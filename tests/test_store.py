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
import threading
import time
from pathlib import Path

import pytest

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


_N_PUTS = 1000
_BLOB_LEN = 100_000

_WRITER = """
import sys
from lib_python_harness.runtime.store import FileRunStore
from lib_python_harness.runtime.lifecycle import RunState
store = FileRunStore(sys.argv[1])
blob = "x" * 100_000
for n in range(1, 1001):
    state = RunState.RUNNING if n % 2 else RunState.COMPLETED
    store.put("run-1", {"run_id": "run-1", "state": state, "n": n, "blob": blob})
print(n)
"""


def test_put_is_atomic_under_a_concurrent_reader(tmp_path):
    """A writer process doing >= 1000 put()s never lets a reader process see a
    missing, empty or partial record (get() and list() both)."""
    src = Path(__file__).resolve().parent.parent / "src"
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(src)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])
    )
    store = FileRunStore(artifacts_dir=tmp_path)
    store.put("run-1", {"run_id": "run-1", "state": RunState.RUNNING, "n": 0,
                        "blob": "x" * _BLOB_LEN})

    writer = subprocess.Popen(
        [sys.executable, "-c", _WRITER, str(tmp_path)],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    reads = 0
    seen_n: set[int] = set()
    last_n = 0
    try:
        while writer.poll() is None:
            for record in (store.get("run-1"), store.list()[0]):
                assert set(record) == {"run_id", "state", "n", "blob"}
                assert record["run_id"] == "run-1"
                assert len(record["blob"]) == _BLOB_LEN
                assert set(record["blob"]) == {"x"}
                assert isinstance(record["n"], int)
                assert record["state"] in (RunState.RUNNING, RunState.COMPLETED)
                assert record["n"] >= last_n, "record went backwards"
                last_n = record["n"]
                seen_n.add(record["n"])
                reads += 1
    finally:
        out, err = writer.communicate(timeout=60)

    assert writer.returncode == 0, err
    assert int(out.strip()) == _N_PUTS
    # The reader must genuinely have overlapped the writer, not just glanced.
    assert reads >= 20, f"reader barely overlapped the writer ({reads} reads)"
    assert len(seen_n) >= 5, f"reader observed only {sorted(seen_n)}"


def test_get_retries_while_record_is_momentarily_unparseable(tmp_path):
    store = FileRunStore(artifacts_dir=tmp_path)
    full = {"run_id": "run-1", "state": RunState.RUNNING, "exit_code": None}
    store.put("run-1", full)
    path = tmp_path / "run-1" / "record.json"
    good = path.read_text()
    path.write_text('{"run_id": "run-1", "st')

    def restore():
        tmp = path.with_name("restore.tmp")
        tmp.write_text(good)
        os.replace(tmp, path)

    timer = threading.Timer(0.05, restore)
    timer.start()
    try:
        started = time.monotonic()
        assert store.get("run-1") == full
        # Returns as soon as the record is restored, well inside the deadline.
        assert time.monotonic() - started < 0.9
        path.write_text('{"run_id": "run-1", "st')
        timer2 = threading.Timer(0.05, restore)
        timer2.start()
        try:
            assert store.list() == [full]
        finally:
            timer2.join()
    finally:
        timer.join()


def test_permanently_unparseable_record_still_raises(tmp_path):
    store = FileRunStore(artifacts_dir=tmp_path)
    store.put("run-1", _record())
    (tmp_path / "run-1" / "record.json").write_text('{"run_id": "run-1", "st')
    started = time.monotonic()
    with pytest.raises(json.JSONDecodeError):
        store.get("run-1")
    # Retries up to the deadline (~_REPLACE_RETRY_S = 1 s), then gives up.
    assert 0.8 <= time.monotonic() - started < 5.0


def test_concurrent_puts_from_threads_never_tear_the_record(tmp_path):
    store = FileRunStore(artifacts_dir=tmp_path)
    length = 200_000
    store.put("run-1", {"run_id": "run-1", "state": RunState.RUNNING, "blob": "a" * length})
    errors: list[BaseException] = []

    def writer(ch: str) -> None:
        try:
            for _ in range(200):
                store.put("run-1", {"run_id": "run-1", "state": RunState.RUNNING,
                                    "blob": ch * length})
        except BaseException as exc:  # noqa: BLE001 - collected and asserted below
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(ch,)) for ch in "ab"]
    for t in threads:
        t.start()
    reads = 0
    try:
        while any(t.is_alive() for t in threads):
            blob = store.get("run-1")["blob"]
            assert len(blob) == length
            assert len(set(blob)) == 1
            reads += 1
    finally:
        for t in threads:
            t.join(timeout=60)

    assert errors == []
    assert reads > 0
    assert sorted(p.name for p in (tmp_path / "run-1").iterdir()) == ["record.json"]
