"""lib-python-harness — Provider-independent subagent engine: lifecycle, dispatch and transport abstraction.

Public re-exports. Everything a consumer is meant to import lives here;
adding, removing, or changing the signature of a name in `__all__` is a
breaking change. Keep `__all__`, the README, and the version in sync.
See `README.md` for usage.
"""
from __future__ import annotations

from .errors import (
    HarnessError,
    IllegalTransitionError,
    RunIdentityUnverifiedError,
    UnsafeCwdError,
)
from .harness import Harness, run
from .providers.base import Isolation, LaunchPlan, Provider, RunResult, RunSpec
from .providers.claude_cli import ClaudeCliProvider
from .runtime.lifecycle import RunState
from .runtime.store import FileRunStore, InMemoryRunStore, RunStore

__version__ = "0.1.0"

__all__ = [
    "ClaudeCliProvider",
    "FileRunStore",
    "Harness",
    "HarnessError",
    "IllegalTransitionError",
    "InMemoryRunStore",
    "Isolation",
    "LaunchPlan",
    "Provider",
    "RunIdentityUnverifiedError",
    "RunResult",
    "RunSpec",
    "RunState",
    "RunStore",
    "UnsafeCwdError",
    "__version__",
    "run",
]
