"""#24 — the task reaches the child as its user message, the definition body
as its instructions (live reversal probe).

requires_claude: needs the installed `claude` CLI + subscription auth.
Excluded from the default `python -m pytest` run; run explicitly with
`python -m pytest -m requires_claude -k task -q -s`.

The definition body says "reply with the user message reversed"; the task is
`abc`. If the task really arrives as the user message and the body as the
agent's instructions, the reply is exactly `cba`. If the body reached the child
as the user message instead (the pre-#24 behaviour), there would be nothing
to reverse and the reply could not be `cba`.
"""
from __future__ import annotations

import pytest

from lib_python_harness import HostContext, discover, resolve, run

pytestmark = pytest.mark.requires_claude

BODY = "Reply with the text of the user message reversed."


def test_task_is_reversed_by_definition_body(tmp_path):
    repo = tmp_path / "repo"
    agents = repo / ".claude" / "agents"
    agents.mkdir(parents=True)
    (repo / ".git").mkdir()
    (agents / "reverser.md").write_text(
        "---\nname: reverser\ndescription: Reverses the user message\n"
        f"model: haiku\n---\n{BODY}\n"
    )

    context = HostContext(cwd=str(repo))
    context.complete()
    definition = discover(context)["reverser"]

    spec = resolve(definition, context, task="abc")
    result = run(spec)

    assert result.text.strip() == "cba"
