"""R5 additional coverage — docs/run-lifecycle.md stays in sync with the
transition table, modelled on lib_python_worktree's test_teardown_contract_doc.py.
"""
from __future__ import annotations

import re
from pathlib import Path

from lib_python_harness.runtime.lifecycle import _TRANSITIONS

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


def test_doc_exists_and_documents_at_least_one_transition():
    # Folded from the former bare test_doc_exists / test_doc_mentions_every_state
    # (tautology F12): existence plus a bare RunState-name scan is satisfied by
    # a one-line file listing the five state names with no real transitions.
    # Tying existence to "declares at least one structural edge" means a doc
    # that only names the states, without describing any transition, already
    # fails here — the exhaustive edge-set check below is what proves every
    # legal transition (and therefore every state that appears in one) is
    # documented correctly, not merely mentioned.
    assert DOC_PATH.exists(), f"{DOC_PATH} is missing"
    assert _transitions_from_doc(), (
        f"{DOC_PATH} exists but declares no '- `FROM` -> `TO`' transition "
        f"lines — naming the states without documenting any real transition "
        f"between them is not lifecycle documentation"
    )


def test_doc_mentions_every_legal_transition():
    doc_edges = _transitions_from_doc()
    table_edges = _transitions_from_table()
    assert doc_edges == table_edges, (
        f"docs/run-lifecycle.md's transition list has drifted from "
        f"_TRANSITIONS (expected one '- `FROM` -> `TO`' line per edge).\n"
        f"documented but not in _TRANSITIONS: {doc_edges - table_edges}\n"
        f"in _TRANSITIONS but not documented: {table_edges - doc_edges}"
    )
