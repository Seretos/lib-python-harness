"""R1 additional edge-case coverage — the same terminal-event parse driven
offline from tests/fixtures/result_envelope.jsonl: success, is_error +
subtype, structured_output present/absent, usage/cost, and a truncated
stream (no terminal `result` event) mapping to a failure outcome.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lib_python_harness.providers.claude_cli import ClaudeCliProvider

FIXTURE = Path(__file__).parent / "fixtures" / "result_envelope.jsonl"


def _load_scenarios():
    scenarios = {}
    with FIXTURE.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            scenarios[obj["scenario"]] = [json.dumps(evt) for evt in obj["stream"]]
    return scenarios


SCENARIOS = _load_scenarios()


def test_success_envelope_parses_to_result_text():
    result = ClaudeCliProvider().parse_events(SCENARIOS["success"])
    assert result.text == "OK"
    assert result.is_error is False
    assert result.usage["input_tokens"] == 50
    assert result.cost == pytest.approx(0.001)


def test_is_error_envelope_carries_subtype():
    result = ClaudeCliProvider().parse_events(SCENARIOS["is_error_with_subtype"])
    assert result.is_error is True
    assert result.subtype == "error_max_turns"


def test_structured_output_present():
    result = ClaudeCliProvider().parse_events(SCENARIOS["structured_output_present"])
    assert result.structured_output == {"answer": 42}


def test_structured_output_absent_is_none():
    result = ClaudeCliProvider().parse_events(SCENARIOS["structured_output_absent"])
    assert result.structured_output is None


def test_truncated_stream_without_terminal_result_is_a_failure():
    # "A missing terminal event => FAILED with the raw tail" (plan Approach).
    # The exact exception type is an implementation detail of parse_events;
    # what matters here is that a truncated stream is never silently
    # accepted as a successful result.
    with pytest.raises(Exception):
        ClaudeCliProvider().parse_events(SCENARIOS["truncated_stream"])


# -- package 25: describe_last_activity (liveness sign on RUNNING results) ----


def _line(obj) -> str:
    return json.dumps(obj)


def _assistant(*blocks) -> str:
    return _line({"type": "assistant", "message": {"content": list(blocks)}})


_INIT_LINE = _line({"type": "system", "subtype": "init", "session_id": "s"})
_TOOL_USE = {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}}
_TEXT = {"type": "text", "text": "hello"}


def test_describe_last_activity_names_the_last_tool_use():
    lines = [_INIT_LINE, _assistant(_TEXT), _assistant(_TOOL_USE)]
    assert ClaudeCliProvider().describe_last_activity(lines) == "tool_use:Bash"


def test_describe_last_activity_uses_the_last_tool_use_block_of_the_newest_event():
    other = {"type": "tool_use", "id": "t2", "name": "Read", "input": {}}
    lines = [_assistant(_TOOL_USE), _assistant(_TEXT, _TOOL_USE, other)]
    assert ClaudeCliProvider().describe_last_activity(lines) == "tool_use:Read"


def test_describe_last_activity_text_only_stream():
    lines = [_INIT_LINE, _assistant(_TEXT)]
    assert ClaudeCliProvider().describe_last_activity(lines) == "text"


def test_describe_last_activity_init_only_stream():
    assert ClaudeCliProvider().describe_last_activity([_INIT_LINE]) == "init"


def test_describe_last_activity_skips_a_truncated_trailing_line():
    lines = [_assistant(_TOOL_USE), '{"type": "assist']
    assert ClaudeCliProvider().describe_last_activity(lines) == "tool_use:Bash"


def test_describe_last_activity_empty_or_unrecognizable_stream_is_none():
    provider = ClaudeCliProvider()
    assert provider.describe_last_activity([]) is None
    assert provider.describe_last_activity(["", "not json", _line({"type": "mystery"})]) is None
