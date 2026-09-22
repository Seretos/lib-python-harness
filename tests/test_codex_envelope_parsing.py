"""R3 — codex's JSONL event stream maps onto the shared `RunResult`.

Fed by streams recorded from the real CLI (tests/fixtures/codex_events_*.jsonl,
captured on native Windows; see .adev/4-1/codex-survey.md) — never an invented
event shape.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from lib_python_harness.providers.base import Isolation, RunSpec
from lib_python_harness.providers.codex_cli import CodexCliProvider

FIXTURES = Path(__file__).parent / "fixtures"


def _lines(name):
    return [ln for ln in (FIXTURES / name).read_text(encoding="utf-8").splitlines() if ln.strip()]


def test_success_stream_maps_all_envelope_fields():
    lines = _lines("codex_events_sample.jsonl")
    thread_id = json.loads(lines[0])["thread_id"]

    result = CodexCliProvider().parse_events(lines)

    assert result.text == "OK"
    assert result.session_id == thread_id
    assert result.is_error is False
    assert result.usage["input_tokens"] == 12404
    assert result.usage["output_tokens"] == 5
    assert result.cost is None  # codex reports tokens, not dollars


def test_failed_turn_is_an_error_envelope():
    result = CodexCliProvider().parse_events(_lines("codex_events_failed.jsonl"))
    assert result.is_error is True
    assert result.subtype == "turn.failed"  # terminal event type of the recorded failed stream
    ok = CodexCliProvider().parse_events(_lines("codex_events_sample.jsonl"))
    assert ok.subtype != "turn.failed"  # a successful turn does not carry the failure subtype
    assert result.text == ""  # a failed turn produced no agent message


def test_truncated_stream_raises():
    lines = _lines("codex_events_sample.jsonl")[:2]  # thread.started, turn.started
    with pytest.raises(ValueError):  # same contract as ClaudeCliProvider (truncated stream)
        CodexCliProvider().parse_events(lines)


def test_empty_stream_raises():
    with pytest.raises(ValueError):  # same contract as ClaudeCliProvider (truncated stream)
        CodexCliProvider().parse_events([])


def test_last_agent_message_wins():
    lines = _lines("codex_events_sample.jsonl")
    extra = json.dumps({"type": "item.completed",
                        "item": {"id": "item_9", "type": "agent_message", "text": "LAST"}})
    # the sample already holds the "OK" message; LAST comes strictly after it,
    # so first-wins ("OK") and last-wins ("LAST") differ
    lines = lines[:-1] + [extra] + lines[-1:]
    assert CodexCliProvider().parse_events(lines).text == "LAST"


def test_schema_stream_yields_structured_output_when_requested(tmp_path):
    # The provider instance that built the launch plan (and so knows a schema
    # was requested) is the one that parses that run's stream.
    provider = CodexCliProvider()
    schema = {"type": "object", "properties": {"answer": {"type": "string"}},
              "required": ["answer"], "additionalProperties": False}
    (tmp_path / "cwd").mkdir()
    provider.build_launch_plan(
        RunSpec(prompt="p", isolation=Isolation.CLEAN, model="gpt-5.6-luna", provider="codex",
                json_schema=schema, cwd=tmp_path / "cwd"),
        session_id=str(uuid.uuid4()), run_dir=tmp_path / "run",
    )
    result = provider.parse_events(_lines("codex_events_schema.jsonl"))
    assert result.structured_output == {"answer": "OK"}
    assert result.text == '{"answer":"OK"}'


def test_valid_json_text_is_not_structured_output_when_no_schema_requested():
    # Same stream, but this provider never built a plan with a json_schema.
    result = CodexCliProvider().parse_events(_lines("codex_events_schema.jsonl"))
    assert result.text == '{"answer":"OK"}'
    assert result.structured_output is None
