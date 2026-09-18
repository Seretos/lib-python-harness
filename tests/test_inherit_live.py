"""R5 — the child really inherits cwd, env and CLAUDE.md, by both dispatch
paths (the ticket's own symptom).

requires_claude: needs the installed `claude` CLI + subscription auth.
Excluded from the default `python -m pytest` run; run explicitly with
`python -m pytest -m requires_claude -k inherit -q` (this file's own
substitute-execution command, per the plan).

Bypasses `resolve()`/`AgentDefinition` entirely (neither exists yet, and
neither is this test's subject) and drives `Harness.run(RunSpec(isolation=
Isolation.INHERIT, ...))` directly — the same minimal-dependency approach
`tests/test_resolve_inherit.py` uses, so this file's RED does not depend on
any other new module. `Isolation.INHERIT` does not exist yet (added in
phase=implement), so every arm below fails with `AttributeError: INHERIT`
while constructing its `RunSpec` — before any subprocess is ever spawned:
"the run fails to spawn", the plan's stated RED reason, with no live CLI
call and no auth required to observe it.

Arm 3 (materialized-path) is simulated the same way `test_resolve_inherit.py`
simulates it: setting a field outside `AGENT_JSON_KEYS` on the `RunSpec`
directly forces `dispatch_mode` to choose `materialized` once it exists,
without needing a real `AgentDefinition`.

phase=implement update (step 0's live probe against installed `claude`
v2.1.277): `skills` is, in fact, accepted by the `--agents` JSON schema —
the opposite of what this module originally assumed before that probe ran.
The verified-rejected keys are `hooks` and `mcpServers` (both produce
"Invalid --agents configuration" errors; `tools`/`disallowedTools` are
accepted but only as a JSON array, not the comma-separated scalar
`RunSpec.tools` carries). Arm 3 below uses `mcp_servers=...` — genuinely
outside `AGENT_JSON_KEYS` — instead of the originally-planned `skills=...`,
which `AGENT_JSON_KEYS` now legitimately accepts and would dispatch as
`payload`, defeating this arm's whole purpose of exercising the
materialized carrier.

A second, separate live finding from the same probe round: a *non-empty*
`hooks:` field in a materialized agent `.md` file's on-disk frontmatter
(not just the `--agents` JSON payload) makes the real CLI's own agent
loader silently drop the file from discovery (`--agent <stem> not found`,
reproduced with a plain string value and with a nested mapping alike; an
*empty* `hooks: {}` does not trigger it, nor does an arbitrary unknown key,
nor a non-empty `mcpServers:`). That is a narrower, still-open question
about the real hooks schema Claude Code's own agent loader expects on
disk — orthogonal to what this arm exists to prove (that the materialized
carrier reaches the child at all) — so `mcp_servers`, confirmed to
round-trip through the on-disk loader successfully, is what forces the
materialized path here instead.

Round 2 fix: the original stimulus asked the model to "report" the env var
without granting any tool or a non-interactive permission mode — env vars
are not part of the model's automatic context the way cwd/git status are,
so nothing ever actually checked `HARNESS_CANARY`; the CLAUDE.md half of
the assertion worked because that *is* automatic context. Two changes fix
it: (1) the stimulus now explicitly instructs the model to invoke the Bash
tool to check the variable; (2) every arm sets `permission_mode=
"bypassPermissions"` so a one-shot, non-interactive `-p` run does not stall
on an approval prompt nobody can answer. Arm 3 additionally sets
`tools="Bash"` on the `RunSpec`, since that is the one arm with a real
agent scope (the materialized `--agent inherit-live-probe` file) for the
field to land in via `materialize_agent_dir`'s `tools:` frontmatter key;
arms 1/2 have no `agent_name` at all (no `--agents`/materialized carrier is
built — see `_build_inherit_plan`), so `RunSpec.tools` would be a pure
no-op there (never emitted as a top-level `--allowedTools`, by design —
`test_tools_and_disallowed_tools_never_become_top_level_argv_flags`): the
top-level session's own default tool access, combined with
`bypassPermissions`, is what carries Bash to the child in those two arms.
"""
from __future__ import annotations

import uuid

import pytest

from lib_python_harness import Harness, Isolation, RunSpec

pytestmark = pytest.mark.requires_claude

STIMULUS = (
    "Reply with exactly two lines, built as follows.\n"
    "Line 1: use the Bash tool to run: echo \"$HARNESS_CANARY\" -- do not "
    "answer from memory or context, actually invoke the tool -- and report "
    "its exact output, or NOCANARY if it was empty.\n"
    "Line 2: the exact first line of CLAUDE.md, ONLY if that content is "
    "already visible to you automatically (e.g. it was loaded into your "
    "context/system prompt at session start). Do NOT use any tool (Bash, "
    "Read, cat, grep, ls, or otherwise) to open, read, or search for a "
    "CLAUDE.md file to answer this line -- this line tests only what "
    "reached you automatically, not what you could look up. If no CLAUDE.md "
    "content is already visible to you without looking it up, reply "
    "NOCLAUDEMD."
)


def _repo_with_claude_md(tmp_path, claude_md_first_line: str):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / "CLAUDE.md").write_text(f"{claude_md_first_line}\n")
    return repo


def test_inherit_with_claude_md_reaches_child(tmp_path, monkeypatch):
    canary = f"CANARY-{uuid.uuid4().hex}"
    monkeypatch.setenv("HARNESS_CANARY", canary)
    claude_md_line = f"CLAUDE-MD-MARKER-{uuid.uuid4().hex}"
    repo = _repo_with_claude_md(tmp_path, claude_md_line)

    harness = Harness()
    result = harness.run(
        RunSpec(
            prompt=STIMULUS,
            isolation=Isolation.INHERIT,
            model="haiku",
            cwd=repo,
            allow_nonempty_cwd=True,
            # bypassPermissions: this is a one-shot, non-interactive -p run
            # with no TTY to answer a tool-approval prompt — without it the
            # Bash call the stimulus asks for either stalls or gets silently
            # denied, and the model never actually checks HARNESS_CANARY.
            permission_mode="bypassPermissions",
        )
    )

    assert canary in result.text
    assert claude_md_line in result.text


def test_inherit_with_omit_claude_md_true_returns_only_canary(tmp_path, monkeypatch):
    canary = f"CANARY-{uuid.uuid4().hex}"
    monkeypatch.setenv("HARNESS_CANARY", canary)
    claude_md_line = f"CLAUDE-MD-MARKER-{uuid.uuid4().hex}"
    repo = _repo_with_claude_md(tmp_path, claude_md_line)

    harness = Harness()
    result = harness.run(
        RunSpec(
            prompt=STIMULUS,
            isolation=Isolation.INHERIT,
            model="haiku",
            cwd=repo,
            allow_nonempty_cwd=True,
            omit_claude_md=True,
            permission_mode="bypassPermissions",
        )
    )

    assert canary in result.text
    assert claude_md_line not in result.text


def test_inherit_materialized_mode_still_reaches_child(tmp_path, monkeypatch):
    canary = f"CANARY-{uuid.uuid4().hex}"
    monkeypatch.setenv("HARNESS_CANARY", canary)
    claude_md_line = f"CLAUDE-MD-MARKER-{uuid.uuid4().hex}"
    repo = _repo_with_claude_md(tmp_path, claude_md_line)

    harness = Harness()
    result = harness.run(
        RunSpec(
            prompt=STIMULUS,
            isolation=Isolation.INHERIT,
            model="haiku",
            cwd=repo,
            allow_nonempty_cwd=True,
            # Forces the materialized dispatch path once dispatch_mode()
            # exists: "mcpServers" is verified outside AGENT_JSON_KEYS (the
            # --agents JSON schema rejects it), unlike "skills" (accepted —
            # see module docstring). Not "hooks": see the module docstring's
            # second finding — a non-empty on-disk hooks: field is a
            # separate, still-open schema question this arm does not exist
            # to settle. `command` must name a real, resolvable binary
            # ("echo") — the real CLI validates MCP server configs eagerly
            # (before agent selection even runs) and rejects a command it
            # cannot resolve with "Invalid MCP configuration", a third live
            # finding from the same probe round.
            mcp_servers={"demo": {"command": "echo"}},
            agent_name="inherit-live-probe",
            # This arm has a real agent scope (the materialized
            # --agent inherit-live-probe file), so tools= actually lands in
            # that file's `tools:` frontmatter key via materialize_agent_dir
            # — unlike arms 1/2, which have no agent_name and so no carrier
            # for RunSpec.tools at all (see module docstring, round 2 fix).
            tools="Bash",
            permission_mode="bypassPermissions",
        )
    )

    assert canary in result.text
    assert claude_md_line in result.text
