"""Driving tests for #36: `Harness.start` (and every provider's
`build_launch_plan`) refuses a `model`/`effort` the selected provider cannot
honour, synchronously, before any run record, artifact directory or child
process exists.

R1 — an unknown `model` is refused before any record/artifact/process, at
all three provider call sites (claude, codex, mistral), including the
empty/absent-model special case (plan Approach).

R2 — an unknown `effort` is refused synchronously and the message names the
valid values; the per-provider value sets differ (P1: `minimal`/`none` are
codex-only). Mistral has no effort set at all — it already rejects the
`effort` *field* outright via `_UNSUPPORTED_FIELDS`
(`tests/test_mistral_cli_flags.py::test_each_unhonourable_field_is_rejected`),
so it is not duplicated here.

R3 — every value the provider *does* accept still builds a plan unchanged —
the guard against the fix becoming a false-rejection machine. These cases
already pass against today's (unfixed) code; they stay green through the fix.

Known, accepted residual behaviour (plan-critic round 2 findings misread::F1
and misread::F2 — reviewed and accepted as an inherent trade-off of the
namespace-rule design, not something this test-writing pass redesigns): the
family-token rule is neither exact-typo-proof (a mistyped id that happens to
retain a family token, e.g. a hypothetical "claude-opus-6", would still be
accepted and could still fail ~9s later) nor guaranteed to accept every
legal gateway/Vertex id (one carrying no family token would be wrongly
rejected). Neither direction is asserted below — doing so would pin a
stronger contract than the plan actually committed to.
"""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import pytest

import lib_python_harness.harness as harness_module
from lib_python_harness.errors import UnsupportedByProvider
from lib_python_harness.harness import Harness
from lib_python_harness.providers.base import Isolation, RunSpec
from lib_python_harness.providers.claude_cli import ClaudeCliProvider
from lib_python_harness.providers.codex_cli import CodexCliProvider
from lib_python_harness.providers.mistral_cli import MistralCliProvider
from lib_python_harness.runtime.process import _spawn_detached as _real_spawn_detached

FIXTURES = Path(__file__).parent / "fixtures"
FAKE_CLAUDE = FIXTURES / "fake_claude.py"
FAKE_CODEX = FIXTURES / "fake_codex.py"
FAKE_MISTRAL = FIXTURES / "fake_mistral.py"

_PROVIDER_CLASSES = {
    "claude": ClaudeCliProvider,
    "codex": CodexCliProvider,
    "mistral": MistralCliProvider,
}


def _spy_spawn(monkeypatch):
    """Wraps the real spawn hook (rather than replacing it with a stub) so a
    RED run against today's unfixed code still completes a real (fake-CLI)
    spawn instead of exploding on an unrelated mock mismatch — the call
    count is what R1 asserts on, not whether the spawn itself "succeeds"."""
    calls: list[dict] = []

    def wrapper(**kwargs):
        calls.append(kwargs)
        return _real_spawn_detached(**kwargs)

    monkeypatch.setattr(harness_module, "_spawn_detached", wrapper)
    return calls


def _build_plan(tmp_path, provider: str, **overrides):
    defaults = {
        "claude": dict(model="haiku"),
        "codex": dict(model="gpt-5.6-luna", provider="codex"),
        "mistral": dict(model="mistral-medium-3.5", provider="mistral"),
    }[provider]
    cwd = tmp_path / "cwd"
    cwd.mkdir(exist_ok=True)
    kwargs = dict(prompt="p", isolation=Isolation.CLEAN, cwd=cwd)
    kwargs.update(defaults)
    kwargs.update(overrides)
    spec = RunSpec(**kwargs)
    return _PROVIDER_CLASSES[provider]().build_launch_plan(
        spec, session_id=str(uuid.uuid4()), run_dir=tmp_path / "run"
    )


# -- R1: unknown model refused before any record/artifact/process -----------

_BAD_MODEL_CASES = [
    pytest.param("claude", FAKE_CLAUDE, "opuss", id="claude-typo"),
    pytest.param("claude", FAKE_CLAUDE, None, id="claude-none"),
    pytest.param("claude", FAKE_CLAUDE, "", id="claude-empty"),
    pytest.param("claude", FAKE_CLAUDE, "   ", id="claude-whitespace"),
    pytest.param("claude", FAKE_CLAUDE, "-model", id="claude-leading-dash"),
    pytest.param("codex", FAKE_CODEX, "m", id="codex-unnamespaced"),
    pytest.param("mistral", FAKE_MISTRAL, "spec-model", id="mistral-unnamespaced"),
]


@pytest.mark.parametrize("provider, fake_cli, model", _BAD_MODEL_CASES)
def test_unknown_model_is_refused_before_any_record_or_process(
    tmp_path, monkeypatch, provider, fake_cli, model
):
    calls = _spy_spawn(monkeypatch)
    artifacts_dir = tmp_path / "artifacts"

    harness = Harness(claude_argv=[sys.executable, str(fake_cli)])
    spec = RunSpec(
        prompt="Reply with exactly OK",
        isolation=Isolation.CLEAN,
        model=model,
        provider=provider,
        artifacts_dir=artifacts_dir,
    )

    with pytest.raises(UnsupportedByProvider):
        harness.start(spec)

    assert harness.list_runs() == []
    assert not artifacts_dir.exists() or not any(artifacts_dir.iterdir())
    assert calls == [], "spawn hook must never be reached for a rejected model"


# -- R2: unknown effort refused, message names the valid values -------------


def test_unknown_effort_is_refused_and_message_names_valid_values(tmp_path):
    with pytest.raises(UnsupportedByProvider) as excinfo:
        _build_plan(tmp_path, "claude", effort="hi")
    message = str(excinfo.value)
    for valid in ("low", "medium", "high", "xhigh", "max"):
        assert valid in message, f"{valid!r} missing from claude effort message: {message!r}"

    with pytest.raises(UnsupportedByProvider) as excinfo:
        _build_plan(tmp_path, "codex", effort="xtreme")
    message = str(excinfo.value)
    for valid in ("none", "minimal", "low", "medium", "high", "xhigh", "max"):
        assert valid in message, f"{valid!r} missing from codex effort message: {message!r}"


def test_minimal_effort_is_claude_only_rejected_but_codex_accepted(tmp_path):
    """P1: claude's own CLI set has no 'minimal' (it silently falls back to
    the default and warns — the very symptom this ticket closes), while
    codex's set includes it. A single shared effort set would have had to
    pick a union (wrongly accepting 'minimal' for claude) or an intersection
    (wrongly rejecting valid codex values); this pins the per-provider split."""
    with pytest.raises(UnsupportedByProvider):
        _build_plan(tmp_path, "claude", effort="minimal")

    plan = _build_plan(tmp_path, "codex", effort="minimal")
    assert any("minimal" in tok for tok in plan.argv), plan.argv


# -- R3: every value the provider does accept still builds a plan unchanged -

_ACCEPTED_MODEL_CASES = [
    pytest.param("claude", "claude-opus-5[1m]", id="claude-full-dated-id"),
    pytest.param("claude", "sonnet", id="claude-alias-sonnet"),
    pytest.param("claude", "fable", id="claude-alias-fable"),
    pytest.param("claude", "inherit", id="claude-alias-inherit"),
    pytest.param(
        "claude", "anthropic.claude-3-5-sonnet-20241022-v2:0", id="claude-bedrock-id"
    ),
    pytest.param("codex", "gpt-5.6-luna", id="codex-gpt"),
    pytest.param("mistral", "mistral-medium-3.5", id="mistral-family"),
]


@pytest.mark.parametrize("provider, model", _ACCEPTED_MODEL_CASES)
def test_accepted_models_still_build_a_plan_unchanged(tmp_path, provider, model):
    plan = _build_plan(tmp_path, provider, model=model)
    if provider == "mistral":
        # vibe has no --model flag; the model travels as an env var.
        assert plan.env["VIBE_ACTIVE_MODEL"] == model
    else:
        assert model in plan.argv, f"{model!r} missing from argv verbatim: {plan.argv}"


@pytest.mark.parametrize(
    "provider, effort",
    [
        ("claude", "high"),
        ("claude", "xhigh"),
        ("claude", "max"),
        ("codex", "high"),
        ("codex", "xhigh"),
        ("codex", "max"),
    ],
)
def test_accepted_efforts_still_build_a_plan_unchanged(tmp_path, provider, effort):
    plan = _build_plan(tmp_path, provider, effort=effort)
    assert any(effort in tok for tok in plan.argv), plan.argv


def test_inherit_agent_name_path_still_builds_with_model_emitted_twice(tmp_path):
    """INHERIT + agent_name: `_build_inherit_plan` emits the model both as
    the top-level `--model` flag and inside the `--agents` JSON payload —
    an accepted model must survive the check at both emission sites."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    spec = RunSpec(
        prompt="Body text.",
        isolation=Isolation.INHERIT,
        model="sonnet",
        agent_name="reviewer",
        cwd=repo,
    )
    plan = ClaudeCliProvider().build_launch_plan(
        spec, session_id=str(uuid.uuid4()), run_dir=tmp_path / "run"
    )
    assert "--model" in plan.argv
    assert plan.argv[plan.argv.index("--model") + 1] == "sonnet"

    agents_idx = plan.argv.index("--agents")
    agents_json = json.loads(plan.argv[agents_idx + 1])
    assert agents_json["reviewer"]["model"] == "sonnet"
