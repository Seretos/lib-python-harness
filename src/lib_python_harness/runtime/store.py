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
        path.write_text(json.dumps(_serialize(record), indent=2, default=_json_default))

    def get(self, run_id: str) -> dict[str, Any] | None:
        path = self._record_path(run_id)
        if not path.exists():
            return None
        return _deserialize(json.loads(path.read_text()))

    def list(self) -> list[dict[str, Any]]:
        if not self.artifacts_dir.exists():
            return []
        records = []
        for run_dir in sorted(self.artifacts_dir.iterdir()):
            record_path = run_dir / "record.json"
            if record_path.exists():
                records.append(_deserialize(json.loads(record_path.read_text())))
        return records

    def remove(self, run_id: str) -> None:
        # Drops only this store's own bookkeeping file; the run's artifacts
        # (provenance.json, events.jsonl, stderr.txt) are the consumer's and
        # are never deleted by the library (see Harness.cleanup).
        path = self._record_path(run_id)
        path.unlink(missing_ok=True)
