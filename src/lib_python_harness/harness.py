"""The façade: `Harness` (start/poll/stop/cleanup/run) plus the module-level
`run(spec)` convenience the acceptance criterion's literal `run(RunSpec(...))`
resolves to.

Named `harness.py`, not `run.py`, on purpose: a submodule literally called
`lib_python_harness.run` would collide with (shadow, or be shadowed by) the
exported callable `lib_python_harness.run` — see `tests/test_public_api.py::
test_run_resolves_to_a_function_not_the_facade_module`.

`Harness` owns two things a `Provider` does not: the run's *lifecycle*
(`RunState` + `_TRANSITIONS`, enforced by `runtime.lifecycle.transition`) and
its *artifacts* — `provenance.json`, `events.jsonl` and `stderr.txt` always
land on real disk under `<artifacts_dir>/<run_id>/` regardless of which
`RunStore` is used for the run *record* (default: `InMemoryRunStore`, so a
plain `Harness()` call never leaves a stray `record.json` around, while
still writing a real provenance file — see the plan-critic note this
resolves: the acceptance call `run(RunSpec(prompt=..., isolation=...,
model=...))` supplies no `artifacts_dir`, so the harness falls back to a
`Harness`-owned temp directory it creates lazily, distinct from the
consumer-owned `artifacts_dir` case `cleanup()` never deletes).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid as uuid_module
from pathlib import Path
from typing import Any

from .errors import HarnessError, RunIdentityUnverifiedError
from .providers.base import RunResult, RunSpec
from .providers.claude_cli import ClaudeCliProvider
from .runtime.lifecycle import RunState, transition
from .runtime.process import (
    _capture_start_time,
    _force_kill,
    _pid_status,
    _reap_until_gone,
    _send_graceful_signal,
    _spawn_detached,
)
from .runtime.store import InMemoryRunStore, RunStore

DEFAULT_STOP_TIMEOUT = 10.0

_VERSION_RE = re.compile(r"\d+\.\d+\.\d+")
_UNSET = object()


class Harness:
    """Owns the run lifecycle for a `Provider`: `start`, `poll`, `stop`,
    `cleanup`, and `run` (= `start` + `wait`, one code path).
    """

    def __init__(
        self,
        store: RunStore | None = None,
        claude_argv: list[str] | None = None,
        provider: ClaudeCliProvider | None = None,
    ) -> None:
        self.store: RunStore = store if store is not None else InMemoryRunStore()
        self.claude_argv: list[str] = list(claude_argv) if claude_argv is not None else ["claude"]
        self.provider = provider if provider is not None else ClaudeCliProvider()
        self._default_artifacts_dir: Path | None = None
        self._processes: dict[str, subprocess.Popen] = {}
        self._version_cache: str | None | object = _UNSET

    # -- artifacts ---------------------------------------------------------

    def _artifacts_base(self, spec: RunSpec) -> Path:
        if spec.artifacts_dir is not None:
            return Path(spec.artifacts_dir)
        if self._default_artifacts_dir is None:
            self._default_artifacts_dir = Path(
                tempfile.mkdtemp(prefix="lib-python-harness-runs-")
            )
        return self._default_artifacts_dir

    def _claude_version(self) -> str | None:
        if self._version_cache is _UNSET:
            text = ""
            try:
                proc = subprocess.run(
                    self.claude_argv + ["--version"],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                text = (proc.stdout or "") + (proc.stderr or "")
            except (OSError, subprocess.TimeoutExpired):
                text = ""
            match = _VERSION_RE.search(text)
            self._version_cache = match.group(0) if match else None
        return self._version_cache  # type: ignore[return-value]

    # -- lifecycle -----------------------------------------------------

    def start(self, spec: RunSpec) -> RunResult:
        run_id = str(uuid_module.uuid4())
        session_id = str(uuid_module.uuid4())
        run_dir = self._artifacts_base(spec) / run_id

        # Raises UnsafeCwdError before anything is ever recorded, if spec.cwd
        # fails the CLEAN recipe.
        plan = self.provider.build_launch_plan(spec, session_id=session_id, run_dir=run_dir)

        run_dir.mkdir(parents=True, exist_ok=True)
        events_path = run_dir / "events.jsonl"
        stderr_path = run_dir / "stderr.txt"

        record: dict[str, Any] = {
            "run_id": run_id,
            "session_id": session_id,
            "state": RunState.CREATED,
            "run_dir": run_dir,
            "cwd": Path(plan.cwd),
            "events_path": events_path,
            "stderr_path": stderr_path,
            "model": spec.model,
            "effort": spec.effort,
            "prompt_sha256": hashlib.sha256(spec.prompt.encode()).hexdigest(),
            "system_prompt_sha256": hashlib.sha256(
                (spec.system_prompt or "").encode()
            ).hexdigest(),
            "allow_nonempty_cwd": spec.allow_nonempty_cwd,
        }
        self.store.put(run_id, record)

        argv = self.claude_argv + plan.argv
        # Names present in this process's own environment that did not make
        # it into plan.env — what the provider actually scrubbed for this run.
        scrubbed_env = sorted(set(os.environ) - set(plan.env))
        record["argv"] = argv
        record["scrubbed_env"] = scrubbed_env
        self.store.put(run_id, record)

        started_at = time.monotonic()
        try:
            proc = _spawn_detached(
                argv=argv,
                cwd=plan.cwd,
                env=plan.env,
                stdin_text=plan.stdin,
                events_path=events_path,
                stderr_path=stderr_path,
            )
        except Exception:
            record["state"] = transition(record["state"], RunState.FAILED)
            self.store.put(run_id, record)
            raise

        pid = proc.pid
        start_time = _capture_start_time(pid)
        self._processes[run_id] = proc

        record["state"] = transition(record["state"], RunState.RUNNING)
        record.update(
            {
                "pid": pid,
                "start_time": start_time,
                "started_at": started_at,
            }
        )
        self.store.put(run_id, record)

        return self._record_to_result(record)

    def poll(self, run_id: str) -> RunResult:
        record = self._require_record(run_id)
        if record["state"] == RunState.RUNNING:
            proc = self._processes.get(run_id)
            if proc is not None and proc.poll() is not None:
                self._finalize(run_id, record, proc)
                record = self._require_record(run_id)
        return self._record_to_result(record)

    def wait(self, run_id: str, timeout: float | None = None) -> RunResult:
        record = self._require_record(run_id)
        proc = self._processes.get(run_id)
        if proc is not None and record["state"] == RunState.RUNNING:
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                return self.stop(run_id)
            record = self._require_record(run_id)
            self._finalize(run_id, record, proc)
            record = self._require_record(run_id)
        return self._record_to_result(record)

    def run(self, spec: RunSpec) -> RunResult:
        started = self.start(spec)
        return self.wait(started.run_id, timeout=spec.timeout)

    def stop(self, run_id: str, timeout: float = DEFAULT_STOP_TIMEOUT) -> RunResult:
        record = self._require_record(run_id)

        # No terminal-state early return: this is the first thing that can
        # observably happen. A stop() on an already-COMPLETED/FAILED/
        # CANCELLED run raises right here, before any signal is ever sent —
        # see tests/test_harness_offline.py::test_stop_on_completed_run_raises,
        # which asserts nothing reaches the (patched) signal sender.
        transition(record["state"], RunState.CANCELLED)

        pid = record.get("pid")
        start_time = record.get("start_time")
        proc = self._processes.get(run_id)

        if pid is not None:
            status = _pid_status(pid, start_time)
            if status is None:
                if proc is None:
                    raise RunIdentityUnverifiedError(
                        f"cannot verify identity of pid {pid} for run {run_id}; "
                        "refusing to signal a possibly-recycled pid"
                    )
                status = True  # this process still holds the child's Popen

            if status:
                _send_graceful_signal(pid)
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    if _pid_status(pid, start_time) is not True:
                        break
                    time.sleep(0.05)
                if _pid_status(pid, start_time) is True:
                    _force_kill(pid)
                _reap_until_gone(pid)

        if proc is not None:
            try:
                proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                pass
            if proc.returncode is not None:
                record["exit_code"] = proc.returncode

        record["duration_s"] = time.monotonic() - record.get("started_at", time.monotonic())
        record["state"] = transition(record["state"], RunState.CANCELLED)
        self.store.put(run_id, record)
        self._processes.pop(run_id, None)
        return self._record_to_result(record)

    def cleanup(self, run_id: str, remove_cwd: bool = False) -> None:
        """Drop the run's record from the store and stop tracking its
        process handle. Never touches the CLI transcript. Removes the run's
        cwd only when `remove_cwd=True` (default `False`) — whether resuming
        a session needs its original cwd is unverified, so the safer default
        is to leave it. The artifacts dir (`provenance.json`, `events.jsonl`,
        `stderr.txt`) is never deleted by the library.
        """
        record = self._require_record(run_id)
        self._processes.pop(run_id, None)
        if remove_cwd:
            cwd = record.get("cwd")
            if cwd:
                shutil.rmtree(Path(cwd), ignore_errors=True)
        self.store.remove(run_id)

    # -- internals -----------------------------------------------------

    def _require_record(self, run_id: str) -> dict[str, Any]:
        record = self.store.get(run_id)
        if record is None:
            raise HarnessError(f"unknown run_id: {run_id}")
        return record

    def _resolve_transcript_path(self, session_id: str) -> Path | None:
        config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
        base = Path(config_dir) if config_dir else Path.home() / ".claude"
        matches = sorted(base.glob(f"projects/*/{session_id}.jsonl"))
        return matches[0] if matches else None

    def _finalize(self, run_id: str, record: dict[str, Any], proc: subprocess.Popen) -> None:
        events_path = Path(record["events_path"])
        exit_code = proc.returncode
        duration_s = time.monotonic() - record["started_at"]

        lines: list[str] = []
        if events_path.exists():
            lines = [ln for ln in events_path.read_text().splitlines() if ln.strip()]

        parse_error: Exception | None = None
        parsed: RunResult | None = None
        try:
            parsed = self.provider.parse_events(lines)
        except Exception as exc:  # missing terminal event => FAILED
            parse_error = exc

        session_id = record["session_id"]
        transcript_path = self._resolve_transcript_path(session_id)

        provenance = {
            "flags": record["argv"],
            "cwd": str(record["cwd"]),
            "model": record.get("model"),
            "effort": record.get("effort"),
            "prompt_sha256": record.get("prompt_sha256"),
            "system_prompt_sha256": record.get("system_prompt_sha256"),
            "claude_version": self._claude_version(),
            "exit_code": exit_code,
            "duration_s": duration_s,
            "scrubbed_env": record.get("scrubbed_env", []),
            "allow_nonempty_cwd": record.get("allow_nonempty_cwd", False),
            "session_id": session_id,
        }
        provenance_path = Path(record["run_dir"]) / "provenance.json"
        provenance_path.write_text(json.dumps(provenance, indent=2))

        new_state = RunState.FAILED if (parse_error is not None or exit_code != 0) else RunState.COMPLETED
        record["state"] = transition(record["state"], new_state)
        record["exit_code"] = exit_code
        record["duration_s"] = duration_s
        record["provenance_path"] = provenance_path
        record["transcript_path"] = transcript_path
        if parsed is not None:
            record["text"] = parsed.text
            record["is_error"] = parsed.is_error
            record["subtype"] = parsed.subtype
            record["structured_output"] = parsed.structured_output
            record["usage"] = parsed.usage
            record["cost"] = parsed.cost
            if parsed.session_id:
                record["session_id"] = parsed.session_id

        self.store.put(run_id, record)
        self._processes.pop(run_id, None)

    def _record_to_result(self, record: dict[str, Any]) -> RunResult:
        return RunResult(
            run_id=record.get("run_id"),
            session_id=record.get("session_id"),
            text=record.get("text", ""),
            is_error=record.get("is_error", False),
            subtype=record.get("subtype"),
            structured_output=record.get("structured_output"),
            usage=record.get("usage", {}),
            cost=record.get("cost"),
            transcript_path=record.get("transcript_path"),
            state=record.get("state"),
            duration_s=record.get("duration_s"),
        )


def run(spec: RunSpec) -> RunResult:
    """Module-level convenience: `Harness().run(spec)`. The acceptance
    criterion's literal surface form `run(RunSpec(...))` resolves here — a
    plain function, not `lib_python_harness.harness` the module (see
    `tests/test_public_api.py::test_run_resolves_to_a_function_not_the_facade_module`).
    """
    return Harness().run(spec)
