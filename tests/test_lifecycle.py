"""Additional coverage for R5 — the RunState transition table.

R5's own driving test is ``tests/test_harness_offline.py::
test_stop_on_completed_run_raises``. This file table-drives ``transition()``
itself: every legal pair inside ``_TRANSITIONS`` succeeds, every pair outside
it raises ``IllegalTransitionError``, and terminal states have no outgoing
edges.
"""
from __future__ import annotations

import pytest

from lib_python_harness.runtime.lifecycle import RunState, _TRANSITIONS, transition
from lib_python_harness.errors import IllegalTransitionError

ALL_STATES = list(RunState)
LEGAL_PAIRS = {(frm, to) for frm, tos in _TRANSITIONS.items() for to in tos}
ILLEGAL_PAIRS = [
    (frm, to) for frm in ALL_STATES for to in ALL_STATES if (frm, to) not in LEGAL_PAIRS
]


@pytest.mark.parametrize(
    "frm,to", sorted(LEGAL_PAIRS, key=lambda p: (p[0].name, p[1].name))
)
def test_legal_transition_succeeds(frm, to):
    assert transition(frm, to) == to


@pytest.mark.parametrize(
    "frm,to", sorted(ILLEGAL_PAIRS, key=lambda p: (p[0].name, p[1].name))
)
def test_illegal_transition_raises(frm, to):
    with pytest.raises(IllegalTransitionError):
        transition(frm, to)


@pytest.mark.parametrize(
    "terminal", [RunState.COMPLETED, RunState.FAILED, RunState.CANCELLED]
)
def test_terminal_states_have_no_outgoing_edges(terminal):
    assert _TRANSITIONS.get(terminal, set()) == set()
