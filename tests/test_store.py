"""Additional coverage for R7 — RunStore round-tripping and the on-disk layout.

R7's driving test is ``tests/test_harness_offline.py::
test_provenance_fields_from_spawned_run``. This file covers the store
protocol itself: ``InMemoryRunStore``, ``FileRunStore``, the
``<artifacts_dir>/<run_id>/`` layout, and a FAILED run recording a non-zero
exit code.
"""
from __future__ import annotations

import json

from lib_python_harness.runtime.store import InMemoryRunStore, FileRunStore
from lib_python_harness.runtime.lifecycle import RunState


def _record(run_id="run-1", state=RunState.COMPLETED, exit_code=0):
    return {"run_id": run_id, "state": state, "exit_code": exit_code}


def test_in_memory_store_round_trips():
    store = InMemoryRunStore()
    store.put("run-1", _record())
    assert store.get("run-1")["run_id"] == "run-1"
    assert "run-1" in [r["run_id"] for r in store.list()]


def test_in_memory_store_get_missing_returns_none():
    store = InMemoryRunStore()
    assert store.get("nope") is None


def test_file_store_layout(tmp_path):
    store = FileRunStore(artifacts_dir=tmp_path)
    store.put("run-1", _record())

    run_dir = tmp_path / "run-1"
    assert (run_dir / "record.json").exists()
    saved = json.loads((run_dir / "record.json").read_text())
    assert saved["run_id"] == "run-1"

    fetched = store.get("run-1")
    assert fetched["run_id"] == "run-1"
    assert any(r["run_id"] == "run-1" for r in store.list())


def test_file_store_records_failed_run_exit_code(tmp_path):
    store = FileRunStore(artifacts_dir=tmp_path)
    store.put("run-2", _record(run_id="run-2", state=RunState.FAILED, exit_code=1))

    fetched = store.get("run-2")
    assert fetched["state"] == RunState.FAILED
    assert fetched["exit_code"] == 1
