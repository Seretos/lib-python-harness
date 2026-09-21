#!/usr/bin/env python3
"""Canned stream-json emitter standing in for the real `claude` binary (R7).

Used by ``tests/test_harness_offline.py::test_provenance_fields_from_spawned_run``
so that test can drive a full spawn/parse/persist cycle through the real
``Harness``/``ClaudeCliProvider`` code paths without a live CLI or auth.

Ignores its argv except ``--version`` (answered the way the real CLI would,
so the harness's own `claude --version` provenance step has something real
to parse), ``--session-id`` (echoed back into the emitted events, the way
the real CLI would echo the session it was told to use) and ``--sleep
<seconds>`` (R3/R4: used by
``tests/test_harness_offline.py::test_stop_cancels_running_child`` to keep a
real child alive long enough for `Harness.stop()` to have something to
signal and kill — the plain mode below exits the instant it emits its
terminal event, so nothing would be left to cancel). Reads and discards
stdin (the prompt), then emits a fixed stream-json event sequence ending in
a terminal ``result`` event, mimicking
``claude -p --output-format stream-json --verbose``.
"""
from __future__ import annotations

import json
import sys
import time

FAKE_VERSION = "0.0.1 (Claude Code)"


def main() -> int:
    argv = sys.argv[1:]

    if "--version" in argv:
        print(FAKE_VERSION)
        return 0

    # Drain stdin (the prompt) the same way the real CLI would.
    stdin_text = sys.stdin.read()

    session_id = "00000000-0000-4000-8000-000000000000"
    for i, token in enumerate(argv):
        if token in ("--session-id", "--resume") and i + 1 < len(argv):
            session_id = argv[i + 1]

    # Emitted first, same as the plain mode below, so a caller that lets a
    # --sleep run finish (instead of killing it) still gets a real init
    # event before the sleep — and, if never killed, the same terminal
    # event sequence afterwards.
    init_event = {"type": "system", "subtype": "init", "session_id": session_id}
    print(json.dumps(init_event), flush=True)

    # --ticks <n> / --tick-interval <s>: emit n assistant events, spaced
    # tick-interval apart, before the terminal event -- a run whose events
    # log visibly grows while it is alive (live-progress tests).
    if "--ticks" in argv:
        ticks = int(argv[argv.index("--ticks") + 1])
        interval = 0.3
        if "--tick-interval" in argv:
            interval = float(argv[argv.index("--tick-interval") + 1])
        for n in range(ticks):
            time.sleep(interval)
            print(
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {"content": [{"type": "text", "text": f"tick {n}"}]},
                    }
                ),
                flush=True,
            )

    # --tool-ticks <n>: emit n assistant events whose content is a `tool_use`
    # block (name "Bash"), spaced --tick-interval apart (default 0.3 s).
    if "--tool-ticks" in argv:
        tool_ticks = int(argv[argv.index("--tool-ticks") + 1])
        interval = 0.3
        if "--tick-interval" in argv:
            interval = float(argv[argv.index("--tick-interval") + 1])
        for n in range(tool_ticks):
            time.sleep(interval)
            print(
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "content": [
                                {
                                    "type": "tool_use",
                                    "id": f"toolu_{n}",
                                    "name": "Bash",
                                    "input": {"command": "ls"},
                                }
                            ]
                        },
                    }
                ),
                flush=True,
            )

    if "--sleep" in argv:
        idx = argv.index("--sleep")
        seconds = float(argv[idx + 1]) if idx + 1 < len(argv) else 5.0
        time.sleep(seconds)

    # --reply <text>: the final answer (default "OK").
    reply = "OK"
    if "--reply" in argv:
        reply = argv[argv.index("--reply") + 1]
    # --echo-stdin: reply with the drained stdin text verbatim, so a test can
    # observe what the child actually received as its user message.
    if "--echo-stdin" in argv:
        reply = stdin_text
    events = [
        {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": reply}]},
        },
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": reply,
            "session_id": session_id,
            "duration_ms": 42,
            "usage": {"input_tokens": 10, "output_tokens": 2},
            "total_cost_usd": 0.0001,
        },
    ]
    # --no-result: end without a terminal `result` event (a truncated
    # stream). --exit-code <n>: the process exit code (default 0).
    exit_code = 0
    if "--exit-code" in argv:
        exit_code = int(argv[argv.index("--exit-code") + 1])
    if "--no-result" in argv:
        return exit_code
    for event in events:
        print(json.dumps(event), flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
