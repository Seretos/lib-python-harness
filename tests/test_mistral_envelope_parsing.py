"""R2 + R7 — Vibe's `--output streaming` stream maps onto the shared
`RunResult`.

Fed by a stream recorded from the real CLI (tests/fixtures/mistral_events_sample.jsonl,
`vibe` 2.25.4 on native Windows) — never an invented event shape. Line 1 is the
echoed user message, line 2 a reasoning entry, line 3 the assistant reply.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from lib_python_harness.harness import Harness
from lib_python_harness.providers.base import Isolation, RunSpec
from lib_python_harness.providers.mistral_cli import MistralCliProvider
from lib_python_harness.runtime.lifecycle import RunState

FIXTURES = Path(__file__).parent / "fixtures"
FAKE_MISTRAL = FIXTURES / "fake_mistral.py"
NON_ASCII = "Grüße — 日本語 ✓ éè"


def _lines():
    return [ln for ln in (FIXTURES / "mistral_events_sample.jsonl").read_text(
        encoding="utf-8").splitlines() if ln.strip()]


def _assistant_entry():
    return json.loads(_lines()[2])


def test_success_stream_maps_envelope_fields():
    lines = _lines()
    session_id = json.loads(lines[0])["sessionId"]

    result = MistralCliProvider().parse_events(lines)

    assert result.text == "OK"
    assert result.session_id == session_id
    assert result.is_error is False
    assert result.usage == {}  # streaming entries carry no token stats
    assert result.cost is None


def test_stream_without_assistant_message_raises():
    # user echo + reasoning only: the truncated-stream condition
    with pytest.raises(ValueError):
        MistralCliProvider().parse_events(_lines()[:2])


def test_user_message_alone_is_not_an_answer():
    with pytest.raises(ValueError):
        MistralCliProvider().parse_events(_lines()[:1])


def test_empty_stream_raises():
    with pytest.raises(ValueError):
        MistralCliProvider().parse_events([])


def test_last_assistant_message_wins():
    lines = _lines()
    extra = _assistant_entry()
    extra["id"] = "extra-id"
    extra["content"] = [{"type": "text", "text": "LAST"}]
    assert MistralCliProvider().parse_events(lines + [json.dumps(extra)]).text == "LAST"


def test_multi_block_content_is_joined_in_order():
    entry = _assistant_entry()
    entry["content"] = [{"type": "text", "text": "ALPHA"}, {"type": "text", "text": "OMEGA"}]
    text = MistralCliProvider().parse_events(_lines()[:2] + [json.dumps(entry)]).text
    assert "ALPHA" in text and "OMEGA" in text
    assert text.index("ALPHA") < text.index("OMEGA")


def test_incomplete_entries_are_ignored():
    partial = _assistant_entry()
    partial["generationStatus"] = "in_progress"
    partial["content"] = [{"type": "text", "text": "PARTIAL"}]
    result = MistralCliProvider().parse_events(_lines() + [json.dumps(partial)])
    assert result.text == "OK"
    # and an in-progress-only assistant entry is not an answer
    with pytest.raises(ValueError):
        MistralCliProvider().parse_events(_lines()[:2] + [json.dumps(partial)])


def test_blank_lines_are_tolerated():
    lines = [""] + _lines()[:2] + ["   "] + _lines()[2:]
    assert MistralCliProvider().parse_events(lines).text == "OK"


# -- R7: non-ASCII replies survive the events-file read ----------------------


def _run(tmp_path, *fake_args):
    (tmp_path / "run-cwd").mkdir(exist_ok=True)
    harness = Harness(claude_argv=[sys.executable, str(FAKE_MISTRAL), *fake_args])
    result = harness.run(RunSpec(
        prompt="Reply with something non-ASCII", isolation=Isolation.CLEAN,
        model="mistral-medium-3.5", provider="mistral", cwd=tmp_path / "run-cwd",
        artifacts_dir=tmp_path / "artifacts",
    ))
    return harness, result


def test_non_ascii_reply_round_trips(tmp_path):
    """R7 driving test."""
    harness, result = _run(tmp_path, "--reply-non-ascii")
    # the file on disk really is raw UTF-8, not ASCII-escaped JSON
    events = Path(harness.store.get(result.run_id)["events_path"]).read_bytes()
    assert NON_ASCII.encode("utf-8") in events
    assert result.state == RunState.COMPLETED
    assert result.text == NON_ASCII


def test_stream_truncated_mid_codepoint_fails_the_run_without_raising(tmp_path):
    harness, result = _run(tmp_path, "--truncate-mid-codepoint")
    assert result.state == RunState.FAILED
