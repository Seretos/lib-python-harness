"""R4 — `HostContext.complete()` needs no live session.

Tests `lib_python_harness.host.context.HostContext`.

Assumptions (documented): `complete()` locates the transcript by globbing
`<config_dir>/projects/*/<session_id>.jsonl` — the same pattern
`Harness._resolve_transcript_path` already uses (`harness.py:283-287`) — and
reads `enabled_plugins` via `host.plugins.enabled_plugins(config_dir,
self.cwd)`. `config_dir` is read from the `CLAUDE_CONFIG_DIR` env var
(monkeypatched in these tests), consistent with `host.plugins.config_dir()`.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from lib_python_harness.host.context import HostContext

FIXTURE = Path(__file__).parent / "fixtures" / "transcript_model.jsonl"
SESSION_ID = "00000000-0000-4000-8000-000000000001"


def _plant_transcript(config_dir: Path, session_id: str = SESSION_ID, fixture: Path = FIXTURE):
    project_slug_dir = config_dir / "projects" / "some-project-slug"
    project_slug_dir.mkdir(parents=True, exist_ok=True)
    dest = project_slug_dir / f"{session_id}.jsonl"
    shutil.copy(fixture, dest)
    return dest


def _settings(config_dir: Path, enabled: dict):
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "settings.json").write_text(json.dumps({"enabledPlugins": enabled}))


def test_complete_fills_model_and_enabled_plugins_from_fixtures(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    _settings(config_dir, {"demo@mkt": True})
    _plant_transcript(config_dir)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config_dir))

    context = HostContext(cwd=project_dir, session_id=SESSION_ID)
    context.complete()

    # last type=="assistant" line's message.model, not the first.
    assert context.model == "claude-opus-4-1-20250805"
    assert context.enabled_plugins.get("demo@mkt") is True


def test_complete_does_not_overwrite_already_set_fields(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    _settings(config_dir, {"demo@mkt": True})
    _plant_transcript(config_dir)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config_dir))

    context = HostContext(cwd=project_dir, session_id=SESSION_ID, model="already-set-model")
    context.complete()

    assert context.model == "already-set-model"


def test_complete_with_missing_transcript_leaves_model_none(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    _settings(config_dir, {})
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config_dir))

    context = HostContext(cwd=project_dir, session_id="no-such-session-id")
    context.complete()

    assert context.model is None


def test_complete_with_empty_transcript_leaves_model_none(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    _settings(config_dir, {})
    project_slug_dir = config_dir / "projects" / "empty-slug"
    project_slug_dir.mkdir(parents=True)
    (project_slug_dir / "empty-session.jsonl").write_text("")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config_dir))

    context = HostContext(cwd=project_dir, session_id="empty-session")
    context.complete()

    assert context.model is None


def test_complete_skips_trailing_partial_line_instead_of_raising(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    _settings(config_dir, {})
    project_slug_dir = config_dir / "projects" / "partial-slug"
    project_slug_dir.mkdir(parents=True)
    session_id = "partial-session"
    lines = [
        json.dumps(
            {
                "type": "assistant",
                "message": {"model": "claude-sonnet-4-5-20250929", "content": []},
            }
        ),
        '{"type": "assistant", "message": {"model": "claude-opus-tru',  # truncated
    ]
    (project_slug_dir / f"{session_id}.jsonl").write_text("\n".join(lines))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config_dir))

    context = HostContext(cwd=project_dir, session_id=session_id)
    context.complete()  # must not raise

    assert context.model == "claude-sonnet-4-5-20250929"


def test_complete_never_populates_mcp_servers(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    _settings(config_dir, {})
    _plant_transcript(config_dir)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config_dir))

    # test-critic round 1, tautology::F4: without a real .mcp.json for an
    # implementation to (wrongly) read from, "complete() never populates
    # mcp_servers" is indistinguishable from "complete() merges whatever
    # .mcp.json has, and there just isn't one here" — both pass the
    # assertions below. Planting a real .mcp.json with content an
    # over-eager complete() could pick up closes that gap.
    (project_dir / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"leaked": {"command": "should-not-be-read"}}})
    )

    supplied = {"demo": {"command": "demo-server"}}
    context = HostContext(cwd=project_dir, session_id=SESSION_ID, mcp_servers=supplied)
    context.complete()

    assert context.mcp_servers == supplied

    context_unset = HostContext(cwd=project_dir, session_id=SESSION_ID)
    context_unset.complete()
    assert not context_unset.mcp_servers
