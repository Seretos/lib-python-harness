"""Provider-independent types: `Isolation`, `RunSpec`, `LaunchPlan`,
`RunResult`, and the `Provider` protocol every CLI adapter implements.

`ClaudeCliProvider` (`providers.claude_cli`) is the only implementation this
ticket ships. A `Provider` has exactly two responsibilities:

- `build_launch_plan(spec, session_id=..., run_dir=...)` — turn a `RunSpec`
  into an argv/cwd/env/stdin `LaunchPlan`, enforcing whatever isolation
  recipe its `Isolation` member implies.
- `parse_events(lines)` — turn the provider's own event stream (one JSON
  object per line for `ClaudeCliProvider`) into a `RunResult`.

What a future Codex/Mistral provider is explicitly *not* required to add to
this protocol (named per the plan-critic note that a blanket "anything else
is open" sentence documents no boundary at all):

- streaming/partial-output callbacks mid-run (`parse_events` is a one-shot,
  whole-stream parse; a provider may still emit partial events to disk, but
  nothing in this protocol subscribes to them as they arrive);
- non-JSON-lines event formats (`parse_events` takes `Iterable[str]`, one
  JSON object per line — a provider whose CLI emits something else must
  translate to that shape itself, outside this protocol);
- tool/plugin/MCP passthrough configuration (out of scope for `Isolation.CLEAN`
  by definition; a future non-CLEAN isolation profile would need a new
  `Isolation` member, not a `Provider` method);
- multi-turn conversation assembly (`RunSpec` carries exactly one `prompt`
  per call; resuming a session is a separate CLI invocation, not a
  `Provider` method — see `Harness`/README for the resume pattern).
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Protocol


class Isolation(enum.Enum):
    """The isolation profile a run is spawned under.

    Only `CLEAN` exists in this ticket: no user/project settings, no
    plugins, no skills, no MCP servers, no hooks, no CLAUDE.md, no
    auto-memory. Further profiles (e.g. a "trusted" one that keeps project
    settings) are a later ticket's addition, not this one's.
    """

    CLEAN = "clean"


@dataclass
class RunSpec:
    """What a caller wants run, and under what isolation.

    `cwd=None` means "spawn in a fresh, empty temp directory the harness
    creates" — the default, and the only way the `CLEAN` no-auto-memory
    guarantee is actually enforced (memory is keyed by cwd; a directory the
    harness just created has never had `claude` run in it, so it has no
    memory to load). A caller-supplied `cwd` must exist, must not sit inside
    (or under) a git repository, and must be empty unless
    `allow_nonempty_cwd=True` — the one recorded opt-out, meant for
    diagnostics/probes that need to plant files into the child's cwd.
    """

    prompt: str
    isolation: Isolation
    model: str
    effort: str | None = None
    system_prompt: str | None = None
    json_schema: dict[str, Any] | None = None
    cwd: str | Path | None = None
    allow_nonempty_cwd: bool = False
    artifacts_dir: str | Path | None = None
    timeout: float | None = None


@dataclass(frozen=True)
class LaunchPlan:
    """The fully-built command line a `Provider` wants spawned.

    `argv` never includes the binary itself — `Harness.claude_argv` (default
    `["claude"]`, overridable for tests/alternate installs) is prepended by
    the harness at spawn time. The prompt travels on `stdin`, never `argv`.
    """

    argv: list[str]
    cwd: str
    env: dict[str, str]
    stdin: str


@dataclass(frozen=True)
class RunResult:
    """The result envelope. `Provider.parse_events()` fills the content
    fields (`text`, `is_error`, `subtype`, `structured_output`, `usage`,
    `cost`, `session_id`); `Harness` fills the run-identity/lifecycle fields
    (`run_id`, `transcript_path`, `state`, `duration_s`) that no single
    event in the stream carries.
    """

    run_id: str | None = None
    text: str = ""
    is_error: bool = False
    subtype: str | None = None
    structured_output: Any | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    cost: float | None = None
    session_id: str | None = None
    transcript_path: Path | None = None
    state: Any | None = None
    duration_s: float | None = None


class Provider(Protocol):
    """The seam a CLI adapter implements. See module docstring for the
    explicitly-named boundary of what else this protocol does and does not
    cover.
    """

    def build_launch_plan(
        self, spec: RunSpec, *, session_id: str, run_dir: Path
    ) -> LaunchPlan:
        """Build the argv/cwd/env/stdin for `spec`, enforcing `spec.isolation`.

        Raises `UnsafeCwdError` if `spec.cwd` fails the CLEAN cwd recipe.
        """
        ...

    def parse_events(self, lines: Iterable[str]) -> RunResult:
        """Parse one JSON-object-per-line event stream into a `RunResult`.

        Raises if the stream ends without a terminal result event — a
        truncated stream is never silently accepted as success.
        """
        ...
