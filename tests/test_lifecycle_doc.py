"""R5 additional coverage — docs/run-lifecycle.md stays in sync with the
transition table, modelled on lib_python_worktree's test_teardown_contract_doc.py.
"""
from __future__ import annotations

import re
from pathlib import Path

from lib_python_harness.runtime.lifecycle import RunState, _TRANSITIONS

DOC_PATH = Path(__file__).resolve().parent.parent / "docs" / "run-lifecycle.md"

# Each legal transition is documented as its own list line, one edge per
# line: "- `FROM` -> `TO`" (ASCII "->" or the Unicode arrow are both
# accepted). This lets the sync test extract the *edges* the doc actually
# claims and diff them against `_TRANSITIONS` structurally, instead of only
# checking that both state names occur somewhere in the file.
_TRANSITION_LINE_RE = re.compile(
    r"^-\s*`([A-Z_]+)`\s*(?:->|→)\s*`([A-Z_]+)`\s*$", re.MULTILINE
)


def _transitions_from_doc() -> set[tuple[str, str]]:
    text = DOC_PATH.read_text()
    return set(_TRANSITION_LINE_RE.findall(text))


def _transitions_from_table() -> set[tuple[str, str]]:
    return {(frm.name, to.name) for frm, tos in _TRANSITIONS.items() for to in tos}


def test_doc_exists():
    assert DOC_PATH.exists(), f"{DOC_PATH} is missing"


def test_doc_mentions_every_state():
    text = DOC_PATH.read_text()
    for state in RunState:
        assert state.name in text, f"{state.name} not documented in {DOC_PATH}"


def test_doc_mentions_every_legal_transition():
    doc_edges = _transitions_from_doc()
    table_edges = _transitions_from_table()
    assert doc_edges == table_edges, (
        f"docs/run-lifecycle.md's transition list has drifted from "
        f"_TRANSITIONS (expected one '- `FROM` -> `TO`' line per edge).\n"
        f"documented but not in _TRANSITIONS: {doc_edges - table_edges}\n"
        f"in _TRANSITIONS but not documented: {table_edges - doc_edges}"
    )
