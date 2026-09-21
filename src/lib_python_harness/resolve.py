"""`resolve(definition, host_context) -> RunSpec`: the one place every
`AgentDefinition` field and `HostContext` field gets turned into a
provider-independent `RunSpec`, once, for an `Isolation.INHERIT` dispatch.

Fallback shape (`definition` else `context`) applies to `model`,
`permission_mode` and `effort` alike — a definition that sets its own value
wins; one that leaves it unset falls back to the parent session's own
value. `tools`/`disallowed_tools`/`skills`/`max_turns` always come from the
definition (no context to fall back to: those are agent-specific, not
session-level). `omit_claude_md`/`hooks`/`mcp_servers` also come from the
definition, but are dropped (forced to `None`) at `source_scope ==
"plugin"` — a documented assumption about how the *parent* Claude Code
loads plugin agents (plan Premises), not something readable from this
worktree; falsifying it later changes only this function's plugin branch.
`mcp_servers` additionally falls back to `host_context.mcp_servers` when
the definition itself does not set one, so the parent's own inherited MCP
servers still reach `--mcp-config` even for a definition that never
mentions `mcpServers:` at all.

`description` always comes from the definition, unconditionally — there is
no `host_context` fallback (a session has no ambient "description") and no
plugin-scope drop (unlike `permission_mode`/`hooks`/`mcp_servers`, a
plugin's own description is not part of the ignore-list assumption). An
empty/missing frontmatter description normalizes to `None` here, so the
`payload`/`materialized` carriers can each apply their own fallback
(omit the JSON key; synthesize a dispatchable filler) uniformly.

The agent's own body always becomes `RunSpec.system_prompt`. Without a
`task` it is also `RunSpec.prompt` (the definition's body *is* what the
dispatched run is asked to do). With the optional keyword-only `task`,
`RunSpec.prompt` is the task instead, so the child gets the body only as
its agent instructions (the `--agents` payload / materialized `.md` body,
see `providers.claude_cli`) and the task only as its user message (stdin);
`task=""` is a task, not "unset". No `--system-prompt` is emitted for
INHERIT.

`resolve(definition, host_context, config=None, *, task=None)`: with `config` (a loaded
`.seretos/harness.yml`, see `config.load_harness_config`) the result above is
then retuned by `config.apply.apply_config`; `config=None` returns it
untouched.
"""
from __future__ import annotations

from .providers.base import Isolation, RunSpec


def resolve(
    definition, host_context, config=None, *, task: str | None = None
) -> RunSpec:
    spec = _resolve_base(definition, host_context, task)
    if config is None:
        return spec
    from .config.apply import apply_config

    return apply_config(spec, definition, config, host_context)


def _resolve_base(definition, host_context, task: str | None = None) -> RunSpec:
    is_plugin = definition.source_scope == "plugin"

    model = definition.model or host_context.model
    effort = definition.effort or host_context.effort

    if is_plugin:
        permission_mode = host_context.permission_mode
        hooks = None
        mcp_servers = None
        omit_claude_md = None
    else:
        permission_mode = definition.permission_mode or host_context.permission_mode
        hooks = definition.hooks
        mcp_servers = (
            definition.mcp_servers
            if definition.mcp_servers
            else host_context.mcp_servers
        )
        omit_claude_md = definition.omit_claude_md

    return RunSpec(
        prompt=task if task is not None else definition.body,
        isolation=Isolation.INHERIT,
        model=model,
        effort=effort,
        system_prompt=definition.body,
        cwd=host_context.cwd,
        permission_mode=permission_mode,
        tools=definition.tools,
        disallowed_tools=definition.disallowed_tools,
        skills=definition.skills,
        max_turns=definition.max_turns,
        hooks=hooks,
        mcp_servers=mcp_servers,
        omit_claude_md=omit_claude_md,
        agent_name=definition.qualified_name,
        description=definition.description or None,
    )
