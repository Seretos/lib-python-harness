"""R3 (#37) — the same assertion R2 proves offline against the fake CLI,
proven here against the real `claude` CLI: a definition-driven INHERIT
dispatch's `tools:` frontmatter reaches the spawned child as a real
session-level restriction, observed through that run's own `events.jsonl`
`init` event.

requires_claude: needs the installed `claude` CLI + subscription auth.
Excluded from the default `python -m pytest` run (see `pyproject.toml`'s
`addopts`, which deselects `requires_claude`); run explicitly with this
module's own substitute-execution command, per the plan:

    python -m pytest -m requires_claude -k tools_scope

#37 R0 (2026-09-22, `claude` v2.1.278, `.adev/37-2/r0/probe1.jsonl` /
`probe2.jsonl` — see `tests/fixtures/fake_claude.py`'s `FAKE_DEFAULT_TOOLS`
comment and `tests/test_inherit_live.py`'s module docstring for the same
citation): a plain session's own `init` event carries a `tools` key
listing all seven of the ticket's forbidden names (`ListAgents`,
`ReportFindings`, `ScheduleWakeup`, plus the `Cron*`/`Task*`/
`RemoteTrigger`/`PushNotification` families — both the directly-callable
half and the deferred half of the symptom are present in the plain list,
so this channel is evidence for both halves, not only the directly-callable
one); `--tools Read,Glob` narrows that same key to exactly `Read`/`Glob`
plus a residue of `mcp__*` MCP-server tool names only, never any of the
seven. Assertion (1) below is unsoftened by that residue — R0's stop rule
3 guarantees the residue can never contain a forbidden name, so the two
clauses in this module never contradict each other.

The AC's literal "PR job executes it" clause goes unmet by design: no
live-claude CI job is resurrected for this (`.github/workflows/test.yml`
keeps excluding `requires_claude`, #33 / PR #34 non-goal, restated in the
Blocked-triage comment) — this module runs by hand, on a machine with the
`claude` CLI, and its full output (plus the raw `init` JSON line) belongs
in the PR body per the plan's R3 substitute-execution instructions.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from lib_python_harness import Harness, RunStore
from lib_python_harness.agents.frontmatter import load_agent_definition
from lib_python_harness.host.context import HostContext
from lib_python_harness.resolve import resolve
from lib_python_harness.runtime.store import InMemoryRunStore

pytestmark = pytest.mark.requires_claude

# Same seven names R1 (test_resolve_inherit.py)/R2 (test_harness_offline.py)
# pin, restated here rather than imported so this module has no dependency
# on another test module's internals.
FORBIDDEN_TOOL_NAMES = frozenset(
    {
        "ListAgents",
        "ReportFindings",
        "ScheduleWakeup",
        "CronCreate",
        "CronDelete",
        "CronList",
        "TaskCreate",
        "TaskGet",
        "TaskList",
        "TaskStop",
        "TaskUpdate",
        "RemoteTrigger",
        "PushNotification",
    }
)

# R0's measured residue (probe2.jsonl, `--tools Read,Glob`): every surviving
# name beyond Read/Glob was an `mcp__<server>__<tool>` MCP-server tool name,
# never a bare harness/entrypoint tool and never one of the seven forbidden
# names -- a prefix check rather than a literal fixed set, since exactly
# which MCP servers are connected is a property of the machine running this
# test, not of the library under test (R0's own probe session had its own
# plugin/MCP set; a different machine's live run would see a different, but
# same-shaped, residue).
_RESIDUE_PREFIX = "mcp__"


def _write_definition(tmp_path):
    """A real `.md` agent-definition file, the ticket's own shape, with
    `tools: Read, Glob` -- for `load_agent_definition` to load."""
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir(exist_ok=True)
    path = agents_dir / "tools-scope-probe.md"
    path.write_text(
        "\n".join(
            [
                "---",
                "name: tools-scope-probe",
                "description: R3 (#37) live tool-scope probe.",
                "model: haiku",
                "tools: Read, Glob",
                "---",
                "Reply with exactly OK.",
            ]
        )
        + "\n"
    )
    return path


def _init_event_tools(events_path):
    for line in Path(events_path).read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        event = json.loads(line)
        if event.get("type") == "system" and event.get("subtype") == "init":
            return event.get("tools")
    raise AssertionError(f"no init event found in {events_path}")


def test_definition_tool_restriction_in_live_init_event(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    definition_path = _write_definition(tmp_path)
    definition = load_agent_definition(definition_path, source_scope="project")
    host_context = HostContext(
        cwd=repo, model="haiku", permission_mode="default", effort="medium",
        mcp_servers={},
    )
    spec = resolve(definition, host_context)

    store: RunStore = InMemoryRunStore()
    harness = Harness(store=store)
    result = harness.run(spec)
    record = harness.store.get(result.run_id)
    tools = _init_event_tools(record["events_path"])

    # (1) absolute, unsoftened -- never relaxed by the residue check below.
    assert not (set(tools) & FORBIDDEN_TOOL_NAMES)

    # (2) the list is exactly {"Read", "Glob"} plus at most an mcp__* residue.
    extra = set(tools) - {"Read", "Glob"}
    assert all(name.startswith(_RESIDUE_PREFIX) for name in extra), (
        f"unexpected non-MCP, non-forbidden tool name(s) survived narrowing: "
        f"{sorted(n for n in extra if not n.startswith(_RESIDUE_PREFIX))}"
    )
