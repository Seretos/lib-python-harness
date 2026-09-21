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

    # An INHERIT cwd inside a git repo does not raise (unlike CLEAN) — and
    # it is the *given* cwd, not a substituted scratch directory (test-critic
    # round 1, tautology::F8: `Path(plan.cwd).exists()` alone would also
    # pass for a provider that ignored spec.cwd and returned some other
    # existing directory it made up).
    repo = tmp_path / "repo"
    assert Path(plan.cwd) == repo

    # test-critic round 1, tautology::F1: every other assertion in this test
    # uses the same fixed literals ("sonnet"/"acceptEdits") a provider could
    # hard-code without ever reading spec.model/spec.permission_mode. A
    # second spec with *different* values, asserted the same way, kills that
    # implementation.
    other_plan = _inherit_plan(tmp_path, model="opus", permission_mode="plan")
    other_argv = other_plan.argv
    assert other_argv[other_argv.index("--model") + 1] == "opus"
    assert other_argv[other_argv.index("--permission-mode") + 1] == "plan"


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
        description="Reviews code for correctness.",
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
    # test-critic round 1, tautology::F2: the injected accepted_keys must
    # reach build_launch_plan too, not just dispatch_mode in isolation —
    # otherwise the argv assertions below are not actually tied to the
    # dispatch rule (they would pass for a provider that branches on some
    # other spec difference between the two dispatch tests instead).
    plan = provider.build_launch_plan(
        spec,
        session_id=str(uuid.uuid4()),
        run_dir=tmp_path / "run",
        accepted_keys=accepted_keys,
    )
    assert "--add-dir" not in plan.argv
    assert "--agents" in plan.argv
    import json

    agents_json = json.loads(plan.argv[plan.argv.index("--agents") + 1])
    assert set(agents_json.keys()) == {"qualified-name"}
    payload = agents_json["qualified-name"]
    assert payload["prompt"] == "Body text."
    # review round 1, R1 [blocking]: description was hardcoded to None in
    # _build_agent_payload, discarding the plugin author's real text — the
    # --agents JSON payload must carry the real description, never a
    # generic filler or a dropped key.
    assert payload["description"] == "Reviews code for correctness."
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
        description="Reviews code for correctness.",
        cwd=repo,
    )
    accepted_keys = {"description", "prompt", "tools", "disallowedTools", "model",
                      "permissionMode", "maxTurns"}  # no "skills"

    mode = dispatch_mode(spec, accepted_keys)
    assert mode == "materialized"

    run_dir = tmp_path / "run"
    provider = ClaudeCliProvider()
    # Same accepted_keys threaded through as the payload test above
    # (tautology::F2) — this spec sets `skills`, which the *production*
    # AGENT_JSON_KEYS default now accepts (verified against the real CLI,
    # see change report), so without this the default dispatch would
    # choose "payload" here too and every assertion below would fail.
    plan = provider.build_launch_plan(
        spec, session_id=str(uuid.uuid4()), run_dir=run_dir, accepted_keys=accepted_keys
    )

    assert "--agents" not in plan.argv
    assert "--add-dir" in plan.argv
    add_dir_value = plan.argv[plan.argv.index("--add-dir") + 1]
    assert add_dir_value == str(run_dir / "agents")
    assert "--agent" in plan.argv
    assert plan.argv[plan.argv.index("--agent") + 1] == "qualified-name"
    materialized_path = run_dir / "agents" / ".claude" / "agents" / "qualified-name.md"
    assert materialized_path.exists()

    # review round 1, R1 [blocking]: materialize_agent_dir wrote a synthetic
    # filler string instead of the definition's real description, discarding
    # the plugin author's actual text. The materialized frontmatter must
    # carry the real description, not a generic filler.
    from lib_python_harness.agents.frontmatter import parse_frontmatter

    fields, _body = parse_frontmatter(materialized_path.read_text())
    assert fields["description"] == "Reviews code for correctness."


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


def test_effort_set_on_definition_wins_over_context():
    # test-critic round 1, tautology::F6: the fallback test above only
    # exercises "definition unset -> context wins"; without this reverse
    # case, an implementation that assigns `effort = host_context.effort`
    # unconditionally (never reading `definition.effort` at all) would
    # satisfy the fallback test too.
    from lib_python_harness.resolve import resolve

    spec = resolve(
        _definition(model="sonnet", effort="low"), _host_context(effort="high")
    )
    assert spec.effort == "low"


def test_model_inherit_passes_through_literally():
    from lib_python_harness.resolve import resolve

    spec = resolve(_definition(model="inherit"), _host_context())
    assert spec.model == "inherit"


def test_model_falls_back_to_host_context_model_when_definition_unset():
    # test-critic round 1, tautology::F6 ("the same one-sidedness applies to
    # model, whose only assertion is test_model_inherit_passes_through_
    # literally") — that test never leaves definition.model unset, so it
    # cannot tell "definition else context" apart from "definition always".
    from lib_python_harness.resolve import resolve

    spec = resolve(_definition(), _host_context(model="haiku"))
    assert spec.model == "haiku"


def test_description_is_carried_from_definition_to_runspec():
    # review round 1, R1 [blocking]: RunSpec had no description field at
    # all, so resolve() could not carry AgentDefinition.description through
    # to either dispatch carrier.
    from lib_python_harness.resolve import resolve

    spec = resolve(
        _definition(model="sonnet", description="Reviews code for correctness."),
        _host_context(),
    )
    assert spec.description == "Reviews code for correctness."


def test_description_survives_plugin_scope():
    # Unlike permission_mode/hooks/mcp_servers, description is not part of
    # the plugin-scope ignore-list assumption (plan Premises) — a plugin
    # agent's own description must still reach the child.
    from lib_python_harness.resolve import resolve

    spec = resolve(
        _definition(
            model="sonnet",
            description="A plugin agent.",
            source_scope="plugin",
        ),
        _host_context(),
    )
    assert spec.description == "A plugin agent."


def test_description_normalizes_empty_to_none():
    from lib_python_harness.resolve import resolve

    spec = resolve(_definition(model="sonnet", description=""), _host_context())
    assert spec.description is None


def test_hooks_and_mcp_servers_arrive_on_the_spec_at_project_scope():
    # test-critic round 1, tautology::F3: every existing hooks/mcp_servers
    # assertion is the *negative* one at plugin scope
    # (test_plugin_scope_drops_permission_mode_hooks_and_mcp_servers) — an
    # implementation that never copies either field from the definition at
    # all (leaving both permanently None) would satisfy that test too. This
    # is the missing positive case: project scope must actually carry them.
    from lib_python_harness.resolve import resolve

    spec = resolve(
        _definition(
            model="sonnet",
            hooks={"PreToolUse": {"matcher": "Read"}},
            mcp_servers={"demo": {"command": "demo-server"}},
        ),
        _host_context(),
    )
    assert spec.hooks == {"PreToolUse": {"matcher": "Read"}}
    assert spec.mcp_servers == {"demo": {"command": "demo-server"}}


def test_mcp_servers_falls_back_to_host_context_when_definition_unset():
    from lib_python_harness.resolve import resolve

    spec = resolve(
        _definition(model="sonnet"),
        _host_context(mcp_servers={"parent": {"command": "parent-server"}}),
    )
    assert spec.mcp_servers == {"parent": {"command": "parent-server"}}


def test_tools_and_disallowed_tools_never_become_top_level_argv_flags(tmp_path):
    plan = _inherit_plan(tmp_path, tools="Read", disallowed_tools="Bash")
    assert "--allowedTools" not in plan.argv
    assert "--disallowedTools" not in plan.argv


def test_no_system_prompt_flag_for_inherit(tmp_path):
    plan = _inherit_plan(tmp_path, system_prompt="Do the review.")
    assert "--system-prompt" not in plan.argv


def test_omit_claude_md_drops_project_from_setting_sources(tmp_path):
    # Live-verified (round 2) against installed claude v2.1.277: CLAUDE.md
    # loading is gated by the "project" entry of --setting-sources, not by
    # any --settings instructionFiles key (which was probed and found to
    # have no observable effect at all). omit_claude_md=True must drop
    # "project" and keep "user,local"; no --settings flag is emitted.
    plan = _inherit_plan(tmp_path, omit_claude_md=True)
    assert "--setting-sources" in plan.argv
    assert plan.argv[plan.argv.index("--setting-sources") + 1] == "user,local"
    assert "--settings" not in plan.argv

    unset_plan = _inherit_plan(tmp_path)
    assert (
        unset_plan.argv[unset_plan.argv.index("--setting-sources") + 1]
        == "user,project,local"
    )


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

    # test-critic round 1, tautology::F9: membership alone (`flag in argv`)
    # never pins order/values/completeness — a reordered or re-valued
    # ISOLATION_ARGV[CLEAN] would still pass every check above. This is an
    # independently written literal (the same pattern
    # tests/test_claude_cli_flags.py's own header comment documents) of the
    # exact contiguous isolation-flag subsequence CLEAN emits, checked as an
    # ordered run of tokens, not a bag of membership checks.
    expected_isolation_tokens = [
        "--setting-sources", "",
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--tools", "",
        "--output-format", "stream-json",
        "--verbose",
    ]
    n = len(expected_isolation_tokens)
    windows = [plan.argv[i : i + n] for i in range(len(plan.argv) - n + 1)]
    assert expected_isolation_tokens in windows, (
        f"expected contiguous subsequence {expected_isolation_tokens} not "
        f"found, in order, in argv {plan.argv}"
    )


# -- #24: optional `task` hand-over ------------------------------------------

_ALL_AGENT_KEYS = {
    "description", "prompt", "tools", "disallowedTools", "model",
    "permissionMode", "maxTurns", "skills",
}


def _task_plan(tmp_path, body, *, materialized, task="abc"):
    # The RunSpec resolve(..., task=task) yields (R1 pins that separately),
    # built directly so the carrier tests fail at the carrier, not at resolve().
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    (repo / ".git").mkdir(exist_ok=True)
    spec = RunSpec(
        prompt=task,
        system_prompt=body,
        isolation=Isolation.INHERIT,
        model="sonnet",
        agent_name="reviewer",
        description="Reviews code",
        cwd=repo,
        # Same forcing device test_inherit_live.py documents: an MCP server
        # is a key the --agents payload cannot carry.
        mcp_servers={"demo": {"command": "x"}} if materialized else None,
    )
    plan = ClaudeCliProvider().build_launch_plan(
        spec,
        session_id=str(uuid.uuid4()),
        run_dir=tmp_path / "run",
        accepted_keys=_ALL_AGENT_KEYS,
    )
    return spec, plan


def test_task_becomes_prompt_and_body_becomes_system_prompt():
    from lib_python_harness.resolve import resolve

    spec = resolve(_definition(), _host_context(), task="abc")
    assert spec.prompt == "abc"
    assert spec.system_prompt == "Do the review."


def test_empty_task_is_a_task_not_unset():
    from lib_python_harness.resolve import resolve

    spec = resolve(_definition(), _host_context(), task="")
    assert spec.prompt == ""
    assert spec.system_prompt == "Do the review."


def test_task_payload_carrier_carries_body_not_task(tmp_path):
    import json

    _spec, plan = _task_plan(tmp_path, "Do the review.", materialized=False)
    assert "--agents" in plan.argv
    payload = json.loads(plan.argv[plan.argv.index("--agents") + 1])["reviewer"]
    assert payload["prompt"] == "Do the review."
    assert plan.stdin == "abc"


def test_task_materialized_carrier_carries_body_not_task(tmp_path):
    from lib_python_harness.agents.frontmatter import parse_frontmatter

    _spec, plan = _task_plan(tmp_path, "Do the review.", materialized=True)
    assert "--agents" not in plan.argv
    md = tmp_path / "run" / "agents" / ".claude" / "agents" / "reviewer.md"
    _fields, body = parse_frontmatter(md.read_text())
    assert body.strip() == "Do the review."
    assert plan.stdin == "abc"


def test_task_materialized_body_with_fence_marker_survives(tmp_path):
    from lib_python_harness.agents.frontmatter import parse_frontmatter

    body = "Intro.\n---\nAfter the rule."
    _task_plan(tmp_path, body, materialized=True)
    md = tmp_path / "run" / "agents" / ".claude" / "agents" / "reviewer.md"
    _fields, parsed = parse_frontmatter(md.read_text())
    assert parsed.strip() == body


def test_task_empty_body_yields_empty_agent_body_not_the_task(tmp_path):
    import json

    _spec, plan = _task_plan(tmp_path, "", materialized=False)
    payload = json.loads(plan.argv[plan.argv.index("--agents") + 1])["reviewer"]
    assert payload["prompt"] == ""
    assert plan.stdin == "abc"


def test_resolve_without_task_is_unchanged():
    import dataclasses
    import inspect

    from lib_python_harness.resolve import resolve

    spec = resolve(
        _definition(model="sonnet", permission_mode="plan", tools="Read"),
        _host_context(cwd="/tmp/irrelevant"),
    )
    got = dataclasses.asdict(spec)
    defaults = {f.name: f.default for f in dataclasses.fields(RunSpec)
                if f.default is not dataclasses.MISSING}
    expected = {
        **defaults,
        "prompt": "Do the review.",
        "system_prompt": "Do the review.",
        "isolation": Isolation.INHERIT,
        "model": "sonnet",
        "effort": "medium",
        "cwd": "/tmp/irrelevant",
        "mcp_servers": {},
        "permission_mode": "plan",
        "tools": "Read",
        "agent_name": "reviewer",
        "description": "Reviews code",
    }
    assert got == expected
    # Existing positional call shape (definition, context, config) is intact.
    params = list(inspect.signature(resolve).parameters.values())
    assert [p.name for p in params[:3]] == ["definition", "host_context", "config"]
    assert params[3].name == "task"
    assert params[3].kind is inspect.Parameter.KEYWORD_ONLY


def test_agent_body_falls_back_to_prompt_when_system_prompt_unset(tmp_path):
    import json

    plan = _inherit_plan(
        tmp_path, prompt="Only a prompt.", agent_name="solo", description="d"
    )
    payload = json.loads(plan.argv[plan.argv.index("--agents") + 1])["solo"]
    assert payload["prompt"] == "Only a prompt."
    assert plan.stdin == "Only a prompt."


def test_clean_spec_prompt_stays_stdin_and_system_prompt_flag(tmp_path):
    repo = tmp_path / "cwd"
    repo.mkdir()
    spec = RunSpec(
        prompt="the user message",
        isolation=Isolation.CLEAN,
        model="haiku",
        system_prompt="the system text",
        cwd=repo,
    )
    plan = ClaudeCliProvider().build_launch_plan(
        spec, session_id=str(uuid.uuid4()), run_dir=tmp_path / "run"
    )
    assert plan.stdin == "the user message"
    assert plan.argv[plan.argv.index("--system-prompt") + 1] == "the system text"
