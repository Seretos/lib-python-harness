"""R1 (argv/env recipe) + R3 (pre-spawn rejection) for `MistralCliProvider`.

Expected values are written independently of any provider constant: asserting
against the constant the builder consumed could never catch a silent drop.
The recipe is the one measured against the installed CLI (`vibe` 2.25.4):
`-p --output streaming --enabled-tools <no-match>`, prompt on stdin, model via
`VIBE_ACTIVE_MODEL` (vibe has no `--model` flag), a fresh empty `VIBE_HOME`.
"""
from __future__ import annotations

import json
import shutil
import sys
import uuid
from pathlib import Path

import pytest

from lib_python_harness.errors import HarnessError, UnsafeCwdError, UnsupportedByProvider
from lib_python_harness.harness import Harness
from lib_python_harness.providers.base import Isolation, RunSpec
from lib_python_harness.providers.mistral_cli import MistralCliProvider

FAKE_MISTRAL = Path(__file__).parent / "fixtures" / "fake_mistral.py"

# Real built-in tool names must never be what --enabled-tools names, or the
# "off switch" would leave a tool enabled.
REAL_TOOL_NAMES = {"bash", "read_file", "write_file", "grep", "search_replace",
                   "task", "todo", "ask_user_question", "webfetch", "websearch"}

_MADE_HOMES: list[str] = []


@pytest.fixture(autouse=True)
def _reap_vibe_homes():
    """Direct build_launch_plan callers own the plan's cleanup_paths (Harness
    does it in real runs)."""
    yield
    for home in _MADE_HOMES:
        shutil.rmtree(home, ignore_errors=True)
    _MADE_HOMES.clear()


def _plan(tmp_path, **overrides):
    kwargs = dict(
        prompt="Reply with exactly OK",
        isolation=Isolation.CLEAN,
        model="mistral-medium-3.5",
        provider="mistral",
        cwd=tmp_path / "cwd",
    )
    kwargs.update(overrides)
    if kwargs["cwd"] is not None:
        Path(kwargs["cwd"]).mkdir(exist_ok=True)
    plan = MistralCliProvider().build_launch_plan(
        RunSpec(**kwargs), session_id=str(uuid.uuid4()), run_dir=tmp_path / "run"
    )
    _MADE_HOMES.extend(plan.cleanup_paths)
    return plan


def _value_after(argv, flag):
    return argv[argv.index(flag) + 1]


# -- R1: argv ----------------------------------------------------------------


def test_argv_is_headless_streaming_with_tools_switched_off(tmp_path):
    argv = _plan(tmp_path).argv
    assert "-p" in argv
    assert _value_after(argv, "--output") == "streaming"
    tools = _value_after(argv, "--enabled-tools")
    assert tools and not tools.startswith("-")
    assert tools.lower() not in REAL_TOOL_NAMES
    assert "*" not in tools and not tools.startswith("re:"), "pattern would match real tools"


def test_argv_has_no_binary_no_trust_no_yolo_no_foreign_flags(tmp_path):
    argv = _plan(tmp_path).argv
    assert "vibe" not in argv  # binary is prepended by the harness
    for token in ("--trust", "--auto-approve", "--yolo", "--agent", "--model", "-m",
                  "exec", "--json", "--output-format", "--setting-sources",
                  "--strict-mcp-config", "--system-prompt", "--session-id", "--tools"):
        assert token not in argv, f"{token} must not be in {argv}"


def test_prompt_travels_on_stdin_not_argv(tmp_path):
    prompt = f"nonce-{uuid.uuid4().hex}"
    plan = _plan(tmp_path, prompt=prompt)
    assert plan.stdin == prompt
    assert all(prompt not in token for token in plan.argv)


def test_max_turns_appears_only_when_set(tmp_path):
    assert "--max-turns" not in _plan(tmp_path).argv
    argv = _plan(tmp_path, max_turns=3).argv
    assert _value_after(argv, "--max-turns") == "3"


# -- R1: env -----------------------------------------------------------------


def test_env_uses_fresh_home_model_alias_and_connectors_off(tmp_path, monkeypatch):
    real = tmp_path / "real-vibe-home"
    real.mkdir()
    (real / "AGENTS.md").write_text("PWNED")
    monkeypatch.setenv("VIBE_HOME", str(real))
    other_model = f"model-{uuid.uuid4().hex[:6]}"
    plan = _plan(tmp_path, model=other_model)
    env = plan.env

    home = Path(env["VIBE_HOME"])
    assert home != real
    assert home.is_dir() and list(home.iterdir()) == []
    assert str(home) in plan.cleanup_paths
    assert not str(home).startswith(str(tmp_path / "artifacts"))
    assert env["VIBE_ACTIVE_MODEL"] == other_model  # from spec.model, not a constant
    assert env["VIBE_ENABLE_CONNECTORS"] == "false"


def test_each_run_gets_its_own_home(tmp_path):
    assert _plan(tmp_path).env["VIBE_HOME"] != _plan(tmp_path).env["VIBE_HOME"]


def test_parent_vibe_variables_never_reach_the_child(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBE_HOME", str(tmp_path / "real"))
    monkeypatch.setenv("VIBE_ACTIVE_MODEL", "callers-model")
    monkeypatch.setenv("VIBE_ENABLE_CONNECTORS", "true")
    monkeypatch.setenv("VIBE_SYSTEM_PROMPT_ID", "callers-prompt")
    monkeypatch.setenv("VIBE_FOO_BAR", "x")
    env = _plan(tmp_path, model="spec-model").env
    assert {k for k in env if k.startswith("VIBE_")} == {
        "VIBE_HOME", "VIBE_ACTIVE_MODEL", "VIBE_ENABLE_CONNECTORS"}
    assert env["VIBE_ACTIVE_MODEL"] == "spec-model"
    assert env["VIBE_ENABLE_CONNECTORS"] == "false"
    assert env["VIBE_HOME"] != str(tmp_path / "real")


def test_mistral_api_key_survives_as_the_credential_channel(tmp_path, monkeypatch):
    key = f"key-{uuid.uuid4().hex}"
    monkeypatch.setenv("MISTRAL_API_KEY", key)
    assert _plan(tmp_path).env["MISTRAL_API_KEY"] == key


def test_default_cwd_is_a_fresh_empty_directory(tmp_path):
    plan = _plan(tmp_path, cwd=None)
    cwd = Path(plan.cwd)
    assert cwd.is_dir() and not any(cwd.iterdir())


def test_nonempty_caller_cwd_is_refused(tmp_path):
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    (cwd / "AGENTS.md").write_text("planted")
    with pytest.raises(UnsafeCwdError):
        _plan(tmp_path, cwd=cwd)


# -- R3: unsupported fields --------------------------------------------------


@pytest.mark.parametrize(
    "field,value",
    [
        ("permission_mode", "plan"),
        ("tools", "Bash"),
        ("disallowed_tools", "Bash"),
        ("skills", ["s"]),
        ("hooks", {"PreToolUse": []}),
        ("omit_claude_md", True),
        ("agent_name", "reviewer"),
        ("setting_sources", ["user"]),
        ("strict_mcp", True),
        ("session_tools", "Bash"),
        ("memory", False),
        ("system_prompt", "be terse"),
        ("effort", "high"),
        ("json_schema", {"type": "object"}),
    ],
)
def test_each_unhonourable_field_is_rejected(tmp_path, field, value):
    with pytest.raises(UnsupportedByProvider) as excinfo:
        _plan(tmp_path, **{field: value})
    assert field in str(excinfo.value)
    assert isinstance(excinfo.value, HarnessError)


def test_all_offending_fields_are_listed_at_once(tmp_path):
    with pytest.raises(UnsupportedByProvider) as excinfo:
        _plan(tmp_path, effort="high", json_schema={"type": "object"}, tools="Bash")
    message = str(excinfo.value)
    assert "effort" in message and "json_schema" in message and "tools" in message


def test_inherit_isolation_is_rejected(tmp_path):
    with pytest.raises(UnsupportedByProvider) as excinfo:
        _plan(tmp_path, isolation=Isolation.INHERIT)
    assert "isolation" in str(excinfo.value).lower()


def test_description_alone_is_silently_unsupported_not_an_error(tmp_path):
    plan = _plan(tmp_path, description="a reviewer")
    assert all("a reviewer" not in tok for tok in plan.argv)


def test_unsupported_fields_raise_before_spawn(tmp_path):
    """R3 driving test: rejected through Harness.start with nothing created."""
    artifacts = tmp_path / "artifacts"
    (tmp_path / "run-cwd").mkdir()
    harness = Harness(claude_argv=[sys.executable, str(FAKE_MISTRAL)])
    spec = RunSpec(
        prompt="x", isolation=Isolation.CLEAN, model="mistral-medium-3.5",
        provider="mistral", cwd=tmp_path / "run-cwd", artifacts_dir=artifacts,
        effort="high", json_schema={"type": "object"},
    )
    with pytest.raises(UnsupportedByProvider) as excinfo:
        harness.start(spec)
    assert "effort" in str(excinfo.value) and "json_schema" in str(excinfo.value)
    assert harness._processes == {}
    assert harness.store.list() == []
    assert not artifacts.exists() or not any(artifacts.iterdir())


def test_max_turns_is_honoured_through_harness_not_rejected(tmp_path):
    (tmp_path / "run-cwd").mkdir()
    harness = Harness(claude_argv=[sys.executable, str(FAKE_MISTRAL)])
    result = harness.run(RunSpec(
        prompt="x", isolation=Isolation.CLEAN, model="mistral-medium-3.5",
        provider="mistral", cwd=tmp_path / "run-cwd",
        artifacts_dir=tmp_path / "artifacts", max_turns=3,
    ))
    record = harness.store.get(result.run_id)
    flags = json.loads(Path(record["provenance_path"]).read_text())["flags"]
    assert flags[flags.index("--max-turns") + 1] == "3"
