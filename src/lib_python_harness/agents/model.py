"""`AgentDefinition`: the documented Claude Code subagent frontmatter fields,
normalized camelCase -> snake_case, plus the four fields every definition
carries regardless of frontmatter (`body`, `source_scope`, `path`,
`qualified_name`).

`FALLBACK_DESCRIPTION` is the one sentinel `agents.frontmatter.
load_agent_definition` uses when a `.md` file's frontmatter cannot be
parsed at all (plan R2) — never for a file that simply omits a
`description:` key, which loads with an empty description instead.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

FALLBACK_DESCRIPTION = "(agent definition frontmatter could not be parsed)"


@dataclass(frozen=True)
class AgentDefinition:
    """One subagent Claude Code would offer, as `agents.discovery.discover`
    returns it (keyed by `qualified_name`) and `resolve.resolve` consumes it.

    `name` is the frontmatter's own `name:` field, or the file's stem when
    absent. `qualified_name` is `name` unchanged at project/user scope, and
    `f"{plugin_name}:{name}"` at plugin scope (the dict key `discover()`
    uses, and the `RunSpec.agent_name`/`--agent` value `resolve()` carries
    through) — see `agents.frontmatter.load_agent_definition`'s docstring
    for the exact rule.
    """

    name: str
    description: str
    body: str
    source_scope: str  # "project" | "user" | "plugin"
    path: Path
    qualified_name: str
    model: str | None = None
    permission_mode: str | None = None
    effort: str | None = None
    tools: str | None = None
    disallowed_tools: str | None = None
    skills: list[str] | None = None
    max_turns: int | None = None
    hooks: dict[str, Any] | None = None
    mcp_servers: dict[str, Any] | None = None
    omit_claude_md: bool | None = None
