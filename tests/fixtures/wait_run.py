#!/usr/bin/env python3
"""Second-process waiter for the cross-process wait tests.

``wait_run.py <artifacts_dir> <run_id> [--timeout S]`` builds a fresh
``Harness(FileRunStore(dir))`` (no access to any ``Popen`` map), calls
``wait(run_id[, timeout=S])`` and prints one JSON line with the result
(``state``, ``text``, ``usage``, ``timed_out``, ``elapsed``). Imports
``lib_python_harness`` from whatever ``PYTHONPATH`` the test hands it.
"""
from __future__ import annotations

import json
import sys
import time

from lib_python_harness import FileRunStore, Harness


def main() -> int:
    argv = sys.argv[1:]
    artifacts, run_id = argv[0], argv[1]
    timeout = float(argv[argv.index("--timeout") + 1]) if "--timeout" in argv else None

    harness = Harness(store=FileRunStore(artifacts))
    began = time.monotonic()
    result = harness.wait(run_id, timeout=timeout)
    print(
        json.dumps(
            {
                "state": result.state.name,
                "text": result.text,
                "usage": result.usage,
                "timed_out": result.timed_out,
                "elapsed": time.monotonic() - began,
            }
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
