"""The run lifecycle: an enum of states plus a validated transition table.

Not a free string — `transition()` is the single place "illegal" is
decidable, and it is the only way `RunState` ever changes. The illustrative
"starting" state named in the ticket is deliberately dropped: spawn is
synchronous (`Harness.start()` returns only after the child is already
running), so no observer could ever witness it.

`docs/run-lifecycle.md` documents this table in prose; `tests/test_lifecycle_doc.py`
keeps the two in sync structurally (one "- `FROM` -> `TO`" line per edge).
"""
from __future__ import annotations

import enum

from ..errors import IllegalTransitionError


class RunState(enum.Enum):
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# Terminal states (COMPLETED, FAILED, CANCELLED) carry no outgoing edges —
# enforced by tests/test_lifecycle.py::test_terminal_states_have_no_outgoing_edges
# reading this table directly.
_TRANSITIONS: dict[RunState, set[RunState]] = {
    RunState.CREATED: {RunState.RUNNING, RunState.FAILED},
    RunState.RUNNING: {RunState.COMPLETED, RunState.FAILED, RunState.CANCELLED},
    RunState.COMPLETED: set(),
    RunState.FAILED: set(),
    RunState.CANCELLED: set(),
}


def transition(frm: RunState, to: RunState) -> RunState:
    """Validate and return `to`, or raise `IllegalTransitionError`.

    Pure: does not mutate any record itself. Callers (`Harness`) are
    responsible for actually storing the returned state.
    """
    allowed = _TRANSITIONS.get(frm, set())
    if to not in allowed:
        raise IllegalTransitionError(
            f"illegal run state transition: {frm.name} -> {to.name}"
        )
    return to
