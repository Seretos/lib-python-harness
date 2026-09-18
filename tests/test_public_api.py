"""R6 — the public API is reachable, callable and documented.

Driving test for R6: every public name must import from lib_python_harness
top-level and appear in __all__; the criterion's bare `run(...)` must
resolve to a function, not the façade module.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

import lib_python_harness

README = Path(__file__).resolve().parent.parent / "README.md"

# A documented name gets its own markdown heading (`## name` / `### name` /
# `#### name`, optionally backticked) followed by real prose before the next
# heading. This is what makes the README check below more than a
# string-presence test: a README that only lists the names on one line, or
# gives a name a heading with no body, fails it.
_README_HEADING_RE = re.compile(r"^#{2,4}\s*`?([A-Za-z_][A-Za-z0-9_]*)`?\s*$", re.MULTILINE)

EXPECTED_NAMES = {
    "__version__",
    "run",
    "Harness",
    "RunSpec",
    "RunResult",
    "Isolation",
    "RunState",
    "HarnessError",
    "IllegalTransitionError",
    "RunIdentityUnverifiedError",
    "UnsafeCwdError",
}

# Content-bearing details each identifier's README section must mention,
# pulled verbatim from the plan's own description of that identifier's real
# behaviour (plan.md "Approach", lines ~40-90) — not a generic word count
# and not a single guessable keyword. See tautology finding F1 (round 3):
# a heading followed by a filler sentence containing one required keyword
# ("Raised about the cwd; empty repo handling described elsewhere.") passed
# the previous version of this check without documenting any real behaviour.
#
# Each entry is (terms, min_required): the README section for that name
# must contain at least `min_required` of the *distinct* terms in `terms`.
# The terms are specific field names, method names, enum member names, or
# raising conditions the plan names for that identifier — e.g. real
# RunSpec fields (prompt, cwd, allow_nonempty_cwd, timeout, ...), real
# Harness method names (start, poll, stop, cleanup), real RunState member
# names (CREATED, RUNNING, COMPLETED, FAILED, CANCELLED). Requiring several
# of these together (not one) makes a generic filler sentence implausible:
# it would have to accidentally combine multiple specific, unrelated
# technical terms the plan uses for that exact identifier.
REQUIRED_README_DETAILS: dict[str, tuple[tuple[str, ...], int]] = {
    # No behavioural surface beyond "the installed version string" — one
    # term is the whole content available for this name.
    "__version__": (("version",), 1),
    # Approach: "__init__.py also exports a module-level run(spec)
    # delegating to Harness().run(spec)".
    "run": (("delegat", "harness", "runspec"), 2),
    # Approach: "harness.py ... exposes Harness with run(spec) (= start +
    # wait, one code path), start, poll, stop(run_id, timeout=10.0),
    # cleanup(run_id, remove_cwd=False)".
    "Harness": (("start", "poll", "stop", "cleanup"), 3),
    # Approach: "RunSpec (prompt, isolation, model, effort, system_prompt,
    # json_schema, cwd, allow_nonempty_cwd, artifacts_dir, timeout)".
    "RunSpec": (
        ("prompt", "cwd", "allow_nonempty_cwd", "timeout", "effort",
         "system_prompt", "json_schema", "artifacts_dir"),
        3,
    ),
    # R1/R7: RunResult-carrying fields named in the plan's own assertions
    # — non-empty session_id, existing transcript_path, state == COMPLETED,
    # duration < 60s / duration_s.
    "RunResult": (("session", "transcript", "duration", "state"), 3),
    # Approach: "Isolation (only CLEAN)" plus what CLEAN actually strips
    # per R3/ClaudeCliProvider — no tools, no inherited settings sources,
    # no auto-memory load.
    "Isolation": (("clean", "tools", "memory", "settings"), 2),
    # Approach: "RunState enum — CREATED, RUNNING, COMPLETED, FAILED,
    # CANCELLED".
    "RunState": (
        ("created", "running", "completed", "failed", "cancelled"),
        3,
    ),
    # Approach: "HarnessError base + IllegalTransitionError +
    # RunIdentityUnverifiedError + UnsafeCwdError — four types" — a
    # documented base must actually name at least two of its siblings.
    "HarnessError": (
        ("illegaltransitionerror", "runidentityunverifiederror",
         "unsafecwderror"),
        2,
    ),
    # Approach: "transition() raises IllegalTransitionError outside it"
    # and "a stop() on a COMPLETED run raises before any signal logic is
    # reached" — the raising condition, not just the class name.
    "IllegalTransitionError": (("completed", "signal", "stop"), 2),
    # Approach: "None is acted on only while this process still holds the
    # child's Popen, else stop() raises RunIdentityUnverifiedError" — the
    # risk being guarded against is signalling a recycled pid (R4).
    "RunIdentityUnverifiedError": (("popen", "pid", "recycled"), 2),
    # Approach: "must hold no .git in it or any ancestor, and must be
    # empty, else UnsafeCwdError".
    "UnsafeCwdError": (("git", "empty", "ancestor"), 2),
}


def test_all_is_sorted_and_duplicate_free():
    all_names = lib_python_harness.__all__
    assert len(all_names) == len(set(all_names)), "duplicate entries in __all__"
    assert list(all_names) == sorted(all_names), "__all__ is not sorted"


def test_expected_names_are_exported():
    missing = EXPECTED_NAMES - set(lib_python_harness.__all__)
    assert not missing, f"missing from __all__: {sorted(missing)}"


def test_every_all_entry_resolves_via_getattr():
    for name in lib_python_harness.__all__:
        assert hasattr(lib_python_harness, name), (
            f"{name} is in __all__ but lib_python_harness has no such attribute"
        )


def _readme_sections() -> dict[str, str]:
    """Map each documented name to the prose between its heading and the
    next heading (or end of file)."""
    text = README.read_text()
    matches = list(_README_HEADING_RE.finditer(text))
    sections: dict[str, str] = {}
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections[m.group(1)] = text[start:end].strip()
    return sections


def test_every_all_entry_is_documented_in_readme():
    sections = _readme_sections()
    for name in lib_python_harness.__all__:
        body = sections.get(name)
        assert body, (
            f"{name} is exported but README.md has no heading section "
            f"for it (expected a '### {name}' heading followed by prose)"
        )
        detail = REQUIRED_README_DETAILS.get(name)
        assert detail is not None, (
            f"{name} is exported but this test has no REQUIRED_README_DETAILS "
            f"entry for it — add the specific behavioural details its README "
            f"section must mention before trusting its documentation"
        )
        required_terms, min_required = detail
        body_lower = body.lower()
        matched = [term for term in required_terms if term in body_lower]
        assert len(matched) >= min_required, (
            f"README.md's section for {name} mentions only {matched} of the "
            f"required technical details {required_terms} (needs at least "
            f"{min_required} distinct terms) — a single guessable keyword, or "
            f"generic filler prose, must not be able to satisfy this check; "
            f"the section must name several of {name}'s actual fields/"
            f"methods/members/raising-conditions from the plan"
        )


def test_run_resolves_to_a_function_not_the_facade_module():
    assert callable(lib_python_harness.run)
    assert not inspect.ismodule(lib_python_harness.run)
