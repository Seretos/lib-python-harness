#!/usr/bin/env python3
"""Offline stand-in for the real `codex` binary.

Replays the recorded real stream `codex_events_sample.jsonl` (captured from
codex-cli on native Windows, see .adev/4-1/codex-survey.md) — nothing here is an
invented event shape. Answers `--version` the way the real CLI does
(`codex-cli 0.154.0`), drains stdin (the prompt), and with `--sleep <s>` emits
the first recorded event (`thread.started`) and then stays alive so
`Harness.stop()` has a real child to cancel.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

FAKE_VERSION = "codex-cli 0.154.0"
SAMPLE = Path(__file__).parent / "codex_events_sample.jsonl"


def main() -> int:
    argv = sys.argv[1:]
    if "--version" in argv:
        print(FAKE_VERSION)
        return 0

    sys.stdin.read()

    lines = [ln for ln in SAMPLE.read_text(encoding="utf-8").splitlines() if ln.strip()]
    print(lines[0], flush=True)  # thread.started

    if "--sleep" in argv:
        idx = argv.index("--sleep")
        seconds = float(argv[idx + 1]) if idx + 1 < len(argv) else 5.0
        time.sleep(seconds)

    for line in lines[1:]:
        print(line, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
