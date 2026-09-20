"""Pydantic models for `.seretos/harness.yml`.

Every model forbids unknown keys and every field is optional: a layer only
states what it wants to change. Key names are camelCase, matching the
agent-definition frontmatter they retune.
"""
from __future__ import annotations

from typing import Literal, Union

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ListPatch(_Strict):
    """`{add: [...], remove: [...]}` — applied `remove` first, then `add`."""

    add: list[str] = Field(default_factory=list)
    remove: list[str] = Field(default_factory=list)


# A list value replaces; a `{add, remove}` mapping patches.
ListOrPatch = Union[list[str], ListPatch]


class IsolationProfile(_Strict):
    """A named isolation profile, selectable via `isolation: <name>`."""

    settingSources: list[str] | None = None
    strictMcp: bool | None = None
    tools: ListOrPatch | None = None
    omitClaudeMd: bool | None = None
    memory: bool | None = None


class _Overrides(_Strict):
    provider: Literal["claude"] | None = None
    model: str | None = None
    effort: str | None = None
    permissionMode: str | None = None
    isolation: str | None = None
    tools: ListOrPatch | None = None
    disallowedTools: ListOrPatch | None = None
    mcpServers: ListPatch | None = None


class DefaultOverrides(_Overrides):
    """`defaults:` — applies to every agent. No `canSpawn` here: nesting is
    opt-in per agent, never a blanket default."""


class AgentOverride(_Overrides):
    """One `agents:` entry, keyed by qualified agent name."""

    canSpawn: bool | None = None


class HarnessConfig(_Strict):
    defaults: DefaultOverrides = Field(default_factory=DefaultOverrides)
    agents: dict[str, AgentOverride] = Field(default_factory=dict)
    profiles: dict[str, IsolationProfile] = Field(default_factory=dict)
