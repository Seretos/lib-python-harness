"""Process control: spawn, signal, reap. Ported from
`lib-python-worktree/core/process_lifecycle.py` (`_spawn_detached`,
`_send_graceful_signal`, `_force_kill`, `_reap_until_gone`, `_wait_or_kill`,
`_capture_start_time`), copied not imported, POSIX-only per the plan (no
Windows Job Object / handle-scan machinery).

Unlike that reference: stdin carries the run's prompt text (via a backing
file, never a blocking pipe write — see `_spawn_detached`), and
stdout/stderr are split into two separate files (events JSONL vs.
`stderr.txt`) rather than one combined log.

PID identity is tri-state (`_pid_status` returns `True`/`False`/`None`):
a two-valued answer would have to collapse "cannot tell" onto either
"signal it" (risking a recycled pid) or "never signal" (breaking cancel).
`None` means "cannot verify" — `Harness.stop()` only acts on it while this
process still holds the child's own `Popen` object; otherwise it raises
`RunIdentityUnverifiedError` rather than guess.
"""
from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path


def _spawn_detached(
    *,
    argv: list[str],
    cwd: str,
    env: dict[str, str] | None,
    stdin_text: str,
    events_path: Path,
    stderr_path: Path,
) -> subprocess.Popen:
    """Spawn `argv`, stdin from `stdin_text`, stdout to `events_path`,
    stderr to `stderr_path`. POSIX `start_new_session=True` so the child
    survives this process's own controlling terminal/process group.

    The prompt is written to a small sidecar file and handed to the child
    as a real stdin file object (not a `PIPE` we then write to) — a `PIPE`
    write from the parent can deadlock against a child that has not yet
    started reading, for no benefit here since stdout/stderr are already
    going straight to files rather than pipes we'd need to drain.
    """
    events_path = Path(events_path)
    stderr_path = Path(stderr_path)
    events_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)

    stdin_path = events_path.parent / ".stdin"
    stdin_path.write_text(stdin_text or "")

    kwargs: dict = {}
    if os.name == "posix":
        kwargs["start_new_session"] = True

    with open(stdin_path, "rb") as stdin_file, open(events_path, "wb") as events_file, open(
        stderr_path, "wb"
    ) as stderr_file:
        proc = subprocess.Popen(
            argv,
            cwd=cwd,
            env=env,
            stdin=stdin_file,
            stdout=events_file,
            stderr=stderr_file,
            **kwargs,
        )
    return proc


def _capture_start_time(pid: int) -> float | None:
    """Best-effort process start time (epoch seconds), or `None` if it
    cannot be determined. Prefers `psutil` if already importable (no new
    runtime dependency is added by this library); falls back to
    `/proc/<pid>/stat` on Linux.
    """
    try:
        import psutil  # type: ignore
    except ImportError:
        psutil = None  # type: ignore

    if psutil is not None:
        try:
            return psutil.Process(pid).create_time()
        except Exception:
            return None

    try:
        with open(f"/proc/{pid}/stat") as fh:
            data = fh.read()
        after = data.rsplit(")", 1)[1].split()
        starttime_ticks = int(after[19])
        clk_tck = os.sysconf("SC_CLK_TCK")
        with open("/proc/uptime") as fh:
            uptime_seconds = float(fh.read().split()[0])
        boot_time = time.time() - uptime_seconds
        return boot_time + starttime_ticks / clk_tck
    except (FileNotFoundError, ProcessLookupError, IndexError, ValueError, OSError):
        return None


def _raw_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _pid_status(pid: int, expected_start_time: float | None) -> bool | None:
    """Tri-state identity check: `True` (alive and it's the same process),
    `False` (gone, or a different process now holds this pid), `None`
    (cannot tell — e.g. no `psutil` and `/proc` unreadable).
    """
    if expected_start_time is None:
        return None

    current = _capture_start_time(pid)
    if current is None:
        return None if _raw_alive(pid) else False

    if abs(current - expected_start_time) > 1.0:
        return False
    return True


def _send_graceful_signal(pid: int) -> bool:
    """SIGTERM. Returns `True` if delivered, `False` if the pid was already gone."""
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return False
    return True


def _force_kill(pid: int) -> None:
    """SIGKILL, swallowing "already gone"."""
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _reap_until_gone(pid: int, timeout: float = 5.0) -> None:
    """Poll until `pid` is no longer a live/zombie child of this process,
    or `timeout` elapses. Safe to call after the process has already been
    reaped (e.g. via `Popen.wait()`) — `os.waitpid` raising
    `ChildProcessError` just means there is nothing left to reap.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            reaped_pid, _status = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            return
        if reaped_pid == pid:
            return
        if not _raw_alive(pid):
            return
        time.sleep(0.05)


def _wait_or_kill(pid: int, timeout: float, expected_start_time: float | None) -> None:
    """Graceful signal -> bounded wait -> force kill -> reap, identity-checked.

    `timeout=0` skips straight to the force-kill branch (no waiting), which
    is "immediate kill" in effect while still going through the same
    graceful-signal-first code path.
    """
    if _pid_status(pid, expected_start_time) is False:
        return

    _send_graceful_signal(pid)

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _pid_status(pid, expected_start_time) is not True:
            break
        time.sleep(0.05)

    if _pid_status(pid, expected_start_time) is True:
        _force_kill(pid)

    _reap_until_gone(pid)
