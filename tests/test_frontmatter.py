"""R2 — degraded and nested definitions still load.

Tests `lib_python_harness.agents.frontmatter`: the hand-rolled YAML-subset
parser/emitter (`parse_frontmatter`/`dump_frontmatter`/`FrontmatterError`,
plan Approach) plus the file-to-`AgentDefinition` loader
(`load_agent_definition`) that composes the parser with the filename-stem /
`FALLBACK_DESCRIPTION` degradation rule the plan's R2 behaviour describes.

Module-placement assumption (documented, not verified against the plan's
prose, which only says "agents/frontmatter.py ... hand-rolls a YAML subset"
and separately, under agents/model.py's bullet, defines `FALLBACK_DESCRIPTION`
and the `AgentDefinition` dataclass): this file assumes `load_agent_definition`
— the function that turns a `.md` path plus a `source_scope` into a full
`AgentDefinition`, including the filename-stem name-fallback and the
malformed-frontmatter -> `FALLBACK_DESCRIPTION` degradation — lives in
`agents/frontmatter.py` too (importing the dataclass/constant from
`agents/model.py`), since R2's own "Expected RED reason" is a single
"import error on the missing parser module" and frontmatter.py is the only
candidate "parser module" named. If phase=implement places it in
`agents/sources.py` or `agents/model.py` instead, only this file's import
line needs to move — the assertions below do not otherwise care where the
function lives.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from lib_python_harness.agents.frontmatter import (
    FrontmatterError,
    dump_frontmatter,
    load_agent_definition,
    parse_frontmatter,
)


def _write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text)
    return path


# -- R2 driving behaviour: three files, three loading rules -----------------


def test_file_with_no_name_loads_under_filename_stem(tmp_path):
    path = _write(
        tmp_path,
        "reviewer.md",
        "---\ndescription: Reviews code\n---\nDo the review.\n",
    )
    definition = load_agent_definition(path, source_scope="project")
    assert definition.name == "reviewer"
    assert definition.description == "Reviews code"
    assert definition.body.strip() == "Do the review."


def test_file_with_unparseable_frontmatter_loads_with_fallback_description(tmp_path):
    from lib_python_harness.agents.model import FALLBACK_DESCRIPTION

    # Genuinely malformed: an opening fence with no closing fence, so the
    # low-level parser cannot even tell where frontmatter ends.
    path = _write(tmp_path, "broken.md", "---\nname: [unterminated\nbody text\n")
    definition = load_agent_definition(path, source_scope="project")
    assert definition.description == FALLBACK_DESCRIPTION
    assert definition.name == "broken"
    assert definition.tools is None
    assert definition.model is None
    assert definition.permission_mode is None


def test_nested_hooks_and_mcp_servers_load_as_dicts_without_degrading(tmp_path):
    path = _write(
        tmp_path,
        "full.md",
        (
            "---\n"
            "name: full-agent\n"
            "description: Has everything\n"
            "tools: Read, Glob\n"
            "model: sonnet\n"
            "permissionMode: acceptEdits\n"
            "hooks:\n"
            "  PreToolUse:\n"
            "    matcher: Read\n"
            "    command: echo hi\n"
            "mcpServers:\n"
            "  demo:\n"
            "    command: demo-server\n"
            "---\n"
            "Body text.\n"
        ),
    )
    definition = load_agent_definition(path, source_scope="project")
    assert definition.name == "full-agent"
    assert definition.description == "Has everything"
    assert definition.tools == "Read, Glob"
    assert definition.model == "sonnet"
    assert definition.permission_mode == "acceptEdits"
    assert definition.hooks == {
        "PreToolUse": {"matcher": "Read", "command": "echo hi"}
    }
    assert definition.mcp_servers == {"demo": {"command": "demo-server"}}


# -- Additional edge cases: verified real shapes -----------------------------


def test_block_scalar_description():
    fields, body = parse_frontmatter(
        "---\ndescription: |\n  Line one.\n  Line two.\n---\nBody.\n"
    )
    assert fields["description"] == "Line one.\nLine two.\n"
    assert body.strip() == "Body."


def test_skills_block_sequence():
    fields, _ = parse_frontmatter(
        "---\nskills:\n  - one\n  - two\n---\nBody.\n"
    )
    assert fields["skills"] == ["one", "two"]


def test_tools_inline_comma_list_is_preserved_as_scalar():
    fields, _ = parse_frontmatter("---\ntools: Read, Glob\n---\nBody.\n")
    assert fields["tools"] == "Read, Glob"


def test_omit_claude_md_and_model_inherit_coercion():
    fields, _ = parse_frontmatter(
        "---\nomitClaudeMd: true\nmodel: inherit\n---\nBody.\n"
    )
    assert fields["omitClaudeMd"] is True
    assert fields["model"] == "inherit"


def test_values_containing_colon_are_preserved():
    fields, _ = parse_frontmatter(
        '---\ndescription: "Use this when: the user asks"\n---\nBody.\n'
    )
    assert fields["description"] == "Use this when: the user asks"


def test_no_fence_at_all_is_treated_as_pure_body():
    fields, body = parse_frontmatter("Just a body, no frontmatter fence.\n")
    assert fields == {}
    assert body.strip() == "Just a body, no frontmatter fence."


def test_two_level_nesting_under_hooks():
    fields, _ = parse_frontmatter(
        (
            "---\n"
            "hooks:\n"
            "  PreToolUse:\n"
            "    matcher:\n"
            "      tool: Read\n"
            "      when: always\n"
            "---\n"
            "Body.\n"
        )
    )
    assert fields["hooks"] == {
        "PreToolUse": {"matcher": {"tool": "Read", "when": "always"}}
    }


def test_parse_frontmatter_raises_frontmattererror_on_malformed_input():
    with pytest.raises(FrontmatterError):
        parse_frontmatter("---\nname: [unterminated\nbody text\n")


def test_dump_frontmatter_round_trips_through_parse_frontmatter():
    fields = {
        "name": "round-trip",
        "description": "A description",
        "tools": "Read, Glob",
        "hooks": {"PreToolUse": {"matcher": "Read"}},
    }
    body = "The body text.\n"
    text = dump_frontmatter(fields, body)
    parsed_fields, parsed_body = parse_frontmatter(text)
    assert parsed_fields == fields
    assert parsed_body == body


def test_dump_frontmatter_emits_real_yaml_style_lines_not_json():
    # test-critic round 1, tautology::F5: a round trip through the parser's
    # *own* inverse proves only that dump and parse are mutually
    # consistent — a dump/parse pair that agreed on emitting
    # `json.dumps(fields)` inside the fence would pass the round-trip test
    # above while producing a file Claude Code's own agent loader (a real
    # YAML-ish parser, not this module) could not read, defeating the
    # entire purpose of the materialized carrier (plan R8). This pins the
    # actual emitted shape against literals written independently of
    # dump_frontmatter's own implementation.
    fields = {"name": "round-trip", "tools": "Read, Glob"}
    text = dump_frontmatter(fields, "Body.\n")

    assert text.startswith("---\n")
    lines = text.split("\n")
    assert "name: round-trip" in lines
    assert "tools: Read, Glob" in lines
    # Not a JSON object anywhere in the fenced header: a json.dumps(fields)
    # implementation would produce a single '{"name": ...}' line instead of
    # the two plain 'key: value' lines asserted above.
    header = text.split("---\n", 2)[1]
    assert "{" not in header
    assert "}" not in header
