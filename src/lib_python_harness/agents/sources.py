"""`DefinitionSource`: the protocol `agents.discovery.discover` walks, and
`ClaudeMarkdownSource`, the one implementation this ticket ships — a
directory of Claude Code agent `.md` files (project/user/plugin `agents/`
trees all share this same on-disk shape).
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Iterator, Protocol

from .frontmatter import load_agent_definition
from .model import AgentDefinition


class DefinitionSource(Protocol):
    """Anything `discover()` can walk for `AgentDefinition`s."""

    def iter_definitions(self) -> Iterable[AgentDefinition]:
        ...


class ClaudeMarkdownSource:
    """Walks `directory` (non-recursively) for `*.md` agent-definition
    files, in sorted filename order (a stable, deterministic walk — the
    same file set always yields the same order, regardless of the host
    filesystem's own directory-listing order).

    `scope` is `"project"`, `"user"`, or `"plugin"`; `plugin_name` is
    required (and only meaningful) at `scope == "plugin"` — it is what
    `load_agent_definition` uses to build the `<plugin>:<name>`
    `qualified_name`. A missing `directory` yields nothing; it is not an
    error (a project/user/plugin tree with no `agents/` folder is normal).
    """

    def __init__(
        self,
        directory: Path | str,
        scope: str,
        plugin_name: str | None = None,
    ) -> None:
        self.directory = Path(directory)
        self.scope = scope
        self.plugin_name = plugin_name

    def iter_definitions(self) -> Iterator[AgentDefinition]:
        if not self.directory.is_dir():
            return
        for path in sorted(self.directory.glob("*.md")):
            yield load_agent_definition(path, self.scope, self.plugin_name)
