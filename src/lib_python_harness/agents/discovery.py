"""`discover(host_context)`: every subagent Claude Code would offer in this
session — project, user, and enabled-plugin `.md` definitions — keyed by
`qualified_name`, first writer wins (project > user > plugin).
"""
from __future__ import annotations

import json
from pathlib import Path

from ..host.plugins import config_dir, enabled_plugins
from .model import AgentDefinition
from .sources import ClaudeMarkdownSource


def discover(host_context) -> dict[str, AgentDefinition]:
    """`host_context` need only expose `.cwd` (a real `host.context.
    HostContext` or any duck-typed stand-in) — the project directory this
    walk is rooted at.
    """
    project_dir = Path(host_context.cwd)
    cfg_dir = config_dir()

    result: dict[str, AgentDefinition] = {}

    project_source = ClaudeMarkdownSource(
        project_dir / ".claude" / "agents", scope="project"
    )
    user_source = ClaudeMarkdownSource(cfg_dir / "agents", scope="user")
    for source in (project_source, user_source):
        for definition in source.iter_definitions():
            result.setdefault(definition.qualified_name, definition)

    for plugin_key, install_path in _enabled_plugin_install_paths(
        cfg_dir, project_dir
    ).items():
        # "<name>@<marketplace>" -> "<name>": the verified installed_plugins
        # key shape, stripped of its marketplace suffix for qualified_name.
        plugin_name = plugin_key.split("@", 1)[0]
        plugin_source = ClaudeMarkdownSource(
            Path(install_path) / "agents", scope="plugin", plugin_name=plugin_name
        )
        for definition in plugin_source.iter_definitions():
            result.setdefault(definition.qualified_name, definition)

    return result


def _enabled_plugin_install_paths(cfg_dir: Path, project_dir: Path) -> dict[str, str]:
    """Every enabled `installed_plugins.json` key mapped to the one install
    entry the selection rule picks (`projectPath == project_dir` first,
    else `scope == "user"`, else the first entry) — an enabled key with no
    matching entry at all (a stale/ghost plugin reference) is skipped, not
    raised.
    """
    enabled = enabled_plugins(cfg_dir, project_dir)
    installed_path = cfg_dir / "plugins" / "installed_plugins.json"
    if not installed_path.exists():
        return {}
    try:
        data = json.loads(installed_path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    plugins = data.get("plugins") or {}

    result: dict[str, str] = {}
    for key, is_enabled in enabled.items():
        if not is_enabled:
            continue
        entries = plugins.get(key)
        if not entries:
            continue
        entry = _select_install_entry(entries, project_dir)
        if entry is None or not entry.get("installPath"):
            continue
        result[key] = entry["installPath"]
    return result


def _select_install_entry(entries: list[dict], project_dir: Path) -> dict | None:
    project_dir_str = str(project_dir)
    for entry in entries:
        if entry.get("projectPath") == project_dir_str:
            return entry
    for entry in entries:
        if entry.get("scope") == "user":
            return entry
    return entries[0] if entries else None
