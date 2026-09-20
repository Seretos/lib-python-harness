"""Offline driving tests for `Harness.resume()` (ticket #11): R1, R2, R5.

R1 — resume replays the origin's isolation flags: `--session-id <id>` becomes
`--resume <session_id>`, the new prompt is the run's prompt, and the resume is
a NEW run (`run_id` differs, `session_id` is the origin's, `resumed_from` is
the origin's `run_id`).

R2 — resume refuses `CREATED`/`RUNNING` origins, unknown ids and a session that
already has a live run, before anything is spawned.

R5 — resume is explicitly unsupported for providers that cannot replay an
isolated resume (codex, mistral, a custom provider without
`build_resume_plan`).

Concurrency (plan-critic F1): the same-session exclusion is asserted for two
threads on ONE `Harness` and for two `Harness` instances sharing ONE store in
one process. Cross-PROCESS exclusion is NOT tested and NOT guaranteed: it
depends on the store (a shared `FileRunStore` has no cross-process lock) and
is documented as a limit, not claimed.

Truncated origins: a `CANCELLED` origin resumes mechanically, but it carries
only the transcript the CLI actually wrote, so the follow-up answer may be
based on a partial turn (`test_resume_accepts_cancelled_origin`).
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import threading
import time
from pathlib import Path

import pytest

from lib_python_harness.errors import HarnessError, UnsupportedByProvider
from lib_python_harness.harness import Harness
from lib_python_harness.providers.base import Isolation, LaunchPlan, RunResult, RunSpec
from lib_python_harness.runtime.lifecycle import RunState
from lib_python_harness.runtime.store import InMemoryRunStore

FAKE_CLAUDE = Path(__file__).parent / "fixtures" / "fake_claude.py"

# Independently written, deliberately NOT imported from CLEAN_ARGV_FLAGS (an
# import would make the assertion vacuous — see tests/test_claude_cli_flags.py).
CLEAN_FLAG_PAIRS = [
    ["--setting-sources", ""],
    ["--tools", ""],
    ["--output-format", "stream-json"],
]
CLEAN_FLAG_SINGLES = ["--strict-mcp-config", "--disable-slash-commands", "--verbose"]


def _has_adjacent(flags: list[str], pair: list[str]) -> bool:
    return any(flags[i : i + len(pair)] == pair for i in range(len(flags) - len(pair) + 1))


def _origin_run(tmp_path, harness, *, cwd=None):
    run_cwd = cwd if cwd is not None else tmp_path / "origin-cwd"
    run_cwd.mkdir(exist_ok=True)
    (run_cwd / "planted.txt").write_text("x")  # non-empty: CLEAN emptiness check must not re-trip
    spec = RunSpec(
        prompt="origin prompt",
        isolation=Isolation.CLEAN,
        model="haiku",
        effort="medium",
        cwd=run_cwd,
        allow_nonempty_cwd=True,
        artifacts_dir=tmp_path / "artifacts",
    )
    return harness.run(spec), run_cwd


def _provenance(harness, run_id) -> dict:
    return json.loads(Path(harness.store.get(run_id)["provenance_path"]).read_text())


def _fake_harness(store=None, extra=()):
    return Harness(
        store=store if store is not None else InMemoryRunStore(),
        claude_argv=[sys.executable, str(FAKE_CLAUDE), *extra],
    )


# -- R1 ---------------------------------------------------------------------


def test_resume_argv_repeats_isolation_flags_and_swaps_session_flag(tmp_path):
    harness = _fake_harness()
    origin, run_cwd = _origin_run(tmp_path, harness)
    assert origin.state == RunState.COMPLETED

    new_prompt = "follow-up prompt"
    result = harness.resume(origin.run_id, new_prompt)

    assert isinstance(result, RunResult)
    assert result.state == RunState.COMPLETED
    assert result.run_id != origin.run_id
    assert result.session_id == origin.session_id

    origin_prov = _provenance(harness, origin.run_id)
    prov = _provenance(harness, result.run_id)
    flags = prov["flags"]

    for pair in CLEAN_FLAG_PAIRS:
        assert _has_adjacent(flags, pair), f"{pair} missing from resume flags"
    for single in CLEAN_FLAG_SINGLES:
        assert single in flags, f"{single} missing from resume flags"
    assert _has_adjacent(flags, ["--model", "haiku"])

    assert "--session-id" not in flags
    assert origin.session_id not in [
        t for i, t in enumerate(flags) if i == 0 or flags[i - 1] != "--resume"
    ], "origin session id must appear only as the --resume value"
    assert _has_adjacent(flags, ["--resume", origin.session_id])

    # Everything else is the origin's argv verbatim: dropping the session pair
    # from the origin and the resume pair from the resume leaves equal argv.
    def _drop(flags_, key):
        out, skip = [], False
        for i, t in enumerate(flags_):
            if skip:
                skip = False
                continue
            if t == key:
                skip = True
                continue
            out.append(t)
        return out

    assert _drop(flags, "--resume") == _drop(origin_prov["flags"], "--session-id")

    assert prov["prompt_sha256"] == hashlib.sha256(new_prompt.encode()).hexdigest()
    assert prov["resumed_from"] == origin.run_id
    assert harness.store.get(result.run_id)["resumed_from"] == origin.run_id
    assert prov["session_id"] == origin.session_id
    # the origin is untouched: still COMPLETED, no resumed_from
    assert harness.store.get(origin.run_id)["state"] == RunState.COMPLETED
    assert "resumed_from" not in origin_prov or origin_prov["resumed_from"] is None
    # the origin cwd (holding claude's / the caller's files) is reused as-is
    assert Path(prov["cwd"]) == run_cwd


def test_resume_of_a_resumed_run_has_exactly_one_resume_pair(tmp_path):
    harness = _fake_harness()
    origin, _ = _origin_run(tmp_path, harness)
    first = harness.resume(origin.run_id, "first follow-up")
    assert first.state == RunState.COMPLETED

    second = harness.resume(first.run_id, "second follow-up")
    assert second.state == RunState.COMPLETED

    flags = _provenance(harness, second.run_id)["flags"]
    assert flags.count("--resume") == 1
    assert _has_adjacent(flags, ["--resume", origin.session_id])
    assert "--session-id" not in flags
    for pair in CLEAN_FLAG_PAIRS:
        assert _has_adjacent(flags, pair), f"{pair} missing from resume-of-resume flags"
    for single in CLEAN_FLAG_SINGLES:
        assert single in flags, f"{single} missing from resume-of-resume flags"


def test_resume_after_origin_cwd_deleted_uses_fresh_cwd(tmp_path):
    harness = _fake_harness()
    origin, run_cwd = _origin_run(tmp_path, harness)
    shutil.rmtree(run_cwd)

    result = harness.resume(origin.run_id, "again")

    assert result.state == RunState.COMPLETED
    prov = _provenance(harness, result.run_id)
    assert Path(prov["cwd"]) != run_cwd
    assert Path(prov["cwd"]).is_dir()
    assert result.session_id == origin.session_id


def test_resume_accepts_cancelled_origin(tmp_path):
    """A CANCELLED (truncated) origin resumes mechanically; the follow-up may
    rest on a partial turn because only the transcript the CLI wrote exists."""
    harness = _fake_harness()
    origin, _ = _origin_run(tmp_path, harness)
    record = harness.store.get(origin.run_id)
    record["state"] = RunState.CANCELLED
    harness.store.put(origin.run_id, record)

    result = harness.resume(origin.run_id, "again")

    assert result.state == RunState.COMPLETED
    assert result.session_id == origin.session_id


# -- R2 ---------------------------------------------------------------------


def _seed(store, run_id, state, *, session_id="sess-1", provider="claude"):
    store.put(
        run_id,
        {
            "run_id": run_id,
            "session_id": session_id,
            "state": state,
            "provider": provider,
            "binary_argv": ["claude"],
            "argv": ["claude", "-p", "--session-id", session_id],
            "cwd": Path("."),
        },
    )


@pytest.fixture
def spawn_calls(monkeypatch):
    calls: list = []
    monkeypatch.setattr(
        "lib_python_harness.harness._spawn_detached",
        lambda *a, **kw: calls.append((a, kw)) or None,
    )
    return calls


def test_resume_rejects_non_terminal_unknown_and_concurrent(spawn_calls):
    store = InMemoryRunStore()
    _seed(store, "created-run", RunState.CREATED, session_id="s-created")
    _seed(store, "running-run", RunState.RUNNING, session_id="s-running")
    _seed(store, "done-run", RunState.COMPLETED, session_id="s-shared")
    _seed(store, "live-sibling", RunState.RUNNING, session_id="s-shared")
    harness = Harness(store=store)

    with pytest.raises(HarnessError, match="CREATED"):
        harness.resume("created-run", "hi")
    with pytest.raises(HarnessError, match="RUNNING"):
        harness.resume("running-run", "hi")
    with pytest.raises(HarnessError, match="no-such-run"):
        harness.resume("no-such-run", "hi")
    with pytest.raises(HarnessError, match="live-sibling"):
        harness.resume("done-run", "hi")

    assert spawn_calls == [], "a guard must raise before anything is spawned"


def test_resume_guard_sees_sibling_created_state_and_other_instance(spawn_calls):
    """The liveness scan reads the shared store, so a live run recorded by a
    DIFFERENT Harness instance on the same store blocks the resume too."""
    store = InMemoryRunStore()
    _seed(store, "done-run", RunState.COMPLETED, session_id="s")
    _seed(store, "sibling", RunState.CREATED, session_id="s")

    with pytest.raises(HarnessError, match="sibling"):
        Harness(store=store).resume("done-run", "hi")
    assert spawn_calls == []


def test_resume_of_same_session_after_terminal_sibling_is_allowed(tmp_path):
    """The guard keys on liveness, not on the session: a resume that already
    finished does not block the next one."""
    harness = _fake_harness()
    origin, _ = _origin_run(tmp_path, harness)

    first = harness.resume(origin.run_id, "one")
    second = harness.resume(origin.run_id, "two")

    assert first.state == second.state == RunState.COMPLETED
    assert len({origin.run_id, first.run_id, second.run_id}) == 3


@pytest.mark.parametrize("shared_instance", [True, False], ids=["one-harness", "two-harnesses"])
def test_concurrent_resume_of_one_session_lets_exactly_one_through(tmp_path, shared_instance):
    """Two simultaneous resumes of one session: exactly one runs, the other
    raises HarnessError. The store scan is widened (sleep after it returns) so
    that, without an atomic scan-then-put, BOTH callers would pass the guard.
    Two Harness instances on one store share a process-wide critical section;
    cross-process exclusion is a documented limit and is not tested here."""
    store = InMemoryRunStore()
    h1 = _fake_harness(store=store, extra=("--sleep", "0.5"))
    origin, _ = _origin_run(tmp_path, h1)
    h2 = h1 if shared_instance else _fake_harness(store=store, extra=("--sleep", "0.5"))

    real_list = store.list

    def slow_list():
        snapshot = real_list()
        time.sleep(0.3)
        return snapshot

    store.list = slow_list  # type: ignore[method-assign]

    outcomes: list = []
    barrier = threading.Barrier(2)

    def go(harness):
        barrier.wait()
        try:
            outcomes.append(harness.resume(origin.run_id, "follow-up"))
        except Exception as exc:  # noqa: BLE001 - collected and asserted below
            outcomes.append(exc)

    threads = [threading.Thread(target=go, args=(h,)) for h in (h1, h2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    results = [o for o in outcomes if isinstance(o, RunResult)]
    errors = [o for o in outcomes if isinstance(o, HarnessError)]
    assert len(outcomes) == 2 and len(results) == 1 and len(errors) == 1, outcomes


# -- R5 ---------------------------------------------------------------------


class _NoResumeProvider:
    """A custom provider that never learned `build_resume_plan`. It is named
    "claude" on purpose: the recorded provider name is one Harness supports, so
    only a capability check on the injected object can produce the refusal (a
    provider-name allowlist would let this through)."""

    name = "claude"
    binary_argv = ["custom"]

    def build_launch_plan(self, spec, *, session_id, run_dir):  # pragma: no cover
        return LaunchPlan(argv=[], cwd=str(run_dir), env={}, stdin=spec.prompt)

    def parse_events(self, lines):  # pragma: no cover
        raise NotImplementedError


@pytest.mark.parametrize("provider", ["codex", "mistral"])
def test_resume_is_unsupported_for_non_claude_providers(spawn_calls, provider):
    store = InMemoryRunStore()
    _seed(store, "run-1", RunState.COMPLETED, provider=provider)

    with pytest.raises(UnsupportedByProvider, match=provider):
        Harness(store=store).resume("run-1", "hi")

    assert spawn_calls == []


def test_resume_with_provider_lacking_build_resume_plan_is_unsupported(spawn_calls):
    store = InMemoryRunStore()
    _seed(store, "run-1", RunState.COMPLETED, provider="claude")

    with pytest.raises(UnsupportedByProvider, match="build_resume_plan"):
        Harness(store=store, provider=_NoResumeProvider()).resume("run-1", "hi")

    assert spawn_calls == []


# -- #21 start_resume -------------------------------------------------------
#
# `start_resume()` is the non-blocking half of `resume()`: it returns as soon
# as the follow-up child is spawned (state RUNNING); the caller then uses
# poll / wait_for / stop.


def test_start_resume_returns_running_before_child_exits(tmp_path):
    harness = _fake_harness(extra=("--sleep", "0.5"))
    origin, _ = _origin_run(tmp_path, harness)
    assert origin.state == RunState.COMPLETED

    t0 = time.monotonic()
    started = harness.start_resume(origin.run_id, "follow-up prompt")
    elapsed = time.monotonic() - t0

    assert elapsed < 0.3, f"start_resume blocked for {elapsed:.2f}s (child sleeps 0.5s)"
    assert isinstance(started, RunResult)
    assert started.run_id != origin.run_id
    assert started.session_id == origin.session_id
    assert started.state == RunState.RUNNING
    assert harness.store.get(started.run_id)["resumed_from"] == origin.run_id
    assert harness.poll(started.run_id).state == RunState.RUNNING

    final = harness.wait_for(started.run_id, timeout=30)
    assert final.state == RunState.COMPLETED
    assert final.text == "OK"
    assert final.is_error is False
    assert final.run_id == started.run_id


def test_start_resume_of_a_resumed_run_has_exactly_one_resume_pair(tmp_path):
    harness = _fake_harness()
    origin, _ = _origin_run(tmp_path, harness)
    first = harness.start_resume(origin.run_id, "first follow-up")
    assert harness.wait_for(first.run_id, timeout=30).state == RunState.COMPLETED

    second = harness.start_resume(first.run_id, "second follow-up")
    assert harness.wait_for(second.run_id, timeout=30).state == RunState.COMPLETED

    flags = _provenance(harness, second.run_id)["flags"]
    assert flags.count("--resume") == 1
    assert _has_adjacent(flags, ["--resume", origin.session_id])
    assert "--session-id" not in flags


def test_start_resume_accepts_cancelled_origin(tmp_path):
    harness = _fake_harness()
    origin, _ = _origin_run(tmp_path, harness)
    record = harness.store.get(origin.run_id)
    record["state"] = RunState.CANCELLED
    harness.store.put(origin.run_id, record)

    started = harness.start_resume(origin.run_id, "again")

    assert started.session_id == origin.session_id
    assert harness.wait_for(started.run_id, timeout=30).state == RunState.COMPLETED


def test_stop_on_started_resume_leaves_origin_untouched(tmp_path):
    harness = _fake_harness(extra=("--sleep", "5"))
    origin, _ = _origin_run(tmp_path, harness)
    origin_run_dir = harness.store.get(origin.run_id)["run_dir"]

    started = harness.start_resume(origin.run_id, "follow-up")
    assert started.state == RunState.RUNNING
    stopped = harness.stop(started.run_id)

    assert stopped.state == RunState.CANCELLED
    assert harness.store.get(started.run_id)["state"] == RunState.CANCELLED
    origin_record = harness.store.get(origin.run_id)
    assert origin_record["state"] == RunState.COMPLETED
    assert origin_record["run_dir"] == origin_run_dir
    assert origin_record.get("resumed_from") is None
    assert _provenance(harness, origin.run_id).get("resumed_from") is None


def test_second_start_resume_while_first_is_live_is_rejected(tmp_path):
    harness = _fake_harness(extra=("--sleep", "5"))
    origin, _ = _origin_run(tmp_path, harness)
    first = harness.start_resume(origin.run_id, "one")
    try:
        with pytest.raises(HarnessError, match=first.run_id):
            harness.start_resume(origin.run_id, "two")
    finally:
        harness.stop(first.run_id)


def test_start_resume_argv_repeats_isolation_flags(tmp_path):
    harness = _fake_harness(extra=("--sleep", "0.3"))
    origin, run_cwd = _origin_run(tmp_path, harness)
    new_prompt = "follow-up prompt"

    started = harness.start_resume(origin.run_id, new_prompt)
    try:
        argv = harness.store.get(started.run_id)["argv"]
        assert _has_adjacent(argv, ["--resume", origin.session_id])
        assert "--session-id" not in argv
        for pair in CLEAN_FLAG_PAIRS:
            assert _has_adjacent(argv, pair), f"{pair} missing from start_resume argv"
        for single in CLEAN_FLAG_SINGLES:
            assert single in argv, f"{single} missing from start_resume argv"
        assert _has_adjacent(argv, ["--model", "haiku"])
    finally:
        final = harness.wait_for(started.run_id, timeout=30)

    assert final.state == RunState.COMPLETED
    prov = _provenance(harness, started.run_id)
    flags = prov["flags"]
    assert _has_adjacent(flags, ["--resume", origin.session_id])
    assert "--session-id" not in flags
    assert prov["prompt_sha256"] == hashlib.sha256(new_prompt.encode()).hexdigest()
    assert prov["resumed_from"] == origin.run_id
    assert Path(prov["cwd"]) == run_cwd


def test_start_resume_after_origin_cwd_deleted_uses_fresh_cwd(tmp_path):
    harness = _fake_harness()
    origin, run_cwd = _origin_run(tmp_path, harness)
    shutil.rmtree(run_cwd)

    started = harness.start_resume(origin.run_id, "again")
    assert harness.wait_for(started.run_id, timeout=30).state == RunState.COMPLETED

    prov = _provenance(harness, started.run_id)
    assert Path(prov["cwd"]) != run_cwd
    assert Path(prov["cwd"]).is_dir()


def _error_case_created(store):
    _seed(store, "created-run", RunState.CREATED, session_id="s-created")
    return "created-run", HarnessError, "CREATED"


def _error_case_running(store):
    _seed(store, "running-run", RunState.RUNNING, session_id="s-running")
    return "running-run", HarnessError, "RUNNING"


def _error_case_unknown(store):
    return "no-such-run", HarnessError, "no-such-run"


def _error_case_live_sibling(store):
    _seed(store, "done-run", RunState.COMPLETED, session_id="s-shared")
    _seed(store, "live-sibling", RunState.RUNNING, session_id="s-shared")
    return "done-run", HarnessError, "live-sibling"


def _error_case_codex(store):
    _seed(store, "run-1", RunState.COMPLETED, provider="codex")
    return "run-1", UnsupportedByProvider, "codex"


def _error_case_mistral(store):
    _seed(store, "run-1", RunState.COMPLETED, provider="mistral")
    return "run-1", UnsupportedByProvider, "mistral"


@pytest.mark.parametrize(
    "case",
    [
        _error_case_created,
        _error_case_running,
        _error_case_unknown,
        _error_case_live_sibling,
        _error_case_codex,
        _error_case_mistral,
    ],
    ids=lambda f: f.__name__.removeprefix("_error_case_"),
)
def test_start_resume_error_paths_match_resume(spawn_calls, case):
    store = InMemoryRunStore()
    run_id, exc_type, match = case(store)
    harness = Harness(store=store)

    with pytest.raises(exc_type, match=match) as start_exc:
        harness.start_resume(run_id, "hi")
    with pytest.raises(exc_type, match=match) as resume_exc:
        harness.resume(run_id, "hi")

    assert type(start_exc.value) is type(resume_exc.value)
    assert spawn_calls == [], "a guard must raise before anything is spawned"


def test_start_resume_with_provider_lacking_build_resume_plan_is_unsupported(spawn_calls):
    store = InMemoryRunStore()
    _seed(store, "run-1", RunState.COMPLETED, provider="claude")

    with pytest.raises(UnsupportedByProvider, match="build_resume_plan"):
        Harness(store=store, provider=_NoResumeProvider()).start_resume("run-1", "hi")

    assert spawn_calls == []


def test_start_resume_accepts_empty_prompt_like_resume(tmp_path):
    """No empty-prompt validation exists on resume(); start_resume matches it."""
    harness = _fake_harness()
    origin, _ = _origin_run(tmp_path, harness)

    resumed = harness.resume(origin.run_id, "")
    started = harness.start_resume(origin.run_id, "")

    assert resumed.state == RunState.COMPLETED
    assert started.state == RunState.RUNNING
    assert harness.wait_for(started.run_id, timeout=30).state == RunState.COMPLETED
