"""`CodexCliProvider` — the OpenAI `codex` CLI (`codex exec --json`).

`Isolation.CLEAN` recipe (flag set confirmed live, see the ticket and
`codex exec --help`): `exec --json --ephemeral --ignore-user-config
--ignore-rules --skip-git-repo-check -s read-only -c project_doc_max_bytes=0`
(the last pair closes the cwd `AGENTS.md` channel, which the other flags leave
open; measured live). `codex exec` has no
approval flag (its policy is effectively "never"), so none belongs here.
The prompt travels on stdin. `CODEX_HOME` is deliberately preserved — it
carries auth; the *config* inside it is neutralised by the flags. `OPENAI_*`
credentials are scrubbed, mirroring the Claude provider's `ANTHROPIC_*`.

A `--ephemeral` run's `thread_id` is reported as `session_id` but is **not**
resumable (`codex exec resume` fails with "no rollout found").

`parse_events` has no `spec` parameter, so whether a JSON schema was
requested is remembered on the instance by `build_launch_plan`: use one
provider instance per run (`Harness` does).
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Iterable

from ..errors import UnsupportedByProvider
from .base import Isolation, LaunchPlan, RunResult, RunSpec
from .isolation import _resolve_clean_cwd, scrub_env

CODEX_CLEAN_ARGV_FLAGS: tuple[str, ...] = (
    "exec",
    "--json",
    "--ephemeral",
    "--ignore-user-config",
    "--ignore-rules",
    "--skip-git-repo-check",
    "-s", "read-only",
    # Disables project-doc (cwd AGENTS.md) loading: --ignore-user-config /
    # --ignore-rules do not, measured live (ticket #4 survey addendum).
    "-c", "project_doc_max_bytes=0",
)

CODEX_SCRUBBED_ENV: tuple[str, ...] = (
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_ORGANIZATION",
)

# RunSpec fields this provider cannot honour. `description` is deliberately
# absent: it is silently unsupported (documented in the README), not an error.
_UNSUPPORTED_FIELDS: tuple[str, ...] = (
    "permission_mode",
    "tools",
    "disallowed_tools",
    "skills",
    "max_turns",
    "hooks",
    "mcp_servers",
    "omit_claude_md",
    "agent_name",
    "setting_sources",
    "strict_mcp",
    "session_tools",
    "memory",
    "system_prompt",
)


def _real_codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


def make_scrubbed_codex_home() -> Path:
    """A fresh private dir containing only `auth.json` (copied from the
    caller's real codex home if present). API-key-only setups (no auth.json)
    get an empty home; auth then relies on whatever env the child inherits."""
    home = Path(tempfile.mkdtemp(prefix="lib-python-harness-codex-home-"))
    try:
        os.chmod(home, 0o700)
    except OSError:
        pass
    auth = _real_codex_home() / "auth.json"
    try:
        if auth.is_file():
            dest = home / "auth.json"
            shutil.copyfile(auth, dest)
            try:
                os.chmod(dest, 0o600)
            except OSError:
                pass
    except BaseException:
        shutil.rmtree(home, ignore_errors=True)
        raise
    return home


class CodexCliProvider:
    """Builds and parses the `codex` CLI's command line (CLEAN only)."""

    name = "codex"
    binary_argv = ["codex"]

    def __init__(self) -> None:
        self._schema_requested = False

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
                "the codex provider cannot honour: "
                + ", ".join(offending)
                + " (Isolation.CLEAN only; Claude-specific fields are unsupported)"
            )

        cwd = _resolve_clean_cwd(spec)

        argv: list[str] = list(CODEX_CLEAN_ARGV_FLAGS) + ["-m", spec.model]
        if spec.effort:
            argv += ["-c", f"model_reasoning_effort={json.dumps(spec.effort)}"]

        self._schema_requested = spec.json_schema is not None
        if spec.json_schema is not None:
            run_dir = Path(run_dir)
            run_dir.mkdir(parents=True, exist_ok=True)
            schema_path = run_dir / "output-schema.json"
            schema_path.write_text(json.dumps(spec.json_schema), encoding="utf-8")
            argv += ["--output-schema", str(schema_path)]

        env = scrub_env(CODEX_SCRUBBED_ENV)
        home = make_scrubbed_codex_home()
        env["CODEX_HOME"] = str(home)
        return LaunchPlan(
            argv=argv,
            cwd=str(cwd),
            env=env,
            stdin=spec.prompt,
            cleanup_paths=(str(home),),
        )

    def parse_events(self, lines: Iterable[str]) -> RunResult:
        session_id: str | None = None
        text = ""
        usage: dict[str, Any] = {}
        terminal: str | None = None

        for line in lines:
            line = line.strip()
            if not line:
                continue
            event = json.loads(line)
            etype = event.get("type")
            if etype == "thread.started":
                session_id = event.get("thread_id")
            elif etype == "item.completed":
                item = event.get("item") or {}
                if item.get("type") == "agent_message":
                    text = item.get("text", "")
            elif etype == "turn.completed":
                terminal = "turn.completed"
                usage = event.get("usage") or {}
            elif etype == "turn.failed":
                terminal = "turn.failed"

        if terminal is None:
            raise ValueError(
                "codex event stream ended without a terminal 'turn.completed'/"
                "'turn.failed' event (truncated stream) — cannot be treated as "
                "a successful run"
            )

        failed = terminal == "turn.failed"
        structured: Any | None = None
        if self._schema_requested and not failed:
            try:
                structured = json.loads(text)
            except ValueError:
                structured = None

        return RunResult(
            text=text,
            is_error=failed,
            subtype="turn.failed" if failed else None,
            structured_output=structured,
            usage=usage,
            cost=None,
            session_id=session_id,
        )
