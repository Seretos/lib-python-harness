"""R1 + R5 (offline half) — `provider="codex"` selects the codex provider and
its `stop()` path cancels a running child.

Driven through the real `Harness` against `tests/fixtures/fake_codex.py`
(a replay of a recorded real codex stream) substituted for the `codex`
binary via `Harness(claude_argv=[...])`, so no CLI and no auth are needed.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from lib_python_harness.errors import HarnessError
from lib_python_harness.harness import Harness
from lib_python_harness.providers.base import Isolation, RunSpec
from lib_python_harness.providers.claude_cli import ClaudeCliProvider
from lib_python_harness.runtime.lifecycle import RunState
from lib_python_harness.runtime.store import InMemoryRunStore

FIXTURES = Path(__file__).parent / "fixtures"
FAKE_CODEX = FIXTURES / "fake_codex.py"
FAKE_CLAUDE = FIXTURES / "fake_claude.py"
RECORDED_THREAD_ID = json.loads(
    (FIXTURES / "codex_events_sample.jsonl").read_text(encoding="utf-8").splitlines()[0]
)["thread_id"]

# Flags the CLAUDE provider emits and codex never may.
CLAUDE_ONLY_TOKENS = {"-p", "--output-format", "--setting-sources", "--strict-mcp-config",
                      "--disable-slash-commands", "--system-prompt", "--session-id"}


def _spec(tmp_path, **overrides):
    run_cwd = tmp_path / "run-cwd"
    run_cwd.mkdir(exist_ok=True)
    kwargs = dict(
        prompt="Reply with exactly OK",
        isolation=Isolation.CLEAN,
        model="gpt-5.6-luna",
        provider="codex",
        cwd=run_cwd,
        allow_nonempty_cwd=True,
        artifacts_dir=tmp_path / "artifacts",
    )
    kwargs.update(overrides)
    return RunSpec(**kwargs)


def _provenance(harness, run_id):
    record = harness.store.get(run_id)
    return json.loads(Path(record["provenance_path"]).read_text())


def test_provider_codex_spawns_codex_exec_not_claude(tmp_path):
    """R1 driving test."""
    harness = Harness(claude_argv=[sys.executable, str(FAKE_CODEX)])
    result = harness.run(_spec(tmp_path))

    provenance = _provenance(harness, result.run_id)
    flags = provenance["flags"]
    assert "exec" in flags and "--json" in flags
    assert not CLAUDE_ONLY_TOKENS & set(flags), flags
    assert provenance["provider"] == "codex"
    assert provenance["cli_version"] == "0.154.0"
    # slice-1 consumers keep reading the old key; it aliases cli_version
    assert provenance["claude_version"] == "0.154.0"

    # the codex event stream was parsed into the shared envelope
    assert result.state == RunState.COMPLETED
    assert result.text == "OK"
    assert result.session_id == RECORDED_THREAD_ID


def test_default_provider_is_still_claude(tmp_path):
    # RunSpec's own default, without passing provider at all
    assert RunSpec(prompt="p", isolation=Isolation.CLEAN, model="haiku").provider == "claude"

    harness = Harness(claude_argv=[sys.executable, str(FAKE_CLAUDE)])
    run_cwd = tmp_path / "run-cwd"
    run_cwd.mkdir()
    result = harness.run(RunSpec(  # provider deliberately omitted
        prompt="Reply with exactly OK", isolation=Isolation.CLEAN, model="haiku",
        cwd=run_cwd, allow_nonempty_cwd=True, artifacts_dir=tmp_path / "artifacts",
    ))

    provenance = _provenance(harness, result.run_id)
    assert "-p" in provenance["flags"]
    assert "exec" not in provenance["flags"]
    assert provenance["provider"] == "claude"


def test_explicit_provider_instance_wins_for_its_own_name(tmp_path):
    calls = []

    class RecordingClaude(ClaudeCliProvider):  # distinguishable from the registry entry
        def build_launch_plan(self, spec, **kwargs):
            calls.append(spec)
            return super().build_launch_plan(spec, **kwargs)

    harness = Harness(
        claude_argv=[sys.executable, str(FAKE_CLAUDE)], provider=RecordingClaude()
    )
    # _spec()'s default model ("gpt-5.6-luna") is codex-namespaced; this test
    # exercises claude dispatch, so it needs a model the claude provider's
    # #36 namespace check accepts.
    result = harness.run(_spec(tmp_path, provider="claude", model="haiku"))
    assert _provenance(harness, result.run_id)["provider"] == "claude"
    assert len(calls) == 1, "the injected instance was not the one used"


def test_unknown_provider_raises_harness_error_naming_known_providers(tmp_path):
    harness = Harness(claude_argv=[sys.executable, str(FAKE_CODEX)])
    spec = _spec(tmp_path, provider="gemini")
    with pytest.raises(HarnessError) as excinfo:
        harness.start(spec)
    message = str(excinfo.value)
    assert "gemini" in message
    assert "claude" in message and "codex" in message and "mistral" in message
    assert not (tmp_path / "artifacts").exists() or not list((tmp_path / "artifacts").iterdir())


def _pid_gone(pid: int) -> bool:
    if os.name == "nt":
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, errors="replace",
        ).stdout
        return f'"{pid}"' not in out
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


def test_stop_cancels_running_codex_child(tmp_path):
    """R5 offline half: stop() on a still-running codex run ends CANCELLED and
    leaves no child pid; the partial recorded stream is on disk."""
    harness = Harness(
        store=InMemoryRunStore(),
        claude_argv=[sys.executable, str(FAKE_CODEX), "--sleep", "30"],
    )
    started = harness.start(_spec(tmp_path))
    record = harness.store.get(started.run_id)
    proc = harness._processes[started.run_id]

    time.sleep(0.5)
    assert proc.poll() is None, "fake_codex --sleep must keep the child alive"

    gone_after_stop = False
    try:
        result = harness.stop(started.run_id)
        # observed BEFORE the safety-net kill, which would otherwise make the
        # pid vanish on its own (notably on Windows)
        gone_after_stop = _pid_gone(record["pid"])
    finally:
        if proc.poll() is None:  # never leak the sleeping fake if stop() broke
            proc.kill()

    assert result.state == RunState.CANCELLED
    assert gone_after_stop, "recorded pid survived stop()"

    events_path = Path(record["events_path"])
    assert events_path.stat().st_size > 0
    provenance = _provenance(harness, started.run_id)
    # it was a codex run that got cancelled, not a claude one
    assert "exec" in provenance["flags"] and provenance["provider"] == "codex"


def _provenance_text(harness, run_id):
    return Path(harness.store.get(run_id)["provenance_path"]).read_text()


def _fake_real_home(tmp_path, monkeypatch):
    real = tmp_path / "real-home"
    real.mkdir()
    (real / "auth.json").write_text('{"tok": "SECRET-CREDENTIAL"}')
    monkeypatch.setenv("CODEX_HOME", str(real))


def test_scrubbed_codex_home_is_removed_after_run_completes(tmp_path, monkeypatch):
    _fake_real_home(tmp_path, monkeypatch)
    harness = Harness(claude_argv=[sys.executable, str(FAKE_CODEX)])
    spec = _spec(tmp_path)
    started = harness.start(spec)
    record = harness.store.get(started.run_id)
    home = Path(record["cleanup_paths"][0])
    assert (home / "auth.json").is_file() and home != tmp_path / "real-home"
    result = harness.wait(started.run_id, timeout=60)
    assert result.state == RunState.COMPLETED
    assert not home.exists()
    # provenance records the fact, never the credential
    text = _provenance_text(harness, started.run_id)
    assert json.loads(text)["scrubbed_home"] is True
    assert "SECRET-CREDENTIAL" not in text
    for f in (tmp_path / "artifacts").rglob("*"):
        if f.is_file():
            assert "SECRET-CREDENTIAL" not in f.read_text(errors="ignore")
    assert (tmp_path / "real-home" / "auth.json").is_file()


def test_scrubbed_codex_home_is_removed_after_stop(tmp_path, monkeypatch):
    _fake_real_home(tmp_path, monkeypatch)
    harness = Harness(claude_argv=[sys.executable, str(FAKE_CODEX), "--sleep", "30"])
    started = harness.start(_spec(tmp_path))
    record = harness.store.get(started.run_id)
    home = Path(record["cleanup_paths"][0])
    proc = harness._processes[started.run_id]
    assert home.exists()
    try:
        harness.stop(started.run_id)
    finally:
        if proc.poll() is None:
            proc.kill()
    assert not home.exists()


def test_scrubbed_codex_home_is_removed_when_spawn_fails(tmp_path, monkeypatch):
    _fake_real_home(tmp_path, monkeypatch)
    import lib_python_harness.harness as h

    created = []
    real_plan = h.CodexCliProvider.build_launch_plan

    def spy(self, *a, **k):
        plan = real_plan(self, *a, **k)
        created.extend(plan.cleanup_paths)
        return plan

    def boom(**kwargs):
        raise OSError("spawn failed")

    monkeypatch.setattr(h.CodexCliProvider, "build_launch_plan", spy)
    monkeypatch.setattr(h, "_spawn_detached", boom)
    harness = Harness(claude_argv=[sys.executable, str(FAKE_CODEX)])
    with pytest.raises(OSError):
        harness.start(_spec(tmp_path))
    assert created and not Path(created[0]).exists()


# -- mistral (Vibe CLI) ------------------------------------------------------

FAKE_MISTRAL = FIXTURES / "fake_mistral.py"
RECORDED_MISTRAL_SESSION_ID = json.loads(
    (FIXTURES / "mistral_events_sample.jsonl").read_text(encoding="utf-8").splitlines()[0]
)["sessionId"]


def _mistral_spec(tmp_path, **overrides):
    return _spec(tmp_path, provider="mistral", model="mistral-medium-3.5", **overrides)


def test_provider_mistral_spawns_vibe_headless(tmp_path):
    """R1 driving test."""
    harness = Harness(claude_argv=[sys.executable, str(FAKE_MISTRAL)])
    result = harness.run(_mistral_spec(tmp_path))

    provenance = _provenance(harness, result.run_id)
    flags = provenance["flags"]
    assert "-p" in flags and "--output" in flags and "streaming" in flags
    assert flags[flags.index("--output") + 1] == "streaming"
    assert "--enabled-tools" in flags
    assert "exec" not in flags and "--json" not in flags
    assert not (CLAUDE_ONLY_TOKENS - {"-p"}) & set(flags), flags
    assert "Reply with exactly OK" not in flags  # prompt travels on stdin
    assert provenance["provider"] == "mistral"
    assert provenance["cli_version"] == "2.25.4"

    assert result.state == RunState.COMPLETED
    assert result.text == "OK"
    assert result.session_id == RECORDED_MISTRAL_SESSION_ID


def test_stop_cancels_running_mistral_child(tmp_path):
    """R5 offline half."""
    harness = Harness(
        store=InMemoryRunStore(),
        claude_argv=[sys.executable, str(FAKE_MISTRAL), "--sleep", "30"],
    )
    started = harness.start(_mistral_spec(tmp_path))
    record = harness.store.get(started.run_id)
    proc = harness._processes[started.run_id]
    home = Path(record["cleanup_paths"][0])

    time.sleep(0.5)
    assert proc.poll() is None, "fake_mistral --sleep must keep the child alive"

    gone_after_stop = False
    try:
        result = harness.stop(started.run_id)
        gone_after_stop = _pid_gone(record["pid"])
    finally:
        if proc.poll() is None:
            proc.kill()

    assert result.state == RunState.CANCELLED
    assert gone_after_stop, "recorded pid survived stop()"
    assert Path(record["events_path"]).stat().st_size > 0
    assert _provenance(harness, started.run_id)["provider"] == "mistral"
    assert not home.exists(), "temp VIBE_HOME survived stop()"

    from lib_python_harness.errors import IllegalTransitionError

    with pytest.raises(IllegalTransitionError):
        harness.stop(started.run_id)


def test_temp_vibe_home_is_removed_after_run_completes(tmp_path):
    harness = Harness(claude_argv=[sys.executable, str(FAKE_MISTRAL)])
    started = harness.start(_mistral_spec(tmp_path))
    home = Path(harness.store.get(started.run_id)["cleanup_paths"][0])
    assert home.is_dir()
    result = harness.wait(started.run_id, timeout=60)
    assert result.state == RunState.COMPLETED
    assert not home.exists()
