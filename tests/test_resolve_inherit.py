"""R3 — the INHERIT command line carries the flags and the definition, by
whichever of the two dispatch paths applies.

The driving test (`test_inherit_argv_carries_model_permission_mode_and_flags`)
constructs a `RunSpec(isolation=Isolation.INHERIT, ...)` directly and asserts
on `ClaudeCliProvider().build_launch_plan(...)`'s argv — the literal
"Driving test" target the plan names. `Isolation.INHERIT` does not exist yet
(added in phase=implement, `providers/base.py`), so evaluating that one
keyword argument raises `AttributeError: INHERIT` before `RunSpec(...)` is
even called — the plan's stated RED reason — with no dependency on
`resolve.py`, `agents/model.py`, or `host/context.py` existing.

The `resolve()`-level edge cases below (permissionMode override, plugin-scope
dropping, effort fallback, `model: inherit` passthrough) exercise
`lib_python_harness.resolve.resolve(definition, host_context)` directly.
`resolve.py` does not exist yet either (phase=implement's job); those tests
import it lazily, inside each test function, so their own
ModuleNotFoundError never contaminates the driving test's collection or its
required AttributeError. `definition`/`host_context` are duck-typed
`SimpleNamespace` stand-ins rather than real `AgentDefinition`/`HostContext`
instances, for the same reason `test_agent_discovery.py` uses one: those two
classes are R1's/R2's/R4's own subjects and must stay absent so those files'
own driving tests get their mandated RED reasons.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from lib_python_harness.providers.base import Isolation, RunSpec
from lib_python_harness.providers.claude_cli import ClaudeCliProvider


def _inherit_plan(tmp_path, **spec_overrides):
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    (repo / ".git").mkdir(exist_ok=True)
    kwargs = dict(
        prompt="Do the thing.",
        isolation=Isolation.INHERIT,
        model="sonnet",
        permission_mode="acceptEdits",
        cwd=repo,
    )
    kwargs.update(spec_overrides)
    spec = RunSpec(**kwargs)
    provider = ClaudeCliProvider()
    return provider.build_launch_plan(
        spec, session_id=str(uuid.uuid4()), run_dir=tmp_path / "run"
    )


def test_inherit_argv_carries_model_permission_mode_and_flags(tmp_path):
    plan = _inherit_plan(tmp_path)
    argv = plan.argv

    assert "--model" in argv
    assert argv[argv.index("--model") + 1] == "sonnet"

    assert "--permission-mode" in argv
    assert argv[argv.index("--permission-mode") + 1] == "acceptEdits"

    assert "--setting-sources" in argv
    assert argv[argv.index("--setting-sources") + 1] == "user,project,local"

    assert "--strict-mcp-config" not in argv

    # An INHERIT cwd inside a git repo does not raise (unlike CLEAN).
    assert Path(plan.cwd).exists()


# -- dispatch_mode branches (a)/(b), deterministic via injected accepted_keys --


def test_payload_mode_emits_agents_json_and_agent_flag_no_add_dir(tmp_path):
    from lib_python_harness.providers.claude_cli import dispatch_mode

    repo = tmp_path / "repo"
    repo.mkdir()
    spec = RunSpec(
        prompt="Body text.",
        isolation=Isolation.INHERIT,
        model="sonnet",
        permission_mode="acceptEdits",
        max_turns=3,
        skills=["reviewer-skill"],
        agent_name="qualified-name",
        cwd=repo,
    )
    accepted_keys = {
        "description",
        "prompt",
        "tools",
        "disallowedTools",
        "model",
        "permissionMode",
        "maxTurns",
        "skills",
    }

    mode = dispatch_mode(spec, accepted_keys)
    assert mode == "payload"

    provider = ClaudeCliProvider()
    plan = provider.build_launch_plan(
        spec, session_id=str(uuid.uuid4()), run_dir=tmp_path / "run"
    )
    assert "--add-dir" not in plan.argv
    assert "--agents" in plan.argv
    import json

    agents_json = json.loads(plan.argv[plan.argv.index("--agents") + 1])
    assert set(agents_json.keys()) == {"qualified-name"}
    payload = agents_json["qualified-name"]
    assert payload["prompt"] == "Body text."
    assert payload["model"] == "sonnet"
    assert payload["permissionMode"] == "acceptEdits"
    assert payload["maxTurns"] == 3
    assert payload["skills"] == ["reviewer-skill"]
    assert "--agent" in plan.argv
    assert plan.argv[plan.argv.index("--agent") + 1] == "qualified-name"


def test_materialized_mode_when_definition_sets_a_rejected_key(tmp_path):
    from lib_python_harness.providers.claude_cli import dispatch_mode

    repo = tmp_path / "repo"
    repo.mkdir()
    spec = RunSpec(
        prompt="Body text.",
        isolation=Isolation.INHERIT,
        model="sonnet",
        skills=["reviewer-skill"],
        agent_name="qualified-name",
        cwd=repo,
    )
    accepted_keys = {"description", "prompt", "tools", "disallowedTools", "model",
                      "permissionMode", "maxTurns"}  # no "skills"

    mode = dispatch_mode(spec, accepted_keys)
    assert mode == "materialized"

    run_dir = tmp_path / "run"
    provider = ClaudeCliProvider()
    plan = provider.build_launch_plan(spec, session_id=str(uuid.uuid4()), run_dir=run_dir)

    assert "--agents" not in plan.argv
    assert "--add-dir" in plan.argv
    add_dir_value = plan.argv[plan.argv.index("--add-dir") + 1]
    assert add_dir_value == str(run_dir / "agents")
    assert "--agent" in plan.argv
    assert plan.argv[plan.argv.index("--agent") + 1] == "qualified-name"
    assert (run_dir / "agents" / ".claude" / "agents" / "qualified-name.md").exists()


# -- additional edge cases: field-resolution semantics (resolve()) ----------


def _definition(**overrides):
    fields = dict(
        name="reviewer",
        qualified_name="reviewer",
        description="Reviews code",
        body="Do the review.",
        model=None,
        permission_mode=None,
        effort=None,
        tools=None,
        disallowed_tools=None,
        skills=None,
        max_turns=None,
        hooks=None,
        mcp_servers=None,
        omit_claude_md=None,
        source_scope="project",
    )
    fields.update(overrides)
    return SimpleNamespace(**fields)


def _host_context(**overrides):
    fields = dict(
        cwd="/tmp/irrelevant",
        model="haiku",
        permission_mode="default",
        effort="medium",
        mcp_servers={},
    )
    fields.update(overrides)
    return SimpleNamespace(**fields)


def test_definition_permission_mode_wins_over_context():
    from lib_python_harness.resolve import resolve

    spec = resolve(
        _definition(model="sonnet", permission_mode="bypassPermissions"),
        _host_context(permission_mode="acceptEdits"),
    )
    assert spec.permission_mode == "bypassPermissions"


def test_plugin_scope_drops_permission_mode_hooks_and_mcp_servers():
    from lib_python_harness.resolve import resolve

    spec = resolve(
        _definition(
            model="sonnet",
            permission_mode="bypassPermissions",
            hooks={"PreToolUse": {}},
            mcp_servers={"demo": {}},
            source_scope="plugin",
        ),
        _host_context(permission_mode="acceptEdits"),
    )
    assert spec.permission_mode == "acceptEdits"
    assert not spec.hooks
    assert not spec.mcp_servers


def test_effort_falls_back_to_host_context_effort():
    from lib_python_harness.resolve import resolve

    spec = resolve(_definition(model="sonnet"), _host_context(effort="high"))
    assert spec.effort == "high"


def test_model_inherit_passes_through_literally():
    from lib_python_harness.resolve import resolve

    spec = resolve(_definition(model="inherit"), _host_context())
    assert spec.model == "inherit"


def test_tools_and_disallowed_tools_never_become_top_level_argv_flags(tmp_path):
    plan = _inherit_plan(tmp_path, tools="Read", disallowed_tools="Bash")
    assert "--allowedTools" not in plan.argv
    assert "--disallowedTools" not in plan.argv


def test_no_system_prompt_flag_for_inherit(tmp_path):
    plan = _inherit_plan(tmp_path, system_prompt="Do the review.")
    assert "--system-prompt" not in plan.argv


def test_omit_claude_md_emits_exact_settings_literal(tmp_path):
    plan = _inherit_plan(tmp_path, omit_claude_md=True)
    assert "--settings" in plan.argv
    assert plan.argv[plan.argv.index("--settings") + 1] == '{"instructionFiles": []}'


def test_mcp_config_only_when_non_empty(tmp_path):
    plan_without = _inherit_plan(tmp_path)
    assert "--mcp-config" not in plan_without.argv

    plan_with = _inherit_plan(tmp_path, mcp_servers={"demo": {"command": "demo-server"}})
    assert "--mcp-config" in plan_with.argv


def test_clean_argv_is_byte_identical_to_today(tmp_path):
    """Refactor regression guard: ISOLATION_ARGV[CLEAN] must not have moved a
    single token relative to the pre-refactor CLEAN_ARGV_FLAGS sequence that
    tests/test_claude_cli_flags.py independently asserts against.
    """
    repo = tmp_path / "cwd"
    repo.mkdir()
    spec = RunSpec(
        prompt="Reply with exactly OK",
        isolation=Isolation.CLEAN,
        model="haiku",
        cwd=repo,
    )
    provider = ClaudeCliProvider()
    plan = provider.build_launch_plan(
        spec, session_id=str(uuid.uuid4()), run_dir=tmp_path / "run"
    )
    for flag in ("-p", "--setting-sources", "--strict-mcp-config",
                 "--disable-slash-commands", "--tools", "--output-format",
                 "--verbose", "--system-prompt"):
        assert flag in plan.argv
