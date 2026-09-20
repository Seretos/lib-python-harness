"""lib-python-harness — Provider-independent subagent engine: lifecycle, dispatch and transport abstraction.

Public re-exports. Everything a consumer is meant to import lives here;
adding, removing, or changing the signature of a name in `__all__` is a
breaking change. Keep `__all__` and the README in sync; `__version__` is
derived from the installed distribution metadata, never hand-edited.
See `README.md` for usage.
"""
from __future__ import annotations

from importlib import metadata as _metadata

from .agents.model import AgentDefinition
from .agents.sources import ClaudeMarkdownSource, DefinitionSource
from .agents.discovery import discover
from .config import HarnessConfig, load_harness_config
from .errors import (
    ConfigError,
    FrontmatterError,
    HarnessError,
    IllegalTransitionError,
    RunIdentityUnverifiedError,
    UnsafeCwdError,
    UnsupportedByProvider,
)
from .harness import Harness, run
from .host.context import HostContext
from .providers.base import Isolation, LaunchPlan, Provider, RunResult, RunSpec
from .providers.claude_cli import ClaudeCliProvider
from .providers.codex_cli import CodexCliProvider
from .providers.mistral_cli import MistralCliProvider
from .resolve import resolve
from .runtime.lifecycle import RunState
from .runtime.store import FileRunStore, InMemoryRunStore, RunStore

try:
    __version__ = _metadata.version("lib-python-harness")
except _metadata.PackageNotFoundError:
    __version__ = "0.0.0+unknown"

__all__ = [
    "AgentDefinition",
    "ClaudeCliProvider",
    "ClaudeMarkdownSource",
    "CodexCliProvider",
    "ConfigError",
    "DefinitionSource",
    "FileRunStore",
    "FrontmatterError",
    "Harness",
    "HarnessConfig",
    "HarnessError",
    "HostContext",
    "IllegalTransitionError",
    "InMemoryRunStore",
    "Isolation",
    "LaunchPlan",
    "MistralCliProvider",
    "Provider",
    "RunIdentityUnverifiedError",
    "RunResult",
    "RunSpec",
    "RunState",
    "RunStore",
    "UnsafeCwdError",
    "UnsupportedByProvider",
    "__version__",
    "discover",
    "load_harness_config",
    "resolve",
    "run",
]
