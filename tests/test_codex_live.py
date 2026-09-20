"""R4 + R5 (live half) — the ticket's symptom against the real `codex` CLI.

requires_codex: needs the installed `codex` CLI plus ChatGPT/API auth.
Excluded from the default run (see pyproject.toml's addopts); run with
`python -m pytest -m requires_codex -q -s tests/test_codex_live.py`.

Model: `HARNESS_CODEX_MODEL`, default `gpt-5.6-luna`. The plan's `gpt-5-mini`
is rejected on ChatGPT-account logins (survey: .adev/4-1/codex-survey.md).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from lib_python_harness import Harness, Isolation, RunSpec, RunState

pytestmark = [
    pytest.mark.requires_codex,
    pytest.mark.skipif(shutil.which("codex") is None, reason="codex CLI not installed"),
]

MODEL = os.environ.get("HARNESS_CODEX_MODEL", "gpt-5.6-luna")


def _process_table() -> dict[int, int]:
    """pid -> parent pid for every live process (Windows: CIM; POSIX: ps)."""
    if os.name == "nt":
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId | ConvertTo-Json"],
            capture_output=True, text=True, timeout=60,
        ).stdout
        return {int(r["ProcessId"]): int(r["ParentProcessId"]) for r in json.loads(out)}
    out = subprocess.run(["ps", "-e", "-o", "pid=,ppid="], capture_output=True, text=True).stdout
    return {int(a): int(b) for a, b in (ln.split() for ln in out.splitlines() if ln.strip())}


def _descendants(root: int) -> set[int]:
    table = _process_table()
    found: set[int] = set()
    frontier = {root}
    while frontier:
        children = {p for p, parent in table.items() if parent in frontier and p not in found}
        found |= children
        frontier = children
    return found


def _alive(pid: int) -> bool:
    return pid in _process_table()


def test_clean_codex_run_returns_ok():
    """R4 driving test: the symptom — a caller can send a prompt to Codex."""
    harness = Harness()
    result = harness.run(
        RunSpec(prompt="Reply with exactly OK", isolation=Isolation.CLEAN,
                model=MODEL, provider="codex")
    )
    print(f"session_id={result.session_id} usage={result.usage}")

    assert result.text == "OK"
    assert result.state == RunState.COMPLETED
    assert result.is_error is False
    assert result.session_id

    record = harness.store.get(result.run_id)
    provenance = json.loads(Path(record["provenance_path"]).read_text())
    assert provenance["provider"] == "codex"
    assert provenance["cli_version"]
    events = Path(record["events_path"])
    assert events.stat().st_size > 0
    first = json.loads(events.read_text(encoding="utf-8").splitlines()[0])
    assert first["type"] == "thread.started"
    assert first["thread_id"] == result.session_id


def test_resume_of_clean_thread_is_measured_not_asserted():
    """Retrospective measurement (printed, never asserted): the survey found an
    `--ephemeral` thread is NOT resumable (`no rollout found`). This prints what
    the installed CLI does for the harness's own session id."""
    result = Harness().run(
        RunSpec(prompt="Remember the word PINEAPPLE. Reply with exactly OK",
                isolation=Isolation.CLEAN, model=MODEL, provider="codex")
    )
    if not result.session_id:
        pytest.skip("no session id to resume")
    proc = subprocess.run(
        [shutil.which("codex"), "exec", "resume", result.session_id, "--json", "--skip-git-repo-check",
         "--ignore-user-config", "-m", MODEL],
        input="What word did I ask you to remember? One word.",
        capture_output=True, text=True, timeout=120,
    )
    print(f"resume rc={proc.returncode}\nstdout={proc.stdout[-300:]}\nstderr={proc.stderr[-300:]}")


def test_stop_cancels_long_codex_run():
    """R5 live half: stop() on a long codex run -> CANCELLED, and neither the
    spawned pid nor any descendant (the npm shim's grandchild codex.exe) survives."""
    harness = Harness()
    started = harness.start(
        RunSpec(
            prompt="Count from 1 to 200000, one number per line, no other text.",
            isolation=Isolation.CLEAN, model=MODEL, provider="codex",
        )
    )
    record = harness.store.get(started.run_id)
    pid = record["pid"]
    events_path = Path(record["events_path"])

    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if events_path.exists() and events_path.stat().st_size > 0:
            break
        time.sleep(0.25)
    assert events_path.stat().st_size > 0, "codex never emitted its first event"

    tree = _descendants(pid)
    print(f"pid={pid} descendants={sorted(tree)}")
    assert harness._processes[started.run_id].poll() is None, "run ended before stop()"

    # Observe survivors BEFORE any cleanup: the safety-net kill below must never
    # run ahead of the assertions, or it would itself establish the "tree is
    # gone" condition being tested.
    result = None
    top_alive = True
    survivors: list = []
    try:
        result = harness.stop(started.run_id)
        top_alive = _alive(pid)
        survivors = [p for p in tree if _alive(p)]
    finally:
        for stray in [pid, *tree]:  # never leak a live model run if stop() is broken
            if _alive(stray) and os.name == "nt":
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(stray)], capture_output=True)

    assert result.state == RunState.CANCELLED
    assert not top_alive, "spawned codex pid survived stop()"
    assert not survivors, f"descendants of the codex process survived stop(): {survivors}"
    assert events_path.stat().st_size > 0  # partial stream kept on disk
