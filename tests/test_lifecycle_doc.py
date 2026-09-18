"""R5 additional coverage — docs/run-lifecycle.md stays in sync with the
transition table, modelled on lib_python_worktree's test_teardown_contract_doc.py.
"""
from __future__ import annotations

from pathlib import Path

from lib_python_harness.runtime.lifecycle import RunState, _TRANSITIONS

DOC_PATH = Path(__file__).resolve().parent.parent / "docs" / "run-lifecycle.md"


def test_doc_exists():
    assert DOC_PATH.exists(), f"{DOC_PATH} is missing"


def test_doc_mentions_every_state():
    text = DOC_PATH.read_text()
    for state in RunState:
        assert state.name in text, f"{state.name} not documented in {DOC_PATH}"


def test_doc_mentions_every_legal_transition():
    text = DOC_PATH.read_text()
    for frm, tos in _TRANSITIONS.items():
        for to in tos:
            assert frm.name in text and to.name in text, (
                f"transition {frm.name} -> {to.name} not documented in {DOC_PATH}"
            )
