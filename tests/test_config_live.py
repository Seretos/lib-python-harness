"""R9 — the ticket's symptom, against the real CLI: a project cannot retune a
plugin-shipped subagent without forking the plugin.

requires_claude: needs the installed `claude` CLI plus subscription auth.
Excluded from the default run; run with
`python -m pytest -m requires_claude -k config -q` (add `-s` to see replies).

Each arm writes a real `.seretos/harness.yml`, loads it with
`load_harness_config`, resolves a definition with it, and dispatches through
`Harness().run(...)`. The negatives are only meaningful because a control run
(no config) proves the very same setup CAN reach the tool.

`tests/fixtures/fake_mcp_server.py` is the real MCP server (also the
stand-in for the dispatch server). Its tool `fake_probe`, served as
`mcp__fake__fake_probe`, returns `PROBE-<nonce>-OK` — a nonce per stimulus,
so the reply can only come from a real tool call.

Before the implementation exists, every arm fails at `resolve(..., config=)`
(`TypeError`) before any subprocess is spawned.
"""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import pytest

from lib_python_harness import Harness, resolve
from lib_python_harness.config import load_harness_config

from ._config_support import definition, host, make_repo

pytestmark = pytest.mark.requires_claude

FAKE_SERVER = {
    "command": sys.executable,
    "args": [str(Path(__file__).parent / "fixtures" / "fake_mcp_server.py")],
}


def _probe_body(nonce: str) -> str:
    return (
        f"Call the tool named mcp__fake__fake_probe with the argument nonce={nonce} "
        "and reply with its exact output and nothing else. Do not guess or "
        "answer from memory; actually invoke the tool. If you have no tool with "
        "that name, reply with exactly NOTOOL."
    )


def _run(repo, yml, defn, ctx):
    if yml is not None:
        (repo / ".seretos").mkdir(exist_ok=True)
        (repo / ".seretos" / "harness.yml").write_text(yml, encoding="utf-8")
    cfg = load_harness_config(repo, home_default=False) if yml is not None else None
    spec = resolve(defn, ctx, config=cfg)
    result = Harness().run(spec)
    print(f"\n--- reply ---\n{result.text}\n")
    return result.text


def _ctx(repo, **kwargs):
    return host(repo, model="haiku", permission_mode="bypassPermissions", **kwargs)


def _reaches_tool(text: str, nonce: str) -> bool:
    return f"PROBE-{nonce}-OK" in text


def test_config_arm1_clean_isolation_keeps_model_permission_and_tools_overrides(tmp_path):
    # The ticket's headline entry: isolation clean PLUS model/permissionMode/
    # a tools patch. Model: the frontmatter says sonnet, the file says haiku.
    # Tools + permission: CLEAN's default `--tools ""` leaves the child with
    # no tool at all, so a real Bash result can only appear if the tools
    # patch AND bypassPermissions survived CLEAN.
    repo = make_repo(tmp_path)
    nonce = uuid.uuid4().hex
    body = (
        "Reply with exactly two lines.\n"
        "Line 1: your own exact model id as you know it.\n"
        f"Line 2: use the Bash tool to run: echo BASH-{nonce} -- actually invoke "
        "the tool -- and report its exact output, or NOBASH if you have no Bash tool."
    )
    yml = (
        "agents:\n"
        '  "some-plugin:reviewer":\n'
        "    isolation: clean\n"
        "    model: haiku\n"
        "    permissionMode: bypassPermissions\n"
        "    tools:\n"
        "      add: [Bash]\n"
    )

    text = _run(
        repo,
        yml,
        definition("reviewer", plugin="some-plugin", model="sonnet", body=body),
        _ctx(repo),
    )

    assert "haiku" in text.lower()
    assert "sonnet" not in text.lower()
    assert f"BASH-{nonce}" in text


def test_config_arm2_mcp_remove_takes_a_parent_server_away(tmp_path):
    repo = make_repo(tmp_path)
    nonce = uuid.uuid4().hex
    defn = definition("reviewer", plugin=None, scope="project", body=_probe_body(nonce))
    ctx = _ctx(repo, mcp_servers={"fake": FAKE_SERVER}, available_mcp_servers={"fake": FAKE_SERVER})

    control = _run(repo, None, defn, ctx)
    removed = _run(repo, "agents:\n  reviewer:\n    mcpServers:\n      remove: [fake]\n", defn, ctx)

    assert _reaches_tool(control, nonce), "control must reach the tool or the negative is vacuous"
    assert not _reaches_tool(removed, nonce)


def test_config_arm3_mcp_add_gains_a_server_the_parent_lacked(tmp_path):
    repo = make_repo(tmp_path)
    nonce = uuid.uuid4().hex
    defn = definition("reviewer", plugin=None, scope="project", body=_probe_body(nonce))
    ctx = _ctx(repo, available_mcp_servers={"fake": FAKE_SERVER})

    control = _run(repo, None, defn, ctx)
    added = _run(repo, "agents:\n  reviewer:\n    mcpServers:\n      add: [fake]\n", defn, ctx)

    assert not _reaches_tool(control, nonce)
    assert _reaches_tool(added, nonce)


def test_config_arm4_can_spawn_false_blocks_a_server_declared_in_project_settings(tmp_path):
    # The server is declared in the project's own .mcp.json — reachable
    # through settings, NOT through --mcp-config. Only a strict MCP set makes
    # `canSpawn: false` mean anything.
    repo = make_repo(tmp_path)
    (repo / ".mcp.json").write_text(json.dumps({"mcpServers": {"fake": FAKE_SERVER}}))
    (repo / ".claude").mkdir()
    (repo / ".claude" / "settings.json").write_text(
        json.dumps({"enableAllProjectMcpServers": True})
    )
    nonce = uuid.uuid4().hex
    defn = definition("reviewer", plugin=None, scope="project", body=_probe_body(nonce))
    ctx = _ctx(
        repo,
        available_mcp_servers={"fake": FAKE_SERVER},
        dispatch_mcp_server_name="fake",
    )

    control = _run(repo, None, defn, ctx)
    blocked = _run(repo, "agents:\n  reviewer:\n    canSpawn: false\n", defn, ctx)

    assert _reaches_tool(control, nonce), "control must reach the tool or the negative is vacuous"
    assert not _reaches_tool(blocked, nonce)
