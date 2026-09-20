"""Apply a loaded `HarnessConfig` on top of what `resolve()` already built.

Field order, highest first: the agent's own `agents:` entry > `defaults:` >
(for profile-selected fields) the named profile > what `resolve()` put
there (frontmatter > host context). A value the project wrote down also
overrides `resolve()`'s plugin-scope drop: that drop is about a plugin's
*own* frontmatter being ignored by the parent, not about project policy.

Patch bases: `tools`/`disallowedTools` patch the definition's own list
(never the host's); `mcpServers` patches the set `resolve()` chose
(definition's, else the host's) - under `isolation: clean` that set starts
empty, so the file names exactly what the child can reach.
"""
from __future__ import annotations

import dataclasses
from typing import Any

from ..errors import ConfigError
from ..providers.base import Isolation, RunSpec
from .schema import HarnessConfig, ListPatch


def _split(value: str | None) -> list[str] | None:
    if value is None:
        return None
    return [item.strip() for item in value.split(",") if item.strip()]


def _apply_list(base: list[str] | None, steps: list[Any]) -> tuple[list[str] | None, bool]:
    """Fold `steps` (list = replace, ListPatch = remove-then-add) over
    `base`. Returns `(result, stated)`; a patch over an absent base that
    leaves nothing stays `None`, never `[]`."""
    stated = False
    current = None if base is None else list(base)
    for step in steps:
        if step is None:
            continue
        stated = True
        if isinstance(step, ListPatch):
            items = [] if current is None else list(current)
            items = [i for i in items if i not in set(step.remove)]
            for name in step.add:
                if name not in items:
                    items.append(name)
            current = items if (items or current is not None) else None
        else:
            current = list(step)
    return current, stated


def apply_config(spec: RunSpec, definition, config: HarnessConfig, host_context) -> RunSpec:
    entry = config.agents.get(definition.qualified_name)
    defaults = config.defaults
    if entry is None and not defaults.model_fields_set:
        return spec  # nothing in any layer concerns this agent

    where = f"agent {definition.qualified_name!r}"
    layers = [defaults] + ([entry] if entry is not None else [])

    def pick(name: str):
        value = None
        for layer in layers:
            candidate = getattr(layer, name)
            if candidate is not None:
                value = candidate
        return value

    isolation_name = pick("isolation") or "inherit"
    profile = None
    if isolation_name == "clean":
        isolation = Isolation.CLEAN
    elif isolation_name == "inherit":
        isolation = Isolation.INHERIT
    else:
        profile = config.profiles.get(isolation_name)
        if profile is None:
            raise ConfigError(
                f"{where}: isolation {isolation_name!r} is neither 'inherit', "
                f"'clean' nor a profile defined under `profiles:` "
                f"(defined: {sorted(config.profiles) or 'none'})"
            )
        isolation = Isolation.INHERIT
    clean = isolation is Isolation.CLEAN

    changes: dict[str, Any] = {"isolation": isolation}
    if clean:
        # CLEAN rejects any cwd inside a git repo (the parent's always is);
        # None takes its fresh-temp-dir recipe. Inherited host values do not
        # leak into a clean child: only what the file states is carried.
        changes.update(cwd=None, permission_mode=None, mcp_servers=None, tools=None)

    for name, attr in (
        ("model", "model"),
        ("effort", "effort"),
        ("permissionMode", "permission_mode"),
    ):
        value = pick(name)
        if value is not None:
            changes[attr] = value

    # -- tools / disallowedTools ------------------------------------------
    profile_tools = profile.tools if profile is not None else None
    tools, tools_stated = _apply_list(
        _split(definition.tools),
        [profile_tools] + [layer.tools for layer in layers],
    )
    if tools_stated:
        changes["tools"] = ", ".join(tools) if tools is not None else None
    disallowed, disallowed_stated = _apply_list(
        _split(definition.disallowed_tools), [layer.disallowedTools for layer in layers]
    )
    if disallowed_stated:
        changes["disallowed_tools"] = (
            ", ".join(disallowed) if disallowed is not None else None
        )
    if profile_tools is not None and not clean:
        changes["session_tools"] = ",".join(tools or [])

    # -- profile fields -----------------------------------------------------
    strict = True  # the child's MCP set is computed below; see README
    if profile is not None:
        if profile.settingSources is not None:
            changes["setting_sources"] = list(profile.settingSources)
        if profile.omitClaudeMd is not None:
            changes["omit_claude_md"] = profile.omitClaudeMd
        if profile.memory is not None:
            changes["memory"] = profile.memory
        if profile.strictMcp is not None:
            strict = profile.strictMcp
    changes["strict_mcp"] = strict

    # -- MCP servers / canSpawn --------------------------------------------
    catalogue = host_context.available_mcp_servers or {}
    dispatch = host_context.dispatch_mcp_server_name
    can_spawn = bool(entry.canSpawn) if entry is not None else False

    servers: dict[str, Any] = (
        {} if clean else dict(spec.mcp_servers or host_context.mcp_servers or {})
    )
    added: set[str] = set()
    for layer in layers:
        if layer.mcpServers is None:
            continue
        for name in layer.mcpServers.remove:
            servers.pop(name, None)
        for name in layer.mcpServers.add:
            if name not in catalogue:
                raise ConfigError(
                    f"{where}: mcpServers.add names {name!r}, which is not in "
                    f"HostContext.available_mcp_servers "
                    f"(available: {sorted(catalogue) or 'none'})"
                )
            servers[name] = catalogue[name]
            added.add(name)
    if dispatch:
        if can_spawn:
            if dispatch not in catalogue:
                raise ConfigError(
                    f"{where}: canSpawn is true but the dispatch server "
                    f"{dispatch!r} is not in HostContext.available_mcp_servers"
                )
            servers[dispatch] = catalogue[dispatch]
        else:
            if dispatch in added:
                raise ConfigError(
                    f"{where}: mcpServers.add names the dispatch server "
                    f"{dispatch!r} but canSpawn is not true"
                )
            servers.pop(dispatch, None)
    elif can_spawn:
        raise ConfigError(
            f"{where}: canSpawn is true but HostContext.dispatch_mcp_server_name "
            "is not set, so there is no dispatch server to grant"
        )
    changes["mcp_servers"] = servers or None

    return dataclasses.replace(spec, **changes)
