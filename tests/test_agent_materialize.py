"""R8 — the materialized fallback is a real carrier.

Tests `lib_python_harness.providers.claude_cli.materialize_agent_dir(spec,
run_dir)` (pure unit test, no CLI). `materialize_agent_dir` is imported
first, and independently of `agents.frontmatter`, so a collection failure
here is unambiguously attributable to the missing `materialize_agent_dir`
name (plan's stated RED reason: "ImportError on materialize_agent_dir"), not
to `agents/frontmatter.py` also being absent.

`spec` is a fully-resolved `RunSpec` carrying the 9 new INHERIT-only fields
the plan's Mechanism balance section names (`permission_mode`, `tools`,
`disallowed_tools`, `skills`, `max_turns`, `hooks`, `mcp_servers`,
`omit_claude_md`, `agent_name`) — this only becomes constructible once
`providers/base.py` gains those fields (plan Approach, `providers/base.py`
bullet), which is phase=implement's job, not this round's.
"""
from __future__ import annotations

from lib_python_harness.providers.claude_cli import materialize_agent_dir
from lib_python_harness.agents.frontmatter import parse_frontmatter

from pathlib import Path

from lib_python_harness.providers.base import Isolation, RunSpec


def _resolved_spec(**overrides):
    kwargs = dict(
        prompt="Do the thing.",
        isolation=Isolation.INHERIT,
        model="sonnet",
        permission_mode="acceptEdits",
        tools="Read, Glob",
        disallowed_tools="Bash",
        skills=["reviewer-skill"],
        max_turns=5,
        hooks={"PreToolUse": {"matcher": "Read"}},
        mcp_servers={"demo": {"command": "demo-server"}},
        omit_claude_md=False,
        agent_name="my-plugin:reviewer",
    )
    kwargs.update(overrides)
    return RunSpec(**kwargs)


def test_round_trip_carries_every_resolved_field_including_rejected_keys(tmp_path):
    spec = _resolved_spec()
    run_dir = tmp_path / "run"

    dest = materialize_agent_dir(spec, run_dir)

    expected_path = run_dir / "agents" / ".claude" / "agents" / "my-plugin__reviewer.md"
    assert Path(dest) == expected_path
    assert expected_path.exists()

    fields, body = parse_frontmatter(expected_path.read_text())
    assert fields["name"] == "my-plugin__reviewer"
    assert fields["model"] == "sonnet"
    assert fields["permissionMode"] == "acceptEdits"
    assert fields["tools"] == "Read, Glob"
    assert fields["disallowedTools"] == "Bash"
    assert fields["skills"] == ["reviewer-skill"]
    assert fields["maxTurns"] == 5
    assert fields["hooks"] == {"PreToolUse": {"matcher": "Read"}}
    assert fields["mcpServers"] == {"demo": {"command": "demo-server"}}
    assert body == spec.prompt


def test_colon_in_agent_name_becomes_double_underscore_in_filename_and_name_field(tmp_path):
    spec = _resolved_spec(agent_name="plugin-a:sub:agent")
    run_dir = tmp_path / "run"

    dest = materialize_agent_dir(spec, run_dir)

    assert Path(dest).name == "plugin-a__sub__agent.md"
    fields, _body = parse_frontmatter(Path(dest).read_text())
    assert fields["name"] == "plugin-a__sub__agent"


def test_run_dir_need_not_exist_beforehand(tmp_path):
    # test-critic round 1, tautology::F7: the removed `assert not
    # run_dir.exists()` ran *before* materialize_agent_dir was ever called,
    # over a path this test itself never created — it could not come out
    # false under any implementation, so it was not evidence of anything.
    # The real content of the edge case is `Path(dest).exists()` below,
    # which does exercise `mkdir(parents=True, ...)` on a genuinely
    # multi-level-missing run_dir.
    spec = _resolved_spec()
    run_dir = tmp_path / "does" / "not" / "exist" / "yet"

    dest = materialize_agent_dir(spec, run_dir)

    assert Path(dest).exists()


def test_body_containing_a_dash_dash_dash_line_does_not_break_the_fence(tmp_path):
    spec = _resolved_spec(prompt="Line one.\n---\nLine after a fence-like line.\n")
    run_dir = tmp_path / "run"

    dest = materialize_agent_dir(spec, run_dir)

    fields, body = parse_frontmatter(Path(dest).read_text())
    assert fields["name"] == "my-plugin__reviewer"
    assert body == spec.prompt


def test_empty_body_still_produces_a_valid_file(tmp_path):
    spec = _resolved_spec(prompt="")
    run_dir = tmp_path / "run"

    dest = materialize_agent_dir(spec, run_dir)

    fields, body = parse_frontmatter(Path(dest).read_text())
    assert fields["name"] == "my-plugin__reviewer"
    assert body == ""
