"""R1 — discovery returns exactly the enabled set, project > user > plugin.

Tests `lib_python_harness.agents.discovery.discover(host_context)`.

Module-placement / shape assumptions (documented, since the plan's R1 text
describes behaviour, not a return-type contract):
- `discover(host_context)` returns a `dict[str, AgentDefinition]` keyed by
  `qualified_name` — the plan's "first writer of a qualified_name wins"
  phrasing (Approach, agents/discovery.py bullet) only makes sense against a
  mapping keyed by that name, so a later duplicate is skipped, not
  overwritten.
- `host_context` is accepted duck-typed here (a bare `SimpleNamespace` with a
  `.cwd` attribute) rather than a real `HostContext` instance, because
  `HostContext`/`host/context.py` is R4's own subject and must stay absent
  for R4's driving test to get its mandated
  `ImportError: lib_python_harness.host.context` RED reason — importing it
  here would make that module exist.
- User-scope custom agents live at `<config_dir>/agents/*.md` (parallel to
  Claude Code's own layout, `<config_dir>` defaulting to `~/.claude`);
  project-scope at `<project_dir>/.claude/agents/*.md`; plugin-scope at
  `<installPath>/agents/*.md`.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

from lib_python_harness.agents.discovery import discover


def _host_context(project_dir):
    return SimpleNamespace(cwd=project_dir)


def _write_agent(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _setup_base_layout(tmp_path):
    """project 'a', user 'b', enabled plugin 'demo-plugin@demo-marketplace'
    contributing plugin-scope 'c' (no `name:` — discovered as `demo-plugin:c`).
    """
    project_dir = tmp_path / "project"
    config_dir = tmp_path / "home" / ".claude"
    plugin_dir = tmp_path / "plugin"

    _write_agent(
        project_dir / ".claude" / "agents" / "a.md",
        "---\nname: a\ndescription: Project agent A\n---\nBody A.\n",
    )
    _write_agent(
        config_dir / "agents" / "b.md",
        "---\nname: b\ndescription: User agent B\n---\nBody B.\n",
    )
    _write_agent(
        plugin_dir / "agents" / "c.md",
        "---\ndescription: Plugin agent C, no name\n---\nBody C.\n",
    )

    (config_dir / "plugins").mkdir(parents=True, exist_ok=True)
    (config_dir / "plugins" / "installed_plugins.json").write_text(
        json.dumps(
            {
                "version": 2,
                "plugins": {
                    "demo-plugin@demo-marketplace": [
                        {
                            "scope": "user",
                            "installPath": str(plugin_dir),
                            "projectPath": None,
                        }
                    ]
                },
            }
        )
    )
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "settings.json").write_text(
        json.dumps({"enabledPlugins": {"demo-plugin@demo-marketplace": True}})
    )

    return project_dir, config_dir, plugin_dir


def test_discover_returns_exactly_the_enabled_set_project_user_plugin(
    tmp_path, monkeypatch
):
    project_dir, config_dir, _plugin_dir = _setup_base_layout(tmp_path)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config_dir))

    result = discover(_host_context(project_dir))

    assert set(result.keys()) == {"a", "b", "demo-plugin:c"}
    assert result["a"].source_scope == "project"
    assert result["b"].source_scope == "user"
    assert result["demo-plugin:c"].source_scope == "plugin"
    # no name: in c.md -> discovered under its filename stem, qualified by
    # plugin name.
    assert result["demo-plugin:c"].name == "c"


def test_local_settings_false_drops_the_plugin_agent(tmp_path, monkeypatch):
    project_dir, config_dir, _plugin_dir = _setup_base_layout(tmp_path)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config_dir))

    (project_dir / ".claude").mkdir(parents=True, exist_ok=True)
    (project_dir / ".claude" / "settings.local.json").write_text(
        json.dumps({"enabledPlugins": {"demo-plugin@demo-marketplace": False}})
    )

    result = discover(_host_context(project_dir))

    assert set(result.keys()) == {"a", "b"}


def test_same_named_project_and_user_agent_yields_the_project_one(
    tmp_path, monkeypatch
):
    project_dir, config_dir, _plugin_dir = _setup_base_layout(tmp_path)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config_dir))

    _write_agent(
        project_dir / ".claude" / "agents" / "dup.md",
        "---\nname: dup\ndescription: Project dup\n---\nProject body.\n",
    )
    _write_agent(
        config_dir / "agents" / "dup.md",
        "---\nname: dup\ndescription: User dup\n---\nUser body.\n",
    )

    result = discover(_host_context(project_dir))

    assert result["dup"].source_scope == "project"
    assert result["dup"].description == "Project dup"


def test_no_agents_dir_is_not_an_error(tmp_path, monkeypatch):
    config_dir = tmp_path / "home" / ".claude"
    config_dir.mkdir(parents=True)
    (config_dir / "settings.json").write_text(json.dumps({}))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config_dir))

    project_dir = tmp_path / "project"
    project_dir.mkdir()

    result = discover(_host_context(project_dir))
    assert result == {}


def test_enabled_key_absent_from_installed_plugins_is_skipped_not_raised(
    tmp_path, monkeypatch
):
    config_dir = tmp_path / "home" / ".claude"
    config_dir.mkdir(parents=True)
    (config_dir / "plugins").mkdir()
    (config_dir / "plugins" / "installed_plugins.json").write_text(
        json.dumps({"version": 2, "plugins": {}})
    )
    (config_dir / "settings.json").write_text(
        json.dumps({"enabledPlugins": {"ghost-plugin@nowhere": True}})
    )
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config_dir))

    project_dir = tmp_path / "project"
    project_dir.mkdir()

    result = discover(_host_context(project_dir))
    assert result == {}


def test_key_with_user_and_matching_project_entry_resolves_to_project(
    tmp_path, monkeypatch
):
    project_dir = tmp_path / "project"
    config_dir = tmp_path / "home" / ".claude"
    user_plugin_dir = tmp_path / "user-plugin"
    project_plugin_dir = tmp_path / "project-plugin"

    _write_agent(
        user_plugin_dir / "agents" / "p.md",
        "---\nname: p\ndescription: User install\n---\nBody.\n",
    )
    _write_agent(
        project_plugin_dir / "agents" / "p.md",
        "---\nname: p\ndescription: Project install\n---\nBody.\n",
    )

    config_dir.mkdir(parents=True)
    (config_dir / "plugins").mkdir()
    (config_dir / "plugins" / "installed_plugins.json").write_text(
        json.dumps(
            {
                "version": 2,
                "plugins": {
                    "shared-plugin@demo-marketplace": [
                        {
                            "scope": "user",
                            "installPath": str(user_plugin_dir),
                            "projectPath": None,
                        },
                        {
                            "scope": "project",
                            "installPath": str(project_plugin_dir),
                            "projectPath": str(project_dir),
                        },
                    ]
                },
            }
        )
    )
    (config_dir / "settings.json").write_text(
        json.dumps({"enabledPlugins": {"shared-plugin@demo-marketplace": True}})
    )
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config_dir))
    project_dir.mkdir(exist_ok=True)

    result = discover(_host_context(project_dir))

    assert result["shared-plugin:p"].description == "Project install"
