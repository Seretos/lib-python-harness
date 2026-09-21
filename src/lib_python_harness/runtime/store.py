"""`RunStore`: the protocol `Harness` uses to persist a run's *record*
(metadata — state, pid, paths — not the run's artifacts, which always land
on real disk regardless of store choice; see `Harness._artifacts_base`).

Two implementations: `InMemoryRunStore` (default; no disk I/O, so most unit
tests stay fast) and `FileRunStore` (`<artifacts_dir>/<run_id>/record.json`;
needed because a record living only in this process's memory cannot satisfy
"the partial events log is on disk" across process boundaries).
"""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Protocol

from .lifecycle import RunState


class RunStore(Protocol):
    def put(self, run_id: str, record: dict[str, Any]) -> None: ...

    def get(self, run_id: str) -> dict[str, Any] | None: ...

    def list(self) -> list[dict[str, Any]]: ...

    def remove(self, run_id: str) -> None: ...


class InMemoryRunStore:
    """No disk I/O. Records live only as long as this process does."""

    def __init__(self) -> None:
        self._records: dict[str, dict[str, Any]] = {}

    def put(self, run_id: str, record: dict[str, Any]) -> None:
        self._records[run_id] = dict(record)

    def get(self, run_id: str) -> dict[str, Any] | None:
        record = self._records.get(run_id)
        return dict(record) if record is not None else None

    def list(self) -> list[dict[str, Any]]:
        return [dict(record) for record in self._records.values()]

    def remove(self, run_id: str) -> None:
        self._records.pop(run_id, None)


_REPLACE_RETRY_S = 1.0


def _read_json(path: Path) -> dict[str, Any]:
    """Read a record file, retrying briefly on `PermissionError` (on Windows
    opening a file that a concurrent `put()` is replacing fails with a
    sharing violation) and on `json.JSONDecodeError` (a momentarily
    unparseable file); a persistently bad file raises once the deadline
    passes."""
    deadline = time.monotonic() + _REPLACE_RETRY_S
    while True:
        try:
            return json.loads(path.read_text())
        except (PermissionError, json.JSONDecodeError):
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.005)


def _json_default(value: Any) -> Any:
    if isinstance(value, RunState):
        return value.name
    if isinstance(value, Path):
        return str(value)
    return str(value)


def _serialize(record: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in record.items():
        if isinstance(value, RunState):
            out[key] = {"__runstate__": value.name}
        elif isinstance(value, Path):
            out[key] = str(value)
        else:
            out[key] = value
    return out


def _deserialize(raw: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in raw.items():
        if isinstance(value, dict) and set(value) == {"__runstate__"}:
            out[key] = RunState[value["__runstate__"]]
        else:
            out[key] = value
    return out


class FileRunStore:
    """`<artifacts_dir>/<run_id>/record.json`. `get()`/`list()` always read
    from disk — no in-process cache — so what this store returns is
    genuinely what is on disk, not a copy `put()` happened to keep around.
    """

    def __init__(self, artifacts_dir: str | Path) -> None:
        self.artifacts_dir = Path(artifacts_dir)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)

    def _record_path(self, run_id: str) -> Path:
        return self.artifacts_dir / run_id / "record.json"

    def put(self, run_id: str, record: dict[str, Any]) -> None:
        path = self._record_path(run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(_serialize(record), indent=2, default=_json_default)
        # Atomic: write a sibling temp file, then replace. On Windows the
        # replace can fail with a sharing violation while another process has
        # the destination open, so retry briefly rather than raise.
        tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
        tmp.write_text(payload)
        deadline = time.monotonic() + _REPLACE_RETRY_S
        try:
            while True:
                try:
                    os.replace(tmp, path)
                    return
                except PermissionError:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(0.01)
        finally:
            tmp.unlink(missing_ok=True)

    def get(self, run_id: str) -> dict[str, Any] | None:
        path = self._record_path(run_id)
        if not path.exists():
            return None
        return _deserialize(_read_json(path))

    def list(self) -> list[dict[str, Any]]:
        if not self.artifacts_dir.exists():
            return []
        records = []
        for run_dir in sorted(self.artifacts_dir.iterdir()):
            record_path = run_dir / "record.json"
            if record_path.exists():
                records.append(_deserialize(_read_json(record_path)))
        return records

    def remove(self, run_id: str) -> None:
        # Drops only this store's own bookkeeping file; the run's artifacts
        # (provenance.json, events.jsonl, stderr.txt) are the consumer's and
        # are never deleted by the library (see Harness.cleanup).
        path = self._record_path(run_id)
        path.unlink(missing_ok=True)
