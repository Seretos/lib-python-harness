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
simulates it: setting `skills=[...]` on the `RunSpec` directly forces
`dispatch_mode` to choose `materialized` once it exists (`skills` is not in
the verified `AGENT_JSON_KEYS` set per the plan's step 0), without needing a
real `AgentDefinition`.
"""
from __future__ import annotations

import uuid

import pytest

from lib_python_harness import Harness, Isolation, RunSpec

pytestmark = pytest.mark.requires_claude

STIMULUS = (
    "Reply with exactly two lines. Line 1: the value of the environment "
    "variable HARNESS_CANARY, or NOCANARY if unset. Line 2: the exact first "
    "line of CLAUDE.md in your current working directory, or NOCLAUDEMD if "
    "you have no such file or it was not loaded."
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
            # exists: "skills" is outside the verified AGENT_JSON_KEYS set.
            skills=["reviewer-skill"],
            agent_name="inherit-live-probe",
        )
    )

    assert canary in result.text
    assert claude_md_line in result.text
