"""Ticket #3 — `.seretos/harness.yml` overrides on the command line
(R3 mcpServers add/remove, R4 canSpawn, R6 no-config no-op, R8 named profile).

Every argv assertion is against an independently written literal or a
parsed flag value, never a constant the builder itself consumes.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib_python_harness import resolve
from lib_python_harness.config import load_harness_config
from lib_python_harness.errors import ConfigError

from ._config_support import (
    build_plan,
    definition,
    flag_values,
    host,
    make_repo,
)

_FAKE = {"command": "fake-mcp", "args": ["--x"]}
_OLD = {"command": "old-mcp"}
_KEEP = {"command": "keep-mcp"}
_DISPATCH = {"command": "dispatch-mcp"}

# Project-scope definition: `resolve()` lets it fall back to the host
# context's `mcp_servers` (a plugin-scope one gets `mcp_servers=None`).
_PROJECT = dict(name="reviewer", plugin=None, scope="project")


def _before_session_id(argv):
    return argv[: argv.index("--session-id")]


def _mcp_config(argv):
    values = flag_values(argv, "--mcp-config")
    assert len(values) <= 1
    return json.loads(values[0])["mcpServers"] if values else None


def _resolved_plan(tmp_path, yml, ctx_kwargs=None, **definition_kwargs):
    repo = make_repo(tmp_path, yml)
    cfg = load_harness_config(repo, home_default=False)
    spec = resolve(definition(**definition_kwargs), host(repo, **(ctx_kwargs or {})), config=cfg)
    return repo, build_plan(spec, tmp_path)


# -- R6: no config is a byte-identical no-op ---------------------------------


def test_no_config_default_form_argv_is_slice_2_literal(tmp_path):
    repo = make_repo(tmp_path)
    ctx = host(repo, permission_mode="acceptEdits")
    defn = definition(model="sonnet")

    assert resolve(defn, ctx, config=None) == resolve(defn, ctx)
    argv = build_plan(resolve(defn, ctx, config=None), tmp_path).argv

    assert _before_session_id(argv) == [
        "-p", "--model", "sonnet",
        "--permission-mode", "acceptEdits",
        "--setting-sources", "user,project,local",
        "--output-format", "stream-json", "--verbose",
    ]
    assert "--strict-mcp-config" not in argv
    assert "--tools" not in argv


def test_no_config_omit_claude_md_form_argv_is_slice_2_literal(tmp_path):
    repo = make_repo(tmp_path)
    ctx = host(repo)
    defn = definition(
        "solo", plugin=None, scope="project", model="haiku", omit_claude_md=True
    )

    assert resolve(defn, ctx, config=None) == resolve(defn, ctx)
    argv = build_plan(resolve(defn, ctx, config=None), tmp_path).argv

    assert _before_session_id(argv) == [
        "-p", "--model", "haiku",
        "--setting-sources", "user,local",
        "--output-format", "stream-json", "--verbose",
    ]
    assert "--strict-mcp-config" not in argv


def test_clean_argv_stays_slice_1_literal_retrospective(tmp_path):
    # Retrospective regression guard (CLEAN behaviour predates ticket #3):
    # the None-gated CLEAN emissions this ticket adds must not change it.
    from lib_python_harness.providers.base import Isolation, RunSpec

    cwd = tmp_path / "cwd"
    cwd.mkdir()
    spec = RunSpec(prompt="hi", isolation=Isolation.CLEAN, model="haiku", cwd=cwd)
    argv = build_plan(spec, tmp_path).argv

    assert _before_session_id(argv) == [
        "-p", "--model", "haiku",
        "--setting-sources", "",
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--tools", "",
        "--output-format", "stream-json", "--verbose",
        "--system-prompt", "",
    ]


# -- R3: mcpServers add / remove ----------------------------------------------


def test_mcp_add_puts_a_catalogue_server_on_the_command_line(tmp_path):
    _, plan = _resolved_plan(
        tmp_path,
        "agents:\n  reviewer:\n    mcpServers:\n      add: [fake]\n",
        ctx_kwargs=dict(mcp_servers={"keep": _KEEP}, available_mcp_servers={"fake": _FAKE}),
        **_PROJECT,
    )

    assert _mcp_config(plan.argv) == {"keep": _KEEP, "fake": _FAKE}


def test_mcp_remove_drops_a_server_the_parent_context_had(tmp_path):
    _, plan = _resolved_plan(
        tmp_path,
        "agents:\n  reviewer:\n    mcpServers:\n      remove: [old]\n",
        ctx_kwargs=dict(mcp_servers={"old": _OLD, "keep": _KEEP}),
        **_PROJECT,
    )

    assert _mcp_config(plan.argv) == {"keep": _KEEP}


def test_mcp_removing_the_last_server_emits_no_mcp_config(tmp_path):
    _, plan = _resolved_plan(
        tmp_path,
        "agents:\n  reviewer:\n    mcpServers:\n      remove: [old]\n",
        ctx_kwargs=dict(mcp_servers={"old": _OLD}),
        **_PROJECT,
    )

    assert "--mcp-config" not in plan.argv


def test_mcp_add_of_a_name_missing_from_the_catalogue_is_a_config_error(tmp_path):
    repo = make_repo(
        tmp_path, "agents:\n  reviewer:\n    mcpServers:\n      add: [ghost]\n"
    )
    cfg = load_harness_config(repo, home_default=False)
    ctx = host(repo, available_mcp_servers={"fake": _FAKE})

    with pytest.raises(ConfigError) as excinfo:
        resolve(definition(**_PROJECT), ctx, config=cfg)

    assert "ghost" in str(excinfo.value)


def test_mcp_patches_take_effect_under_isolation_clean_too(tmp_path):
    _, plan = _resolved_plan(
        tmp_path,
        "agents:\n  reviewer:\n    isolation: clean\n"
        "    mcpServers:\n      add: [fake]\n",
        ctx_kwargs=dict(available_mcp_servers={"fake": _FAKE}),
        **_PROJECT,
    )

    assert _mcp_config(plan.argv) == {"fake": _FAKE}
    assert "--strict-mcp-config" in plan.argv  # CLEAN always carries it


def test_clean_run_carries_permission_mode_and_tools_from_the_config(tmp_path):
    # The ticket's headline entry combines `isolation: clean` with
    # permissionMode/tools; CLEAN must not silently discard them.
    _, plan = _resolved_plan(
        tmp_path,
        "agents:\n  reviewer:\n    isolation: clean\n"
        "    permissionMode: bypassPermissions\n"
        "    tools:\n      add: [Bash]\n",
        **_PROJECT,
    )
    argv = plan.argv

    assert flag_values(argv, "--permission-mode") == ["bypassPermissions"]
    assert flag_values(argv, "--tools") == ["Bash"]
    assert flag_values(argv, "--setting-sources") == [""]


# -- R4: canSpawn on the command line -----------------------------------------

_SPAWN_CTX = dict(
    mcp_servers={"keep": _KEEP},
    available_mcp_servers={"harness-dispatch": _DISPATCH, "keep": _KEEP},
    dispatch_mcp_server_name="harness-dispatch",
)


def _spawn_argv(tmp_path, extra_agent_lines):
    _, plan = _resolved_plan(
        tmp_path,
        f"agents:\n  reviewer:\n    model: fable\n{extra_agent_lines}",
        ctx_kwargs=_SPAWN_CTX,
        **_PROJECT,
    )
    return plan.argv


def test_can_spawn_default_and_false_omit_the_dispatch_server_true_includes_it(tmp_path):
    default_argv = _spawn_argv(tmp_path / "a", "")
    false_argv = _spawn_argv(tmp_path / "b", "    canSpawn: false\n")
    true_argv = _spawn_argv(tmp_path / "c", "    canSpawn: true\n")

    assert "harness-dispatch" not in _mcp_config(default_argv)
    assert "harness-dispatch" not in _mcp_config(false_argv)
    assert _mcp_config(true_argv)["harness-dispatch"] == _DISPATCH
    # default is `false`, not "unspecified": the same MCP set
    assert _mcp_config(default_argv) == _mcp_config(false_argv)
    # The child's MCP set is computed, so the flag that makes "absent from
    # --mcp-config" mean "unreachable" is on whenever a config applied.
    for argv in (default_argv, false_argv, true_argv):
        assert "--strict-mcp-config" in argv


def test_can_spawn_true_without_a_dispatch_server_name_is_a_config_error(tmp_path):
    repo = make_repo(tmp_path, "agents:\n  reviewer:\n    canSpawn: true\n")
    cfg = load_harness_config(repo, home_default=False)
    ctx = host(repo, available_mcp_servers={"harness-dispatch": _DISPATCH})

    with pytest.raises(ConfigError):
        resolve(definition(**_PROJECT), ctx, config=cfg)


def test_can_spawn_true_with_a_name_absent_from_the_catalogue_is_a_config_error(tmp_path):
    repo = make_repo(tmp_path, "agents:\n  reviewer:\n    canSpawn: true\n")
    cfg = load_harness_config(repo, home_default=False)
    ctx = host(
        repo,
        available_mcp_servers={"other": _KEEP},
        dispatch_mcp_server_name="harness-dispatch",
    )

    with pytest.raises(ConfigError) as excinfo:
        resolve(definition(**_PROJECT), ctx, config=cfg)

    assert "harness-dispatch" in str(excinfo.value)


def test_profile_with_strict_mcp_false_omits_the_flag(tmp_path):
    _, plan = _resolved_plan(
        tmp_path,
        "profiles:\n  loose:\n    strictMcp: false\n"
        "agents:\n  reviewer:\n    isolation: loose\n",
        **_PROJECT,
    )

    assert "--strict-mcp-config" not in plan.argv


# -- R8: the named-profile command line ----------------------------------------


def test_clean_with_git_profile_command_line(tmp_path):
    repo, plan = _resolved_plan(
        tmp_path,
        "profiles:\n"
        "  clean-with-git:\n"
        "    settingSources: []\n"
        "    strictMcp: true\n"
        "    tools: [Bash, Read, Grep]\n"
        "    omitClaudeMd: true\n"
        "    memory: false\n"
        "agents:\n  reviewer:\n    isolation: clean-with-git\n",
        **_PROJECT,
    )
    argv = plan.argv

    # flag present with an EMPTY operand (not absent, not the default)
    assert flag_values(argv, "--setting-sources") == [""]
    assert "--strict-mcp-config" in argv
    assert flag_values(argv, "--tools") == ["Bash,Read,Grep"]

    # memory: false -> a fresh cwd this run has never had memory in, with the
    # project still reachable through --add-dir.
    cwd = Path(plan.cwd)
    assert cwd != repo
    assert cwd.is_dir() and list(cwd.iterdir()) == []
    assert str(repo) in flag_values(argv, "--add-dir")


def test_profile_without_memory_false_keeps_the_parent_cwd(tmp_path):
    repo, plan = _resolved_plan(
        tmp_path,
        "profiles:\n  plain:\n    settingSources: []\n"
        "agents:\n  reviewer:\n    isolation: plain\n",
        **_PROJECT,
    )

    assert Path(plan.cwd) == repo
    assert str(repo) not in flag_values(plan.argv, "--add-dir")


def test_profile_with_memory_true_keeps_the_parent_cwd_and_adds_no_add_dir(tmp_path):
    repo, plan = _resolved_plan(
        tmp_path,
        "profiles:\n  keeps-memory:\n    memory: true\n"
        "agents:\n  reviewer:\n    isolation: keeps-memory\n",
        **_PROJECT,
    )

    assert Path(plan.cwd) == repo
    assert str(repo) not in flag_values(plan.argv, "--add-dir")
