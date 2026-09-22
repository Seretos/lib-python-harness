"""R7 (driving) + R2's static half (helper measurement, explicitly NOT the
isolation finish line — that is `test_codex_isolation_probe.py`).

The flag literal below is written independently of `CODEX_CLEAN_ARGV_FLAGS`
on purpose: asserting argv against the constant the builder consumed could
never catch a silent drop. The tokens are the live-verified set from the
ticket, re-checked against `codex exec --help` (see .adev/4-1/codex-survey.md);
`codex exec` has no approval flag, so none belongs here.
"""
from __future__ import annotations

import json
import shutil
import re
import sys
import uuid
from pathlib import Path

import pytest

from lib_python_harness.errors import HarnessError, UnsafeCwdError, UnsupportedByProvider
from lib_python_harness.harness import Harness
from lib_python_harness.providers.base import Isolation, RunSpec
from lib_python_harness.providers.codex_cli import CodexCliProvider

FAKE_CODEX = Path(__file__).parent / "fixtures" / "fake_codex.py"

EXPECTED_BARE_FLAGS = [
    "exec", "--json", "--ephemeral", "--ignore-user-config", "--ignore-rules",
    "--skip-git-repo-check",
]


@pytest.fixture(autouse=True)
def _reap_scrubbed_homes(monkeypatch):
    """Direct build_launch_plan callers own the plan's cleanup_paths (Harness
    does it in real runs); remove them so tests leave no temp dirs behind."""
    import lib_python_harness.providers.codex_cli as mod

    made = []
    real = mod.make_scrubbed_codex_home

    def tracked():
        home = real()
        made.append(home)
        return home

    monkeypatch.setattr(mod, "make_scrubbed_codex_home", tracked)
    yield
    for home in made:
        shutil.rmtree(home, ignore_errors=True)


def _plan(tmp_path, **overrides):
    kwargs = dict(
        prompt="Reply with exactly OK",
        isolation=Isolation.CLEAN,
        model="gpt-5.6-luna",
        provider="codex",
        cwd=tmp_path / "cwd",
    )
    kwargs.update(overrides)
    if kwargs["cwd"] is not None:
        Path(kwargs["cwd"]).mkdir(exist_ok=True)
    provider = CodexCliProvider()
    return provider.build_launch_plan(
        RunSpec(**kwargs), session_id=str(uuid.uuid4()), run_dir=tmp_path / "run"
    )


def _value_after(argv, flag):
    return argv[argv.index(flag) + 1]


def _overrides(argv):
    return [argv[i + 1] for i, tok in enumerate(argv) if tok == "-c"]


# -- R2 static half (helper measurement) ------------------------------------


def test_argv_contains_canonical_clean_set(tmp_path):
    argv = _plan(tmp_path).argv
    for token in EXPECTED_BARE_FLAGS:
        assert token in argv, f"{token} missing from {argv}"
    assert argv[0] == "exec"
    assert _value_after(argv, "-s") == "read-only"
    assert _value_after(argv, "-m") == "gpt-5.6-luna"
    # the value comes from spec.model, not a constant
    other = f"gpt-other-{uuid.uuid4().hex[:6]}"
    assert _value_after(_plan(tmp_path, model=other).argv, "-m") == other


def test_argv_has_no_claude_flags_and_no_binary(tmp_path):
    argv = _plan(tmp_path).argv
    assert "codex" not in argv  # binary is prepended by the harness
    for token in ("-p", "--output-format", "--setting-sources", "--strict-mcp-config",
                  "--system-prompt", "--session-id", "--tools"):
        assert token not in argv


def test_prompt_travels_on_stdin_not_argv(tmp_path):
    prompt = f"nonce-{uuid.uuid4().hex}"
    plan = _plan(tmp_path, prompt=prompt)
    assert plan.stdin == prompt
    assert all(prompt not in token for token in plan.argv)


def test_effort_maps_to_reasoning_effort_override(tmp_path):
    with_effort = _overrides(_plan(tmp_path, effort="high").argv)
    assert any(re.fullmatch(r'model_reasoning_effort="?high"?', o) for o in with_effort), with_effort
    assert not any("model_reasoning_effort" in o for o in _overrides(_plan(tmp_path).argv))


def test_json_schema_is_written_and_passed_via_output_schema(tmp_path):
    schema = {"type": "object", "properties": {"answer": {"type": "string"}},
              "required": ["answer"], "additionalProperties": False}
    argv = _plan(tmp_path, json_schema=schema).argv
    schema_path = Path(_value_after(argv, "--output-schema"))
    assert schema_path.parent == tmp_path / "run"
    assert json.loads(schema_path.read_text(encoding="utf-8")) == schema
    assert "--output-schema" not in _plan(tmp_path).argv


def test_openai_env_is_scrubbed_and_codex_home_survives(tmp_path, monkeypatch):
    """Contract (ticket #4 decision): OPENAI_* scrubbed; CODEX_HOME is present
    but points at a per-run scrubbed dir holding auth.json only -- never the
    caller's real home (whose AGENTS.md/config the child would otherwise read)."""
    for name in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_ORGANIZATION"):
        monkeypatch.setenv(name, f"nonce-{uuid.uuid4().hex}")
    real = tmp_path / "codex-home"
    real.mkdir()
    (real / "auth.json").write_text('{"tok": "secret"}')
    (real / "AGENTS.md").write_text("PWNED")
    (real / "config.toml").write_text("developer_instructions='x'")
    monkeypatch.setenv("CODEX_HOME", str(real))
    plan = _plan(tmp_path)
    env = plan.env
    for name in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_ORGANIZATION"):
        assert name not in env
    home = Path(env["CODEX_HOME"])
    try:
        assert home != real
        assert sorted(p.name for p in home.iterdir()) == ["auth.json"]
        assert (home / "auth.json").read_text() == '{"tok": "secret"}'
        assert not str(home).startswith(str(tmp_path / "artifacts"))
        assert str(home) in plan.cleanup_paths
    finally:
        shutil.rmtree(home, ignore_errors=True)


def test_scrubbed_codex_home_without_auth_json_is_empty(tmp_path, monkeypatch):
    real = tmp_path / "codex-home"
    real.mkdir()
    (real / "AGENTS.md").write_text("PWNED")
    monkeypatch.setenv("CODEX_HOME", str(real))
    home = Path(_plan(tmp_path).env["CODEX_HOME"])
    try:
        assert home != real and list(home.iterdir()) == []
    finally:
        shutil.rmtree(home, ignore_errors=True)


def test_default_cwd_is_a_fresh_empty_directory(tmp_path):
    plan = _plan(tmp_path, cwd=None)
    cwd = Path(plan.cwd)
    assert cwd.is_dir() and not any(cwd.iterdir())


def test_nonempty_caller_cwd_is_refused_like_claude(tmp_path):
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    (cwd / "AGENTS.md").write_text("planted")
    with pytest.raises(UnsafeCwdError):
        _plan(tmp_path, cwd=cwd)


# -- R7 driving: pre-spawn rejection ----------------------------------------


def test_claude_only_field_raises_unsupported_naming_it(tmp_path):
    with pytest.raises(UnsupportedByProvider) as excinfo:
        _plan(tmp_path, permission_mode="bypassPermissions")
    assert "permission_mode" in str(excinfo.value)
    assert isinstance(excinfo.value, HarnessError)


def test_all_offending_fields_are_listed_at_once(tmp_path):
    with pytest.raises(UnsupportedByProvider) as excinfo:
        _plan(tmp_path, tools="Bash", max_turns=3)
    message = str(excinfo.value)
    assert "tools" in message and "max_turns" in message


@pytest.mark.parametrize(
    "field,value",
    [
        ("permission_mode", "plan"),
        ("tools", "Bash"),
        ("disallowed_tools", "Bash"),
        ("skills", ["s"]),
        ("max_turns", 2),
        ("hooks", {"PreToolUse": []}),
        ("omit_claude_md", True),
        ("agent_name", "reviewer"),
        ("setting_sources", ["user"]),
        ("strict_mcp", True),
        ("session_tools", "Bash"),
        ("memory", False),
        ("system_prompt", "be terse"),
    ],
)
def test_each_unhonourable_field_is_rejected(tmp_path, field, value):
    with pytest.raises(UnsupportedByProvider) as excinfo:
        _plan(tmp_path, **{field: value})
    assert field in str(excinfo.value)


def test_inherit_isolation_is_rejected(tmp_path):
    with pytest.raises(UnsupportedByProvider) as excinfo:
        _plan(tmp_path, isolation=Isolation.INHERIT)
    assert "isolation" in str(excinfo.value).lower()


def test_description_alone_is_silently_unsupported_not_an_error(tmp_path):
    plan = _plan(tmp_path, description="a reviewer")
    assert plan.argv[0] == "exec"
    assert all("a reviewer" not in tok for tok in plan.argv)


def test_start_raises_before_spawn_and_records_nothing(tmp_path):
    artifacts = tmp_path / "artifacts"
    harness = Harness(claude_argv=[sys.executable, str(FAKE_CODEX)])
    (tmp_path / "run-cwd").mkdir()
    spec = RunSpec(
        prompt="x", isolation=Isolation.CLEAN, model="gpt-5.6-luna", provider="codex",
        cwd=tmp_path / "run-cwd", artifacts_dir=artifacts, permission_mode="plan",
    )
    with pytest.raises(UnsupportedByProvider, match="permission_mode"):
        harness.start(spec)
    assert harness._processes == {}
    assert harness.store.list() == []
    assert not artifacts.exists() or not any(artifacts.iterdir())
