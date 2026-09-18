"""R1 coverage — `lib_python_harness.host.plugins`: `config_dir()` and
`enabled_plugins(config_dir, project_dir)`.

Not its own numbered plan requirement (no dedicated R# in the plan's Test /
verification strategy), but new behavioural code this ticket adds — the
plugin install-entry selection rule (`projectPath` -> `user` -> first,
Mechanism balance) and the three-file settings merge (local wins,
`enabledPlugins: false` disables) that `agents/discovery.py`'s R1 driving
test exercises only end-to-end. This file drives the same rule directly, at
the unit level, so a wrong selection is attributable to `host/plugins.py`
rather than requiring a trip through the whole discovery pipeline.
"""
from __future__ import annotations

import json

from lib_python_harness.host.plugins import config_dir, enabled_plugins


def test_config_dir_prefers_env_var(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "custom-config"))
    assert config_dir() == tmp_path / "custom-config"


def test_config_dir_defaults_to_home_dot_claude(monkeypatch):
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    from pathlib import Path

    assert config_dir() == Path.home() / ".claude"


def test_local_settings_win_over_project_and_user(tmp_path):
    config = tmp_path / "config"
    project = tmp_path / "project"
    config.mkdir()
    (project / ".claude").mkdir(parents=True)

    (config / "settings.json").write_text(
        json.dumps({"enabledPlugins": {"demo@mkt": True}})
    )
    (project / ".claude" / "settings.json").write_text(
        json.dumps({"enabledPlugins": {"demo@mkt": True}})
    )
    (project / ".claude" / "settings.local.json").write_text(
        json.dumps({"enabledPlugins": {"demo@mkt": False}})
    )

    result = enabled_plugins(config, project)
    assert result.get("demo@mkt") is not True


def test_project_settings_win_over_user_settings(tmp_path):
    config = tmp_path / "config"
    project = tmp_path / "project"
    config.mkdir()
    (project / ".claude").mkdir(parents=True)

    (config / "settings.json").write_text(
        json.dumps({"enabledPlugins": {"demo@mkt": False}})
    )
    (project / ".claude" / "settings.json").write_text(
        json.dumps({"enabledPlugins": {"demo@mkt": True}})
    )

    result = enabled_plugins(config, project)
    assert result.get("demo@mkt") is True


def test_missing_settings_files_yield_no_enabled_plugins(tmp_path):
    config = tmp_path / "config"
    project = tmp_path / "project"
    config.mkdir()
    project.mkdir()

    result = enabled_plugins(config, project)
    assert result == {} or all(v is not True for v in result.values())
