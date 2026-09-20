#!/usr/bin/env python3
"""A dependency-free stdio MCP server for the live `.seretos/harness.yml`
tests (`tests/test_config_live.py`).

Speaks newline-delimited JSON-RPC 2.0 on stdin/stdout — `initialize`,
`notifications/initialized`, `tools/list`, `tools/call` — and exposes exactly
one uniquely-named tool, `fake_probe`. Registered under the server name
`fake`, the child sees it as `mcp__fake__fake_probe`; a child that has no
such tool cannot produce the reply `PROBE-<nonce>-OK`, so the assertion is
about reachability, never about the model's say-so.
"""
from __future__ import annotations

import json
import sys

PROTOCOL_VERSION = "2024-11-05"
TOOL = {
    "name": "fake_probe",
    "description": "Return PROBE-<nonce>-OK for the given nonce.",
    "inputSchema": {
        "type": "object",
        "properties": {"nonce": {"type": "string"}},
        "required": ["nonce"],
    },
}


def _reply(msg_id, result=None, error=None):
    payload = {"jsonrpc": "2.0", "id": msg_id}
    if error is not None:
        payload["error"] = error
    else:
        payload["result"] = result
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def handle(message: dict) -> None:
    method = message.get("method")
    msg_id = message.get("id")
    if method == "initialize":
        requested = (message.get("params") or {}).get("protocolVersion", PROTOCOL_VERSION)
        _reply(
            msg_id,
            {
                "protocolVersion": requested,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fake", "version": "0.0.1"},
            },
        )
    elif method == "tools/list":
        _reply(msg_id, {"tools": [TOOL]})
    elif method == "tools/call":
        args = (message.get("params") or {}).get("arguments") or {}
        _reply(
            msg_id,
            {"content": [{"type": "text", "text": f"PROBE-{args.get('nonce', '')}-OK"}]},
        )
    elif msg_id is not None:  # unknown request (notifications carry no id)
        _reply(msg_id, error={"code": -32601, "message": f"unknown method {method}"})


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if line:
            handle(json.loads(line))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
