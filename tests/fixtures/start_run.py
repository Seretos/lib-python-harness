#!/usr/bin/env python3
"""Starter process for the cross-process observation tests.

``start_run.py <artifacts_dir> [--label L] [--prompt P] [--stop-after S]
[-- <fake_claude args>...]`` builds a ``Harness(FileRunStore(dir))`` whose
binary is ``fake_claude.py`` (extra args after ``--`` go to it), ``start()``s
one run, prints ``{"run_id": ...}`` on one line and exits -- leaving the
detached child running. With ``--stop-after S`` it sleeps S seconds and
``stop()``s the run before exiting. Imports ``lib_python_harness`` from
whatever ``PYTHONPATH`` the test hands it.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from lib_python_harness import FileRunStore, Harness, Isolation, RunSpec

FAKE_CLAUDE = Path(__file__).parent / "fake_claude.py"


def main() -> int:
    argv = sys.argv[1:]
    fake_args: list[str] = []
    if "--" in argv:
        i = argv.index("--")
        fake_args = argv[i + 1 :]
        argv = argv[:i]

    artifacts = argv[0]
    label = argv[argv.index("--label") + 1] if "--label" in argv else None
    prompt = argv[argv.index("--prompt") + 1] if "--prompt" in argv else "Reply with exactly OK"
    stop_after = float(argv[argv.index("--stop-after") + 1]) if "--stop-after" in argv else None

    harness = Harness(
        store=FileRunStore(artifacts),
        claude_argv=[sys.executable, str(FAKE_CLAUDE), *fake_args],
    )
    spec = RunSpec(
        prompt=prompt,
        isolation=Isolation.CLEAN,
        model="haiku",
        artifacts_dir=artifacts,
        label=label,
    )
    result = harness.start(spec)
    print(json.dumps({"run_id": result.run_id}), flush=True)
    if "--wait" in argv:
        # The starter waits itself (same Harness, Popen held) and reports the
        # final text/usage on a second line.
        final = harness.wait(result.run_id)
        print(
            json.dumps({"state": final.state.name, "text": final.text, "usage": final.usage}),
            flush=True,
        )
    if stop_after is not None:
        time.sleep(stop_after)
        harness.stop(result.run_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
