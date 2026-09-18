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
