"""Offline driving tests for R5, R7, R3 and R4.

R5 — `Harness.stop(run_id)` on a COMPLETED run raises `IllegalTransitionError`
at the façade, before any signal is sent (no early return for terminal
states).

R7 — a real spawn/parse/persist cycle (against tests/fixtures/fake_claude.py,
substituted for the `claude` binary so this runs with no CLI and no auth)
writes a provenance record whose every field matches a value this test
computes independently.

R3 — `start()` then `stop()` ends CANCELLED, with a non-surviving PID and a
partial events log, proven offline (no live `claude` needed) by driving
`fake_claude.py --sleep` as the child instead of the real CLI.

R4 — every terminal state writes a provenance record: both the CANCELLED
route (`stop()`) and the spawn-failure FAILED route (`start()`'s
`_spawn_detached` raising) are gaps `_finalize`'s unconditional write does
not cover, per plan Approach / Premises verified.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

import pytest

from lib_python_harness.harness import Harness
from lib_python_harness.errors import IllegalTransitionError
from lib_python_harness.runtime.lifecycle import RunState
from lib_python_harness.runtime.store import InMemoryRunStore
from lib_python_harness.providers.base import Isolation, RunSpec
from lib_python_harness.providers.claude_cli import CLEAN_ARGV_FLAGS

FAKE_CLAUDE = Path(__file__).parent / "fixtures" / "fake_claude.py"

POSIX_ONLY = pytest.mark.skipif(
    os.name != "posix",
    reason="process control (os.kill, SIGTERM/SIGKILL) is POSIX-only; see runtime/process.py",
)


def test_stop_on_completed_run_raises(monkeypatch):
    store = InMemoryRunStore()
    store.put("run-1", {"run_id": "run-1", "state": RunState.COMPLETED})

    calls = []
    monkeypatch.setattr(
        "lib_python_harness.harness._send_graceful_signal",
        lambda *a, **kw: calls.append((a, kw)) or True,
    )

    harness = Harness(store=store)
    with pytest.raises(IllegalTransitionError):
        harness.stop("run-1")

    # The transition check must precede any process/signal logic — a
    # Harness.stop that returned early for terminal states instead of
    # raising would reach the (patched) signal sender.
    assert calls == []


def test_provenance_fields_from_spawned_run(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    run_cwd = tmp_path / "run-cwd"
    run_cwd.mkdir()

    spec = RunSpec(
        prompt="Reply with exactly OK",
        isolation=Isolation.CLEAN,
        model="haiku",
        effort="medium",
        system_prompt="You are a test double.",
        cwd=run_cwd,
        allow_nonempty_cwd=True,
        artifacts_dir=artifacts_dir,
    )

    harness = Harness(
        store=InMemoryRunStore(),
        claude_argv=[sys.executable, str(FAKE_CLAUDE)],
    )
    result = harness.run(spec)

    # events_path/provenance_path come from the harness's own persisted
    # record (the same `harness.store.get(run_id)[...]` shape already used
    # by tests/test_harness_end_to_end.py), not from test-local path
    # arithmetic — otherwise `events_path.parent == provenance_path.parent`
    # below would just be comparing a test-built variable with itself
    # (tautology::F9, test-critic round 4).
    record = harness.store.get(result.run_id)
    provenance_path = Path(record["provenance_path"])
    events_path = Path(record["events_path"])

    assert provenance_path.exists()
    provenance = json.loads(provenance_path.read_text())

    for flag in CLEAN_ARGV_FLAGS:
        if flag:
            assert flag in provenance["flags"], f"{flag} missing from recorded flags"

    assert Path(provenance["cwd"]) == run_cwd
    assert run_cwd.exists()
    assert provenance["model"] == "haiku"
    assert provenance["effort"] == "medium"
    assert provenance["prompt_sha256"] == hashlib.sha256(
        spec.prompt.encode()
    ).hexdigest()
    assert provenance["system_prompt_sha256"] == hashlib.sha256(
        spec.system_prompt.encode()
    ).hexdigest()
    assert provenance["claude_version"]
    assert re.match(r"\d+\.\d+\.\d+", provenance["claude_version"])
    assert provenance["exit_code"] == 0
    assert provenance["duration_s"] > 0

    assert events_path.exists()
    assert events_path.stat().st_size > 0
    assert events_path.parent == provenance_path.parent


@POSIX_ONLY
def test_stop_cancels_running_child(tmp_path):
    """R3 + R4: `stop()` on a still-RUNNING run kills the child, records
    CANCELLED, and writes a provenance record.

    Drives `fake_claude.py --sleep` (a fixture mode that does not exist yet)
    so there is a real child still alive when `stop()` runs — the plain
    fixture exits the instant it emits its terminal event, so nothing would
    be left to cancel.

    The pre-stop liveness check below reads `proc.poll()` on the harness's
    own `Popen` handle, not `_pid_status(pid, start_time)` as the plan's
    literal wording suggests — measured during this round: an exited-but-
    not-yet-reaped child is still a zombie holding its pid, so
    `_pid_status` (which only compares process identity/start-time) reads
    it as "alive" too, defeating the RED this assertion needs. `proc.poll()`
    reaps-and-reports in one step and is the only check that actually tells
    "still running" apart from "exited, not yet reaped".
    """
    artifacts_dir = tmp_path / "artifacts"
    run_cwd = tmp_path / "run-cwd"
    run_cwd.mkdir()

    spec = RunSpec(
        prompt="Reply with exactly OK",
        isolation=Isolation.CLEAN,
        model="haiku",
        cwd=run_cwd,
        allow_nonempty_cwd=True,
        artifacts_dir=artifacts_dir,
    )

    harness = Harness(
        store=InMemoryRunStore(),
        claude_argv=[sys.executable, str(FAKE_CLAUDE), "--sleep", "5"],
    )
    started = harness.start(spec)
    record = harness.store.get(started.run_id)
    proc = harness._processes[started.run_id]

    # Give the child a moment to either still be sleeping (once --sleep
    # exists) or to have already exited (today, since --sleep is ignored).
    time.sleep(0.2)
    assert proc.poll() is None, (
        "fake_claude did not stay alive long enough for stop() to cancel it "
        "— test_stop_cancels_running_child requires fake_claude.py's "
        "--sleep mode to keep the child alive (RED until it exists)"
    )

    result = harness.stop(started.run_id)

    assert result.state == RunState.CANCELLED
    with pytest.raises(ProcessLookupError):
        os.kill(record["pid"], 0)

    events_path = Path(record["events_path"])
    assert events_path.exists()
    assert events_path.stat().st_size > 0

    # R4: the CANCELLED route must write provenance too, same as the
    # COMPLETED/FAILED routes _finalize already covers.
    record_after = harness.store.get(started.run_id)
    provenance_path = Path(record_after["provenance_path"])
    assert provenance_path.exists()
    provenance = json.loads(provenance_path.read_text())
    # A bare `> 0` is satisfied by any positive literal a writer could
    # return without ever reading `started_at` (test-critic round 1,
    # tautology::F1). Tying the lower bound to the 0.2s we actually slept
    # before calling stop() means only a genuinely time-based duration can
    # pass: a hardcoded small constant (e.g. 0.001) now fails.
    assert provenance["duration_s"] >= 0.15
    assert "-p" in provenance["flags"]


@POSIX_ONLY
def test_poll_observes_running_state(tmp_path):
    """Plan-critic round 3 minor (missed::F1): the ticket's Non-goals name
    "start/stop/poll on the run object" as in scope, but no requirement in
    the plan exercises `Harness.poll()` while a run is genuinely still
    alive — R3/R4 only observe state after `stop()` or a failed `start()`.
    This closes that gap with one cheap additional test (not a plan-declared
    R#); it reuses the same `--sleep` fixture mode R3/R4 already added.
    """
    artifacts_dir = tmp_path / "artifacts"
    run_cwd = tmp_path / "run-cwd"
    run_cwd.mkdir()

    spec = RunSpec(
        prompt="Reply with exactly OK",
        isolation=Isolation.CLEAN,
        model="haiku",
        cwd=run_cwd,
        allow_nonempty_cwd=True,
        artifacts_dir=artifacts_dir,
    )

    harness = Harness(
        store=InMemoryRunStore(),
        claude_argv=[sys.executable, str(FAKE_CLAUDE), "--sleep", "5"],
    )
    started = harness.start(spec)
    time.sleep(0.2)

    result = harness.poll(started.run_id)
    assert result.state == RunState.RUNNING

    harness.stop(started.run_id)


def test_spawn_failure_writes_provenance(tmp_path, monkeypatch):
    """R4: a `start()` whose `_spawn_detached` raises (bogus binary) still
    writes a provenance record for the FAILED run — the third route into a
    terminal state, distinct from `_finalize`'s two (COMPLETED/FAILED).
    """
    artifacts_dir = tmp_path / "artifacts"
    run_cwd = tmp_path / "run-cwd"
    run_cwd.mkdir()
    missing_binary = tmp_path / "no-such-claude"

    spec = RunSpec(
        prompt="Reply with exactly OK",
        isolation=Isolation.CLEAN,
        model="haiku",
        cwd=run_cwd,
        allow_nonempty_cwd=True,
        artifacts_dir=artifacts_dir,
    )

    harness = Harness(
        store=InMemoryRunStore(),
        claude_argv=[str(missing_binary)],
    )

    # `start()`'s spawn-failure route calls `time.monotonic()` exactly
    # twice — once to record `started_at` before the spawn attempt, once in
    # the except block to compute `duration_s` — with nothing else in
    # between (the raise happens inside `_spawn_detached` itself). Pinning
    # both return values makes `duration_s` a value this test independently
    # predicts, not merely a non-negative number: a `_write_provenance` that
    # never reads `started_at` (test-critic round 1, tautology::F1) would
    # fail this exact-equality check even though it would still pass a bare
    # `>= 0`.
    monotonic_values = iter([1_000.0, 1_042.5])
    monkeypatch.setattr(
        "lib_python_harness.harness.time.monotonic",
        lambda: next(monotonic_values),
    )

    with pytest.raises(FileNotFoundError):
        harness.start(spec)

    records = harness.store.list()
    assert len(records) == 1
    record = records[0]
    assert record["state"] == RunState.FAILED

    provenance_path = Path(record["provenance_path"])
    assert provenance_path.exists()
    provenance = json.loads(provenance_path.read_text())

    assert str(missing_binary) in provenance["flags"]
    assert Path(provenance["cwd"]) == run_cwd
    assert provenance["model"] == "haiku"
    assert provenance["prompt_sha256"] == hashlib.sha256(
        spec.prompt.encode()
    ).hexdigest()
    # No process ever existed on this route — exit_code is genuinely null,
    # not a missing field (it is already a key of the provenance dict on
    # every other route).
    assert provenance["exit_code"] is None
    assert provenance["duration_s"] == pytest.approx(42.5)
