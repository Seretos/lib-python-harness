"""R4 + R5 (live half) — the ticket's symptom against the real `vibe` CLI.

requires_mistral: needs the installed Mistral Vibe CLI plus auth
(`MISTRAL_API_KEY` or the OS keyring entry `vibe --setup` writes). Excluded from
the default run (see pyproject.toml's addopts); run with
`python -m pytest -m requires_mistral -q -s tests/test_mistral_live.py`.

Model: `HARNESS_MISTRAL_MODEL`, default `mistral-medium-3.5` (Vibe's fresh-home
default alias).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from lib_python_harness import Harness, Isolation, RunSpec, RunState

pytestmark = [
    pytest.mark.requires_mistral,
    pytest.mark.skipif(shutil.which("vibe") is None, reason="vibe CLI not installed"),
]

MODEL = os.environ.get("HARNESS_MISTRAL_MODEL", "mistral-medium-3.5")


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


def _inventory(root: Path) -> dict[str, tuple[int, int]]:
    if not root.exists():
        return {}
    return {
        str(p.relative_to(root)): (p.stat().st_mtime_ns, p.stat().st_size)
        for p in root.rglob("*") if p.is_file()
    }


def test_clean_mistral_run_returns_ok():
    """R4 driving test: the symptom — a caller can send a prompt to Mistral."""
    real_home = Path.home() / ".vibe"
    before = _inventory(real_home)

    harness = Harness()
    started = harness.start(
        RunSpec(prompt="Reply with exactly OK", isolation=Isolation.CLEAN,
                model=MODEL, provider="mistral")
    )
    record = harness.store.get(started.run_id)
    temp_home = Path(record["cleanup_paths"][0])
    result = harness.wait(started.run_id, timeout=240)
    print(f"session_id={result.session_id}")

    assert result.text == "OK"
    assert result.state == RunState.COMPLETED
    assert result.is_error is False
    assert result.session_id

    provenance = json.loads(Path(record["provenance_path"]).read_text())
    assert provenance["provider"] == "mistral"
    assert re.fullmatch(r"\d+\.\d+\.\d+", provenance["cli_version"] or ""), provenance["cli_version"]
    events = Path(record["events_path"])
    assert events.stat().st_size > 0
    first = json.loads(events.read_text(encoding="utf-8").splitlines()[0])
    assert first["sessionId"] == result.session_id

    assert not temp_home.exists(), "temp VIBE_HOME survived the run"
    assert _inventory(real_home) == before, "the user's real ~/.vibe was touched"


def test_stop_cancels_long_mistral_run():
    """R5 live half: stop() on a long run -> CANCELLED, and neither the spawned
    pid nor any descendant (the uv trampoline's python.exe) survives."""
    harness = Harness()
    started = harness.start(
        RunSpec(
            prompt="Count from 1 to 200000, one number per line, no other text.",
            isolation=Isolation.CLEAN, model=MODEL, provider="mistral",
        )
    )
    record = harness.store.get(started.run_id)
    pid = record["pid"]
    events_path = Path(record["events_path"])
    temp_home = Path(record["cleanup_paths"][0])

    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if events_path.exists() and events_path.stat().st_size > 0:
            break
        time.sleep(0.25)
    assert events_path.stat().st_size > 0, "vibe never emitted its first entry"

    tree = _descendants(pid)
    print(f"pid={pid} descendants={sorted(tree)}")
    assert harness._processes[started.run_id].poll() is None, "run ended before stop()"

    # Observe survivors BEFORE any cleanup: the safety-net kill below must never
    # run ahead of the assertions.
    result = None
    top_alive = True
    survivors: list = []
    try:
        result = harness.stop(started.run_id)
        top_alive = _alive(pid)
        survivors = [p for p in tree if _alive(p)]
    finally:
        for stray in [pid, *tree]:
            if _alive(stray) and os.name == "nt":
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(stray)], capture_output=True)

    assert result.state == RunState.CANCELLED
    assert not top_alive, "spawned vibe pid survived stop()"
    assert not survivors, f"descendants of the vibe process survived stop(): {survivors}"
    assert events_path.stat().st_size > 0  # partial stream kept on disk
    assert not temp_home.exists(), "temp VIBE_HOME survived stop()"
