"""The one `Provider` implementation this ticket ships: the real `claude` CLI.

Always spawns `-p --output-format stream-json --verbose`: stream-json is the
only mode that yields a partial events log (the cancel criterion needs it on
disk even for a run that gets stopped mid-flight), its terminal
`{"type": "result"}` event is the same object `--output-format json` would
have printed, and one parse path cannot drift from another. `--bare` is
never emitted — auth stays subscription/OAuth via `CLAUDE_CONFIG_DIR`, never
`ANTHROPIC_API_KEY`.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Iterable

from ..errors import UnsafeCwdError
from .base import LaunchPlan, RunResult, RunSpec

# Explicit, enumerable names this build scrubs from the child's environment —
# a fixed constant (not a runtime-derived pattern) so a test can plant each
# one with a nonce before building a plan and assert it is gone afterwards.
# `CLAUDE_CODE_*` variables are scrubbed too (see `_scrub_env` below), by
# prefix rather than by name, since the set of such variables is open-ended;
# `CLAUDE_CONFIG_DIR` deliberately does *not* match either rule and survives
# unchanged — it is what carries OAuth credentials and session transcripts
# (`claude --resume <id>` and subscription auth both depend on it).
SCRUBBED_ENV: tuple[str, ...] = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_MODEL",
)

_SCRUBBED_ENV_PREFIX = "CLAUDE_CODE_"

# The canonical `Isolation.CLEAN` flag/value subsequence, as a flat list of
# argv tokens (flag immediately followed by its fixed value, where it has
# one). This is the single source of truth the argv builder below consumes
# directly — and it is *not* what `tests/test_claude_cli_flags.py` asserts
# against: that test carries its own, independently written literal, because
# asserting argv against the same constant the builder consumed would be
# vacuous (plan Mechanism balance).
CLEAN_ARGV_FLAGS: tuple[str, ...] = (
    "--setting-sources", "",
    "--strict-mcp-config",
    "--disable-slash-commands",
    "--tools", "",
    "--output-format", "stream-json",
    "--verbose",
)


def _raises_if_git_ancestor(path: Path) -> None:
    resolved = path.resolve()
    for candidate in (resolved, *resolved.parents):
        if (candidate / ".git").exists():
            raise UnsafeCwdError(
                f"{path} is inside a git repository ({candidate}); "
                "Isolation.CLEAN requires an empty temp directory outside any repo"
            )


def _resolve_and_validate_cwd(spec: RunSpec) -> Path:
    if spec.cwd is None:
        # Fresh every call: this is the load-bearing half of the auto-memory
        # guarantee. A directory `claude` has never run in has no
        # `<config>/projects/<slug>/memory/` tree to load from — the
        # guarantee comes from the cwd being new, not from any flag.
        return Path(tempfile.mkdtemp(prefix="lib-python-harness-cwd-"))

    cwd = Path(spec.cwd)
    if not cwd.exists():
        raise UnsafeCwdError(f"{cwd} does not exist")
    if not cwd.is_dir():
        raise UnsafeCwdError(f"{cwd} is not a directory")

    _raises_if_git_ancestor(cwd)

    if any(cwd.iterdir()) and not spec.allow_nonempty_cwd:
        raise UnsafeCwdError(
            f"{cwd} is not empty; Isolation.CLEAN requires an empty cwd unless "
            "allow_nonempty_cwd=True is set (the single, provenance-recorded opt-out)"
        )
    return cwd


def _scrub_env() -> dict[str, str]:
    env = dict(os.environ)
    for name in SCRUBBED_ENV:
        env.pop(name, None)
    for name in list(env):
        if name.startswith(_SCRUBBED_ENV_PREFIX):
            env.pop(name, None)
    return env


class ClaudeCliProvider:
    """Builds and parses the `claude` CLI's clean-run command line."""

    def build_launch_plan(
        self, spec: RunSpec, *, session_id: str, run_dir: Path
    ) -> LaunchPlan:
        cwd = _resolve_and_validate_cwd(spec)

        argv: list[str] = ["-p", "--model", spec.model]
        if spec.effort:
            argv += ["--effort", spec.effort]

        argv += list(CLEAN_ARGV_FLAGS)

        argv += ["--system-prompt", spec.system_prompt or ""]
        argv += ["--session-id", session_id]

        if spec.json_schema is not None:
            argv += ["--json-schema", json.dumps(spec.json_schema)]

        env = _scrub_env()

        return LaunchPlan(argv=argv, cwd=str(cwd), env=env, stdin=spec.prompt)

    def parse_events(self, lines: Iterable[str]) -> RunResult:
        terminal: dict | None = None
        for line in lines:
            line = line.strip()
            if not line:
                continue
            event = json.loads(line)
            if event.get("type") == "result":
                terminal = event

        if terminal is None:
            raise ValueError(
                "stream-json output ended without a terminal 'result' event "
                "(truncated stream) — cannot be treated as a successful run"
            )

        return RunResult(
            text=terminal.get("result", ""),
            is_error=bool(terminal.get("is_error", False)),
            subtype=terminal.get("subtype"),
            structured_output=terminal.get("structured_output"),
            usage=terminal.get("usage") or {},
            cost=terminal.get("total_cost_usd"),
            session_id=terminal.get("session_id"),
        )
