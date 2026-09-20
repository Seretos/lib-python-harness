"""R1 (apply half), R2, R8 (RunSpec arm) — what `resolve(definition, ctx,
config=...)` produces once a real `.seretos/harness.yml` is in play.
"""
from __future__ import annotations

import pytest

from lib_python_harness import Isolation, resolve
from lib_python_harness.config import load_harness_config
from lib_python_harness.errors import ConfigError

from ._config_support import definition, fake_home, host, make_repo, write_harness_yml

AGENT = '"p:reviewer"'


def _cfg(tmp_path, yml, monkeypatch=None, home_yml=None):
    if monkeypatch is not None:
        fake_home(tmp_path, monkeypatch, home_yml)
    repo = make_repo(tmp_path, yml)
    return repo, load_harness_config(repo, home_default=monkeypatch is not None)


# -- R1: layered precedence -------------------------------------------------


def test_home_defaults_and_project_agent_entry_layer_up(tmp_path, monkeypatch):
    repo, cfg = _cfg(
        tmp_path,
        f"agents:\n  {AGENT}:\n    model: fable\n",
        monkeypatch,
        home_yml="defaults:\n  isolation: clean\n",
    )
    ctx = host(repo)

    reviewer = resolve(definition("reviewer", model="opus"), ctx, config=cfg)
    other = resolve(definition("other", model="sonnet"), ctx, config=cfg)

    assert reviewer.model == "fable"
    assert reviewer.isolation is Isolation.CLEAN
    # An agent no layer names individually still gets the home layer's
    # `defaults`, and keeps its own frontmatter model.
    assert other.isolation is Isolation.CLEAN
    assert other.model == "sonnet"


def test_clean_isolation_drops_the_parent_cwd(tmp_path):
    # `Isolation.CLEAN` rejects any cwd inside a git repo, and the parent's
    # cwd always is one -> a config-selected CLEAN run must take CLEAN's own
    # fresh-temp-dir recipe (cwd=None).
    repo, cfg = _cfg(tmp_path, f"agents:\n  {AGENT}:\n    isolation: clean\n")

    spec = resolve(definition(model="opus"), host(repo), config=cfg)

    assert spec.isolation is Isolation.CLEAN
    assert spec.cwd is None


def test_agent_entry_beats_defaults_and_defaults_beat_frontmatter(tmp_path):
    repo, cfg = _cfg(
        tmp_path,
        "defaults:\n  model: haiku\n"
        f"agents:\n  {AGENT}:\n    model: fable\n",
    )
    ctx = host(repo)

    named = resolve(definition("reviewer", model="opus"), ctx, config=cfg)
    unnamed = resolve(definition("other", model="opus"), ctx, config=cfg)

    assert named.model == "fable"
    assert unnamed.model == "haiku"


def test_agent_untouched_by_any_layer_is_exactly_what_resolve_built(tmp_path):
    repo, cfg = _cfg(tmp_path, f"agents:\n  {AGENT}:\n    model: fable\n")
    ctx = host(repo, model="opus", permission_mode="acceptEdits")
    other = definition("other", model="sonnet")

    assert resolve(other, ctx, config=cfg) == resolve(other, ctx)


def test_config_stated_values_override_the_plugin_scope_drop(tmp_path):
    # resolve() ignores a *plugin's own* permissionMode/omitClaudeMd; a
    # value the project wrote down is policy, not plugin frontmatter.
    repo, cfg = _cfg(
        tmp_path,
        f"agents:\n  {AGENT}:\n    permissionMode: acceptEdits\n",
    )

    spec = resolve(
        definition(scope="plugin", permission_mode="plan"),
        host(repo, permission_mode="default"),
        config=cfg,
    )

    assert spec.permission_mode == "acceptEdits"


# -- R2: tools add/remove on the definition's own list ----------------------


def test_tools_patch_removes_then_adds_on_the_definitions_list(tmp_path):
    repo, cfg = _cfg(
        tmp_path,
        f"agents:\n  {AGENT}:\n    tools:\n      remove: [Bash]\n      add: [WebFetch]\n",
    )

    spec = resolve(definition(tools="Bash, Read"), host(repo), config=cfg)

    assert spec.tools == "Read, WebFetch"


def test_tools_remove_on_a_definition_without_tools_stays_none(tmp_path):
    repo, cfg = _cfg(
        tmp_path,
        f"agents:\n  {AGENT}:\n    tools:\n      remove: [Bash]\n",
    )

    spec = resolve(definition(), host(repo, model="opus"), config=cfg)

    assert spec.tools is None


def test_tools_removing_an_absent_tool_is_a_no_op(tmp_path):
    repo, cfg = _cfg(
        tmp_path,
        f"agents:\n  {AGENT}:\n    tools:\n      remove: [WebFetch]\n",
    )

    spec = resolve(definition(tools="Bash, Read"), host(repo), config=cfg)

    assert spec.tools == "Bash, Read"


def test_tools_adding_a_present_tool_does_not_duplicate(tmp_path):
    repo, cfg = _cfg(
        tmp_path,
        f"agents:\n  {AGENT}:\n    tools:\n      add: [Read, Grep]\n",
    )

    spec = resolve(definition(tools="Bash, Read"), host(repo), config=cfg)

    assert spec.tools == "Bash, Read, Grep"


def test_disallowed_tools_patch_uses_the_same_rules(tmp_path):
    repo, cfg = _cfg(
        tmp_path,
        f"agents:\n  {AGENT}:\n    disallowedTools:\n      remove: [Bash]\n      add: [WebFetch]\n",
    )

    spec = resolve(definition(disallowed_tools="Bash, Edit"), host(repo), config=cfg)

    assert spec.disallowed_tools == "Edit, WebFetch"


# -- R8 (RunSpec arm): named isolation profiles ------------------------------

PROFILE = """\
profiles:
  clean-with-git:
    settingSources: []
    strictMcp: true
    tools: [Bash, Read, Grep]
    omitClaudeMd: true
    memory: false
"""


def test_named_profile_maps_to_inherit_plus_the_profiles_fields(tmp_path):
    repo, cfg = _cfg(
        tmp_path, PROFILE + f"agents:\n  {AGENT}:\n    isolation: clean-with-git\n"
    )

    spec = resolve(definition(model="opus"), host(repo), config=cfg)

    assert spec.isolation is Isolation.INHERIT
    assert spec.setting_sources == []
    assert spec.strict_mcp is True
    assert spec.memory is False
    assert spec.omit_claude_md is True
    assert {t.strip() for t in spec.tools.split(",")} == {"Bash", "Read", "Grep"}


def test_profile_from_home_layer_is_usable_from_the_project_layer(
    tmp_path, monkeypatch
):
    repo, cfg = _cfg(
        tmp_path,
        f"agents:\n  {AGENT}:\n    isolation: clean-with-git\n",
        monkeypatch,
        home_yml=PROFILE,
    )

    spec = resolve(definition(model="opus"), host(repo), config=cfg)

    assert spec.isolation is Isolation.INHERIT
    assert spec.memory is False


def test_undefined_profile_is_a_config_error_naming_it(tmp_path):
    repo, cfg = _cfg(tmp_path, f"agents:\n  {AGENT}:\n    isolation: nope\n")

    with pytest.raises(ConfigError) as excinfo:
        resolve(definition(model="opus"), host(repo), config=cfg)

    assert "nope" in str(excinfo.value)


def test_memory_true_or_unset_profile_leaves_memory_untouched(tmp_path):
    repo, cfg = _cfg(
        tmp_path,
        "profiles:\n  keeps-memory:\n    memory: true\n"
        f"agents:\n  {AGENT}:\n    isolation: keeps-memory\n",
    )

    spec = resolve(definition(model="opus"), host(repo), config=cfg)

    assert spec.memory is not False
