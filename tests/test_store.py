"""Additional coverage for R7 — RunStore round-tripping and the on-disk layout.

R7's driving test is ``tests/test_harness_offline.py::
test_provenance_fields_from_spawned_run``. This file covers the store
protocol itself: ``InMemoryRunStore``, ``FileRunStore``, the
``<artifacts_dir>/<run_id>/`` layout, and a FAILED run recording a non-zero
exit code.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

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


_WRITER = """
import sys, time
from lib_python_harness.runtime.store import FileRunStore
from lib_python_harness.runtime.lifecycle import RunState
store = FileRunStore(sys.argv[1])
deadline = time.monotonic() + float(sys.argv[2])
blob = "x" * 400_000
n = 0
while time.monotonic() < deadline:
    n += 1
    store.put("run-1", {"run_id": "run-1", "state": RunState.RUNNING, "n": n, "blob": blob})
print(n)
"""


def test_put_is_atomic_under_a_concurrent_reader(tmp_path):
    """A record must never be observed half-written by another process."""
    src = Path(__file__).resolve().parent.parent / "src"
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(src)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])
    )
    store = FileRunStore(artifacts_dir=tmp_path)
    store.put("run-1", {"run_id": "run-1", "state": RunState.RUNNING, "n": 0, "blob": "x" * 400_000})

    writer = subprocess.Popen(
        [sys.executable, "-c", _WRITER, str(tmp_path), "2.0"],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    reads = 0
    try:
        while writer.poll() is None:
            for record in (store.get("run-1"), store.list()[0]):
                assert record["run_id"] == "run-1"
                assert len(record["blob"]) == 400_000
                reads += 1
    finally:
        out, err = writer.communicate(timeout=30)

    assert writer.returncode == 0, err
    assert int(out.strip()) > 1, "writer never got going"
    assert reads > 0
