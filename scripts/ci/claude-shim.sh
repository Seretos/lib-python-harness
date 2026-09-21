#!/usr/bin/env bash
# CI-only `claude` shim. The library scrubs CLAUDE_CODE_* from every child by
# design, so the headless OAuth token is re-injected here, inside the child,
# instead of weakening the scrub. It adds one variable and execs the real
# binary: no argv rewrite, no flag injection, no cwd or stdio change.
#
# HARNESS_CI_CLAUDE_REAL_BIN     absolute path of the real claude (captured
#                                before this shim dir joined PATH)
# HARNESS_CI_CLAUDE_OAUTH_TOKEN  token to expose as CLAUDE_CODE_OAUTH_TOKEN
set -u

real="${HARNESS_CI_CLAUDE_REAL_BIN:-}"
if [ -z "$real" ]; then
  echo "claude-shim: HARNESS_CI_CLAUDE_REAL_BIN is not set" >&2
  exit 127
fi
if [ ! -f "$real" ] || [ ! -x "$real" ]; then
  echo "claude-shim: real claude is not an executable file: $real" >&2
  exit 127
fi
self="$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null || echo "${BASH_SOURCE[0]}")"
if [ "$(readlink -f "$real" 2>/dev/null || echo "$real")" = "$self" ]; then
  echo "claude-shim: real claude resolves to the shim itself (recursion): $real" >&2
  exit 127
fi

if [ -n "${HARNESS_CI_CLAUDE_OAUTH_TOKEN:-}" ]; then
  export CLAUDE_CODE_OAUTH_TOKEN="$HARNESS_CI_CLAUDE_OAUTH_TOKEN"
fi
exec "$real" "$@"
