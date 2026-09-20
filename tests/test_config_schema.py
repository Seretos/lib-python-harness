"""R5/R7/R8 (schema arm) — the `.seretos/harness.yml` schema is strict and
its errors are attributable: file path, qualified agent name, offending key.
"""
from __future__ import annotations

import pytest

from lib_python_harness.config import load_harness_config
from lib_python_harness.errors import ConfigError, HarnessError

from ._config_support import fake_home, make_repo, write_harness_yml

TICKET_PROFILES_BLOCK = """\
profiles:
  clean-with-git:               # named isolation profiles between inherit and clean
    settingSources: []
    strictMcp: true
    tools: [Bash, Read, Grep]
    omitClaudeMd: true
    memory: false
"""


def _load(repo):
    return load_harness_config(repo, home_default=False)


# -- R5: unknown key -------------------------------------------------------


def test_unknown_agent_key_names_file_agent_and_key(tmp_path):
    repo = make_repo(tmp_path)
    path = write_harness_yml(repo, 'agents:\n  "p:reviewer":\n    modle: fable\n')

    with pytest.raises(ConfigError) as excinfo:
        _load(repo)

    message = str(excinfo.value)
    assert str(path) in message
    assert "p:reviewer" in message
    assert "modle" in message


def test_config_error_is_a_harness_error():
    assert issubclass(ConfigError, HarnessError)


def test_unknown_top_level_key_names_file_and_key(tmp_path):
    repo = make_repo(tmp_path)
    path = write_harness_yml(repo, "frobnicate: 1\n")

    with pytest.raises(ConfigError) as excinfo:
        _load(repo)

    assert str(path) in str(excinfo.value)
    assert "frobnicate" in str(excinfo.value)


def test_unknown_key_inside_a_profile_names_profile_and_key(tmp_path):
    repo = make_repo(tmp_path)
    path = write_harness_yml(
        repo, "profiles:\n  strict-one:\n    strictMpc: true\n"
    )

    with pytest.raises(ConfigError) as excinfo:
        _load(repo)

    message = str(excinfo.value)
    assert str(path) in message
    assert "strict-one" in message
    assert "strictMpc" in message


def test_defaults_can_spawn_is_rejected(tmp_path):
    # Human decision (Q1 (b)): canSpawn is opt-in per agent, never a default.
    repo = make_repo(tmp_path)
    path = write_harness_yml(repo, "defaults:\n  canSpawn: true\n")

    with pytest.raises(ConfigError) as excinfo:
        _load(repo)

    assert str(path) in str(excinfo.value)
    assert "canSpawn" in str(excinfo.value)


def test_malformed_yaml_raises_config_error_naming_file(tmp_path):
    repo = make_repo(tmp_path)
    path = write_harness_yml(repo, "agents: [unterminated\n")

    with pytest.raises(ConfigError) as excinfo:
        _load(repo)

    assert str(path) in str(excinfo.value)


def test_malformed_home_layer_is_the_file_named_not_the_valid_project_layer(
    tmp_path, monkeypatch
):
    home = fake_home(tmp_path, monkeypatch)
    home_path = write_harness_yml(home, 'agents:\n  "p:reviewer":\n    modle: fable\n')
    repo = make_repo(tmp_path, 'agents:\n  "p:reviewer":\n    model: opus\n')
    project_path = repo / ".seretos" / "harness.yml"

    with pytest.raises(ConfigError) as excinfo:
        load_harness_config(repo)

    assert str(home_path) in str(excinfo.value)
    assert str(project_path) not in str(excinfo.value)


def test_malformed_project_layer_is_the_file_named_not_the_valid_home_layer(
    tmp_path, monkeypatch
):
    home = fake_home(tmp_path, monkeypatch, "defaults:\n  isolation: clean\n")
    home_path = home / ".seretos" / "harness.yml"
    repo = make_repo(tmp_path)
    project_path = write_harness_yml(repo, 'agents:\n  "p:reviewer":\n    modle: fable\n')

    with pytest.raises(ConfigError) as excinfo:
        load_harness_config(repo)

    assert str(project_path) in str(excinfo.value)
    assert str(home_path) not in str(excinfo.value)


# -- R7: provider ----------------------------------------------------------


def test_unsupported_provider_fails_loudly_naming_file_agent_and_value(tmp_path):
    repo = make_repo(tmp_path)
    path = write_harness_yml(repo, 'agents:\n  "p:reviewer":\n    provider: codex\n')

    with pytest.raises(ConfigError) as excinfo:
        _load(repo)

    message = str(excinfo.value)
    assert str(path) in message
    assert "p:reviewer" in message
    assert "codex" in message


def test_provider_claude_validates(tmp_path):
    repo = make_repo(tmp_path, 'agents:\n  "p:reviewer":\n    provider: claude\n')
    assert _load(repo) is not None


# -- R8 (schema arm): the ticket's profiles example validates verbatim -----


def test_ticket_profiles_example_validates_verbatim_including_memory(tmp_path):
    repo = make_repo(tmp_path, TICKET_PROFILES_BLOCK)

    cfg = _load(repo)

    assert cfg is not None
    assert "clean-with-git" in cfg.profiles
