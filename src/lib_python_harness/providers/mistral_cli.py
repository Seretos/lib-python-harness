"""`MistralCliProvider` — the Mistral Vibe CLI (`vibe -p --output streaming`).

`Isolation.CLEAN` recipe (measured against `vibe` 2.25.4): `-p --output
streaming --enabled-tools <no-match>`; the prompt travels on stdin. In `-p`
mode `--enabled-tools NAME` disables every other tool, so a name that matches
nothing is the tool/MCP kill switch. `vibe` has no `--model` flag: the model
alias travels as `VIBE_ACTIVE_MODEL`. The child gets a fresh empty
`VIBE_HOME` (config, AGENTS.md, skills, MCP servers, ... all live there), every
inherited `VIBE_*` variable is dropped, and account-side connectors are
switched off with `VIBE_ENABLE_CONNECTORS=false`. `MISTRAL_API_KEY` is
preserved: auth is the env var or the OS keyring, both outside `VIBE_HOME`,
so no credential is copied. `--trust` is deliberately omitted (an untrusted
workdir makes Vibe ignore project config).

`--output streaming` emits one JSON object (a camelCase history entry) per
line; assistant text lives in `content[].text` of `type == "message"`,
`role == "assistant"` entries. The stream has no terminal turn event and
carries no token/cost totals.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable

from ..errors import UnsupportedByProvider
from .base import Isolation, LaunchPlan, RunResult, RunSpec
from .isolation import _resolve_clean_cwd, scrub_env

# Matches no real tool name, so `--enabled-tools` with it disables them all.
_NO_TOOLS_SENTINEL = "__harness_no_tools__"

MISTRAL_CLEAN_ARGV_FLAGS: tuple[str, ...] = (
    "-p",
    "--output", "streaming",
    "--enabled-tools", _NO_TOOLS_SENTINEL,
)

# RunSpec fields this provider cannot honour (`max_turns` is honoured;
# `description` is silently ignored, as for codex).
_UNSUPPORTED_FIELDS: tuple[str, ...] = (
    "permission_mode",
    "tools",
    "disallowed_tools",
    "skills",
    "hooks",
    "mcp_servers",
    "omit_claude_md",
    "agent_name",
    "setting_sources",
    "strict_mcp",
    "session_tools",
    "memory",
    "system_prompt",
    "effort",
    "json_schema",
)


def _make_vibe_home() -> Path:
    home = Path(tempfile.mkdtemp(prefix="lib-python-harness-vibe-home-"))
    try:
        os.chmod(home, 0o700)
    except OSError:
        pass
    return home


class MistralCliProvider:
    """Builds and parses the `vibe` CLI's command line (CLEAN only)."""

    name = "mistral"
    binary_argv = ["vibe"]

    def build_launch_plan(
        self, spec: RunSpec, *, session_id: str, run_dir: Path
    ) -> LaunchPlan:
        offending = [
            field for field in _UNSUPPORTED_FIELDS if getattr(spec, field, None) is not None
        ]
        if spec.isolation is not Isolation.CLEAN:
            offending.append("isolation")
        if offending:
            raise UnsupportedByProvider(
                "the mistral provider cannot honour: "
                + ", ".join(offending)
                + " (Isolation.CLEAN only; Claude-specific fields are unsupported)"
            )

        cwd = _resolve_clean_cwd(spec)

        argv: list[str] = list(MISTRAL_CLEAN_ARGV_FLAGS)
        if spec.max_turns is not None:
            argv += ["--max-turns", str(spec.max_turns)]

        env = scrub_env((), prefixes=("VIBE_",))
        home = _make_vibe_home()
        env["VIBE_HOME"] = str(home)
        env["VIBE_ACTIVE_MODEL"] = spec.model
        env["VIBE_ENABLE_CONNECTORS"] = "false"
        return LaunchPlan(
            argv=argv,
            cwd=str(cwd),
            env=env,
            stdin=spec.prompt,
            cleanup_paths=(str(home),),
        )

    def parse_events(self, lines: Iterable[str]) -> RunResult:
        session_id: str | None = None
        text: str | None = None

        for line in lines:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            if not isinstance(entry, dict):
                continue
            if session_id is None and entry.get("sessionId"):
                session_id = entry["sessionId"]
            if entry.get("generationStatus", "completed") != "completed":
                continue
            if entry.get("type") == "message" and entry.get("role") == "assistant":
                blocks: list[Any] = entry.get("content") or []
                text = "".join(
                    b.get("text", "")
                    for b in blocks
                    if isinstance(b, dict) and b.get("type", "text") == "text"
                )

        if text is None:
            raise ValueError(
                "mistral event stream ended without a completed assistant "
                "message (truncated stream) — cannot be treated as a "
                "successful run"
            )

        return RunResult(
            text=text,
            is_error=False,
            subtype=None,
            structured_output=None,
            usage={},
            cost=None,
            session_id=session_id,
        )
