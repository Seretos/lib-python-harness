"""`config_dir()` and `enabled_plugins(config_dir, project_dir)`: the merged
`enabledPlugins` map `agents.discovery.discover`'s plugin-scope walk (and
`host.context.HostContext.complete()`) both consult.

Merge order (local wins): `<config_dir>/settings.json`,
`<project_dir>/.claude/settings.json`, `<project_dir>/.claude/settings.local.json`
— each later file's `enabledPlugins` entries overwrite the earlier ones
key-by-key (an explicit `false` in a later file really does disable a key
`true` in an earlier one; a file simply not mentioning a key never touches
it).
"""
from __future__ import annotations

import json
import os
from pathlib import Path


def config_dir() -> Path:
    """`CLAUDE_CONFIG_DIR` if set, else `~/.claude` — the same rule
    `Harness._resolve_transcript_path` already uses."""
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    if env:
        return Path(env)
    return Path.home() / ".claude"


def _read_enabled_plugins(settings_path: Path) -> dict[str, bool]:
    if not settings_path.exists():
        return {}
    try:
        data = json.loads(settings_path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    enabled = data.get("enabledPlugins")
    return dict(enabled) if isinstance(enabled, dict) else {}


def enabled_plugins(config_dir: Path | str, project_dir: Path | str) -> dict[str, bool]:
    """The merged `<plugin>@<marketplace>` -> enabled map across
    config/project/project-local settings, local-wins."""
    config_dir = Path(config_dir)
    project_dir = Path(project_dir)

    merged: dict[str, bool] = {}
    merged.update(_read_enabled_plugins(config_dir / "settings.json"))
    merged.update(_read_enabled_plugins(project_dir / ".claude" / "settings.json"))
    merged.update(_read_enabled_plugins(project_dir / ".claude" / "settings.local.json"))
    return merged
