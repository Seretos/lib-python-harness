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

# Content-bearing detail each identifier's README section must mention,
# pulled straight from the plan's own description of that identifier's real
# behaviour (plan.md "Approach") rather than a generic word count — see
# tautology finding F11: a heading followed by filler prose ("this section
# will be written up later on") must NOT satisfy the documentation check.
REQUIRED_README_DETAILS: dict[str, tuple[str, ...]] = {
    "__version__": ("version",),
    "run": ("harness", "delegat"),
    "Harness": ("lifecycle", "cleanup", "stop"),
    "RunSpec": ("prompt",),
    "RunResult": ("transcript", "session"),
    "Isolation": ("clean",),
    "RunState": ("transition", "cancelled", "completed"),
    "HarnessError": ("base",),
    "IllegalTransitionError": ("transition",),
    "RunIdentityUnverifiedError": ("pid", "identity"),
    "UnsafeCwdError": ("repo", "empty", "cwd"),
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
        required_terms = REQUIRED_README_DETAILS.get(name)
        assert required_terms is not None, (
            f"{name} is exported but this test has no REQUIRED_README_DETAILS "
            f"entry for it — add the specific behavioural detail its README "
            f"section must mention before trusting its documentation"
        )
        body_lower = body.lower()
        assert any(term in body_lower for term in required_terms), (
            f"README.md's section for {name} mentions none of {required_terms} "
            f"— filler prose under a correct heading is not documentation of "
            f"{name}'s actual behaviour"
        )


def test_run_resolves_to_a_function_not_the_facade_module():
    assert callable(lib_python_harness.run)
    assert not inspect.ismodule(lib_python_harness.run)
