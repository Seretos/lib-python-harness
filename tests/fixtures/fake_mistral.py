#!/usr/bin/env python3
"""Offline stand-in for the real `vibe` binary.

Replays the recorded real stream `mistral_events_sample.jsonl` (captured from
`vibe -p --output streaming` 2.25.4 on native Windows) — nothing here is an
invented event shape. Answers `--version` the way the real CLI is expected to
(`vibe 2.25.4`), drains stdin (the prompt), and:

- `--sleep <s>`: emits the first recorded entry, then stays alive so
  `Harness.stop()` has a real child to cancel;
- `--reply-non-ascii`: rewrites the assistant reply to non-ASCII text and
  writes the stream as raw UTF-8 with `ensure_ascii=False`, as Vibe does;
- `--truncate-mid-codepoint`: cuts the last line in the middle of a multi-byte
  UTF-8 sequence (a killed child).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

FAKE_VERSION = "vibe 2.25.4"
SAMPLE = Path(__file__).parent / "mistral_events_sample.jsonl"
NON_ASCII_REPLY = "Gr\u00fc\u00dfe \u2014 \u65e5\u672c\u8a9e \u2713 \u00e9\u00e8"


def _emit(data: bytes) -> None:
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def main() -> int:
    argv = sys.argv[1:]
    if "--version" in argv:
        print(FAKE_VERSION)
        return 0

    sys.stdin.read()

    lines = [ln for ln in SAMPLE.read_text(encoding="utf-8").splitlines() if ln.strip()]
    _emit((lines[0] + "\n").encode("utf-8"))

    if "--sleep" in argv:
        idx = argv.index("--sleep")
        seconds = float(argv[idx + 1]) if idx + 1 < len(argv) else 5.0
        time.sleep(seconds)

    rest = lines[1:]
    if "--reply-non-ascii" in argv or "--truncate-mid-codepoint" in argv:
        out = []
        for ln in rest:
            entry = json.loads(ln)
            if entry.get("type") == "message" and entry.get("role") == "assistant":
                entry["content"] = [{"type": "text", "text": NON_ASCII_REPLY}]
            out.append(json.dumps(entry, ensure_ascii=False))
        rest = out

    for i, ln in enumerate(rest):
        data = (ln + "\n").encode("utf-8")
        if "--truncate-mid-codepoint" in argv and i == len(rest) - 1:
            cut = data.index("\u00fc".encode("utf-8")) + 1  # between the two bytes of "\u00fc"
            _emit(data[:cut])
            return 0
        _emit(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
