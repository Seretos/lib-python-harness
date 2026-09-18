"""Offline driving tests for R5 and R7.

R5 — `Harness.stop(run_id)` on a COMPLETED run raises `IllegalTransitionError`
at the façade, before any signal is sent (no early return for terminal
states).

R7 — a real spawn/parse/persist cycle (against tests/fixtures/fake_claude.py,
substituted for the `claude` binary so this runs with no CLI and no auth)
writes a provenance record whose every field matches a value this test
computes independently.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

from lib_python_harness.harness import Harness
from lib_python_harness.errors import IllegalTransitionError
from lib_python_harness.runtime.lifecycle import RunState
from lib_python_harness.runtime.store import InMemoryRunStore
from lib_python_harness.providers.base import Isolation, RunSpec
from lib_python_harness.providers.claude_cli import CLEAN_ARGV_FLAGS

FAKE_CLAUDE = Path(__file__).parent / "fixtures" / "fake_claude.py"


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
