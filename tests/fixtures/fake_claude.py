#!/usr/bin/env python3
"""Canned stream-json emitter standing in for the real `claude` binary (R7).

Used by ``tests/test_harness_offline.py::test_provenance_fields_from_spawned_run``
so that test can drive a full spawn/parse/persist cycle through the real
``Harness``/``ClaudeCliProvider`` code paths without a live CLI or auth.

Ignores its argv except ``--version`` (answered the way the real CLI would,
so the harness's own `claude --version` provenance step has something real
to parse) and ``--session-id`` (echoed back into the emitted events, the way
the real CLI would echo the session it was told to use). Reads and discards
stdin (the prompt), then emits a fixed stream-json event sequence ending in
a terminal ``result`` event, mimicking
``claude -p --output-format stream-json --verbose``.
"""
from __future__ import annotations

import json
import sys

FAKE_VERSION = "0.0.1 (Claude Code)"


def main() -> int:
    argv = sys.argv[1:]

    if "--version" in argv:
        print(FAKE_VERSION)
        return 0

    # Drain stdin (the prompt) the same way the real CLI would.
    sys.stdin.read()

    session_id = "00000000-0000-4000-8000-000000000000"
    for i, token in enumerate(argv):
        if token == "--session-id" and i + 1 < len(argv):
            session_id = argv[i + 1]

    events = [
        {"type": "system", "subtype": "init", "session_id": session_id},
        {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "OK"}]},
        },
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": "OK",
            "session_id": session_id,
            "duration_ms": 42,
            "usage": {"input_tokens": 10, "output_tokens": 2},
            "total_cost_usd": 0.0001,
        },
    ]
    for event in events:
        print(json.dumps(event), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
