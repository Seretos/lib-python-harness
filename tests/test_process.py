"""Offline coverage for R4 — the spawn/stop path, run against a local subprocess.

Ported behaviour from lib_python_worktree's core/process_lifecycle.py
(``_spawn_detached``, ``_send_graceful_signal``, ``_force_kill``,
``_reap_until_gone``, ``_wait_or_kill``, ``_capture_start_time``), POSIX-only
per the plan (no Windows Job Object / handle-scan machinery — see plan
Mechanism balance / Removed). Unlike that reference, stdin carries the run's
prompt text (piped, not DEVNULL) and stdout/stderr are split into two
separate files (events JSONL vs. stderr.txt) rather than one combined log.
"""
from __future__ import annotations

import sys
import time

from lib_python_harness.runtime.process import (
    _spawn_detached,
    _send_graceful_signal,
    _force_kill,
    _reap_until_gone,
    _wait_or_kill,
    _capture_start_time,
    _pid_status,
)


def _spawn(tmp_path, code):
    return _spawn_detached(
        argv=[sys.executable, "-c", code],
        cwd=str(tmp_path),
        env=None,
        stdin_text="",
        events_path=tmp_path / "events.jsonl",
        stderr_path=tmp_path / "stderr.txt",
    )


def test_graceful_exit_on_sigterm(tmp_path):
    proc = _spawn(tmp_path, "import time; time.sleep(30)")
    start_time = _capture_start_time(proc.pid)
    assert start_time is not None

    delivered = _send_graceful_signal(proc.pid)
    assert delivered

    proc.wait(timeout=5)
    assert proc.returncode is not None
    _reap_until_gone(proc.pid)
    assert _pid_status(proc.pid, start_time) is False


def test_sigterm_ignoring_child_escalates_to_kill(tmp_path):
    code = (
        "import signal, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "time.sleep(30)\n"
    )
    proc = _spawn(tmp_path, code)
    start_time = _capture_start_time(proc.pid)

    began = time.monotonic()
    _wait_or_kill(proc.pid, timeout=1.0, expected_start_time=start_time)
    elapsed = time.monotonic() - began

    assert elapsed < 5.0
    assert _pid_status(proc.pid, start_time) is False


def test_timeout_zero_forces_immediate_kill(tmp_path):
    proc = _spawn(tmp_path, "import time; time.sleep(30)")
    start_time = _capture_start_time(proc.pid)

    began = time.monotonic()
    _wait_or_kill(proc.pid, timeout=0, expected_start_time=start_time)
    elapsed = time.monotonic() - began

    assert elapsed < 2.0
    assert _pid_status(proc.pid, start_time) is False


def test_pid_status_reports_mismatched_identity_as_not_alive(tmp_path):
    proc = _spawn(tmp_path, "import time; time.sleep(30)")
    real_start_time = _capture_start_time(proc.pid)

    assert _pid_status(proc.pid, real_start_time) is True
    # A start time that does not match the live process's own must never
    # read as "alive" — this is the tri-state identity check stop() relies
    # on before ever signalling a possibly-recycled pid.
    assert _pid_status(proc.pid, real_start_time - 999) is False

    _force_kill(proc.pid)
    _reap_until_gone(proc.pid)
