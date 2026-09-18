"""Typed errors raised by the run harness.

Four types, no reason-code registry: the acceptance criteria ask for typed
errors and nothing branches on a code (see plan Mechanism balance).
"""
from __future__ import annotations


class HarnessError(Exception):
    """Base class for every error this library raises on purpose.

    Catch this to handle any harness-originated failure without needing to
    enumerate the concrete subclasses.
    """


class IllegalTransitionError(HarnessError):
    """A `RunState` transition outside `runtime.lifecycle._TRANSITIONS`.

    Raised by `runtime.lifecycle.transition()`, and by `Harness.stop()`
    before any process/signal logic runs when the target run is already in
    a terminal state (`COMPLETED`, `FAILED`, `CANCELLED`).
    """


class RunIdentityUnverifiedError(HarnessError):
    """`Harness.stop()` cannot verify the recorded pid is still the run's own child.

    Raised only when this process no longer holds the child's `Popen`
    object and the tri-state pid/start-time check (`runtime.process._pid_status`)
    cannot tell "alive" from "recycled pid" — signalling would risk killing
    an unrelated process, so `stop()` refuses instead of guessing.
    """


class UnsafeCwdError(HarnessError):
    """A `RunSpec.cwd` fails the `Isolation.CLEAN` working-directory recipe.

    Raised by `ClaudeCliProvider.build_launch_plan()` when the caller-supplied
    `cwd` does not exist, sits inside a git repository (or under one), or is
    non-empty without `allow_nonempty_cwd=True`.
    """
