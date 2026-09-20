"""`HostContext`: everything `resolve.resolve` needs about the parent
Claude Code session — cwd, model, permission mode, effort, MCP servers,
enabled plugins — completed from the CLI's own transcript and settings
files, needing no live call back into a running session.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .plugins import config_dir as _config_dir
from .plugins import enabled_plugins as _enabled_plugins


@dataclass
class HostContext:
    """A snapshot of the parent session. Fields already set before
    `complete()` runs are never overwritten — a caller may pre-fill
    anything it already knows (e.g. `mcp_servers`, which `complete()` never
    populates itself; see its docstring) and `complete()` only fills in the
    rest.
    """

    cwd: str | Path
    session_id: str | None = None
    model: str | None = None
    permission_mode: str | None = None
    effort: str | None = None
    mcp_servers: dict[str, Any] | None = None
    available_mcp_servers: dict[str, Any] | None = None
    dispatch_mcp_server_name: str | None = None
    enabled_plugins: dict[str, bool] = field(default_factory=dict)

    def complete(self) -> None:
        """Fill `model` (from the transcript's last assistant turn) and
        `enabled_plugins` (from the merged settings files) when unset.

        `mcp_servers` is deliberately never touched here: collecting the
        parent's actually-active MCP servers (`.mcp.json`, plugin
        manifests, ...) is out of this ticket's scope (its non-goal
        assigns collection to a later ticket) — `HostContext.mcp_servers`
        is caller-supplied only, all the way through.
        """
        cfg_dir = _config_dir()

        if self.model is None and self.session_id:
            self.model = _last_assistant_model(cfg_dir, self.session_id)

        if not self.enabled_plugins:
            self.enabled_plugins = _enabled_plugins(cfg_dir, Path(self.cwd))


def _last_assistant_model(config_dir: Path, session_id: str) -> str | None:
    """The last `type == "assistant"` line's `message.model` in
    `<config_dir>/projects/*/<session_id>.jsonl` — the same glob pattern
    `Harness._resolve_transcript_path` uses. A missing/empty transcript, or
    one whose trailing line is truncated mid-write, is not an error: it
    just yields `None` (or whatever the last *complete* line supplied).
    """
    matches = sorted(config_dir.glob(f"projects/*/{session_id}.jsonl"))
    if not matches:
        return None

    model: str | None = None
    for line in matches[0].read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "assistant":
            candidate = (event.get("message") or {}).get("model")
            if candidate:
                model = candidate
    return model
