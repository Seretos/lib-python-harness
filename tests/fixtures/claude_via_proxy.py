"""R0 test-only substitute for the `claude` binary itself (ticket #41).

Passed to `Harness(claude_argv=[sys.executable, __file__])` so a live probe
run's outbound HTTPS traffic can be pointed at
`tests/fixtures/capture_proxy.py`'s local forwarding proxy without
`Harness`/`RunSpec` growing a new "capture" concept of their own — the
harness still spawns `[sys.executable, claude_via_proxy.py] + <the same
argv it would have given the real binary>` and this process re-execs the
real `claude`, unchanged in every other respect (same argv, same cwd, same
stdin/stdout/stderr — inherited, never redirected, so the harness's own
`--output-format stream-json` capture to `events.jsonl` still works
transparently).

Reads the proxy's base URL from `LIB_PYTHON_HARNESS_R0_PROXY_URL` — a name
outside `providers.claude_cli.SCRUBBED_ENV` and its `CLAUDE_CODE_*` prefix,
so it survives `_scrub_env()` and actually reaches this process even though
`ANTHROPIC_BASE_URL` itself does not (`_scrub_env` strips that on every
run, including this one — this wrapper is what puts it back, deliberately,
only for this test-only substitute binary). A missing env var fails loudly
rather than silently talking straight to the real Anthropic API: that would
fabricate a passing run with no capture behind it.
"""
from __future__ import annotations

import os
import subprocess
import sys

_PROXY_URL_VAR = "LIB_PYTHON_HARNESS_R0_PROXY_URL"


def main(argv: list[str]) -> int:
    proxy_url = os.environ.get(_PROXY_URL_VAR)
    if not proxy_url:
        print(
            f"claude_via_proxy.py: {_PROXY_URL_VAR} is not set; refusing to "
            "silently bypass the capture proxy",
            file=sys.stderr,
        )
        return 1
    env = dict(os.environ)
    env["ANTHROPIC_BASE_URL"] = proxy_url
    completed = subprocess.run(["claude", *argv], env=env)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
