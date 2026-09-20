"""R6 — the public API is reachable, callable and documented.

Driving test for R6: every public name must import from lib_python_harness
top-level and appear in __all__; the criterion's bare `run(...)` must
resolve to a function, not the façade module.
"""
from __future__ import annotations

import ast
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

# A ```python fenced block inside a section's prose.
_PYTHON_FENCE_RE = re.compile(r"```python\s*\n(.*?)```", re.DOTALL)

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
    # The Provider/store swap seam: Harness(store=..., provider=...) takes
    # these as parameters, so the documented seam is unusable without them
    # (plan R8 — round 1's "exports stay exactly as they are" is reversed
    # here, at 0.1.0, the release that defines the surface).
    "Provider",
    "LaunchPlan",
    "ClaudeCliProvider",
    "MistralCliProvider",
    "RunStore",
    "InMemoryRunStore",
    "FileRunStore",
}

# Prose/keyword matching was tried three times (round 3: bare substring;
# round 4 x2: heading+word-count, then multiple required keywords with a
# minimum count) and failed the tautology critique every time — the test
# critic's round-4 note: "documented accurately" cannot be verified by
# prose/keyword matching alone, because filler prose can always be
# constructed to contain any fixed set of keywords without actually being
# correct documentation (tautology::F14).
#
# The mechanism below is structurally different: each identifier's README
# section must contain a ```python fenced code block that (a) is
# syntactically valid Python (`ast.parse` must not raise) and (b) whose AST
# genuinely references the identifier by name — as a Name/Attribute/Call
# node spelling the identifier itself (e.g. `Harness()`, `RunSpec(...)`,
# `RunState.COMPLETED`, `except IllegalTransitionError:`,
# `lib_python_harness.__version__`). Prose can say the right words about the
# wrong behaviour; it cannot produce valid Python syntax that happens to use
# a name it never actually demonstrates.
#
# For identifiers with real methods/members the plan names (Harness,
# RunResult, Isolation, RunState), the block must *additionally* reference
# at least one of those real names as an attribute — e.g.
# `Harness().stop(run_id, timeout=10.0)` (attr "stop") or a
# `result: RunResult` annotated example accessing `result.state`. This
# blocks the degenerate one-liner `Harness` (a bare Name with no real
# member/method use) from being accepted as documentation.
REQUIRED_README_METHODS: dict[str, frozenset[str]] = {
    # Approach: "harness.py ... exposes Harness with run(spec) (= start +
    # wait, one code path), start, poll, stop(run_id, timeout=10.0),
    # cleanup(run_id, remove_cwd=False)".
    "Harness": frozenset({"run", "start", "poll", "stop", "cleanup"}),
    # R1/R7: RunResult-carrying fields named in the plan's own assertions
    # — non-empty session_id, existing transcript_path, state == COMPLETED,
    # duration < 60s / duration_s.
    "RunResult": frozenset({"session_id", "transcript_path", "state", "duration_s"}),
    # Approach: "Isolation (only CLEAN)".
    "Isolation": frozenset({"CLEAN"}),
    # Approach: "RunState enum — CREATED, RUNNING, COMPLETED, FAILED,
    # CANCELLED".
    "RunState": frozenset({"CREATED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"}),
}


def _code_blocks(body: str) -> list[str]:
    return _PYTHON_FENCE_RE.findall(body)


def _references_identifier(tree: ast.AST, identifier: str) -> bool:
    """True if the AST contains a Name/Attribute node literally spelling
    `identifier` — i.e. the code actually uses that name, not merely prose
    that mentions it."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == identifier:
            return True
        if isinstance(node, ast.Attribute) and node.attr == identifier:
            return True
    return False


def _references_member(tree: ast.AST, member_names: frozenset[str]) -> bool:
    """True if the AST accesses one of `member_names` as a real attribute
    (`.stop`, `.state`, `.CLEAN`, ...) — not just as prose text."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in member_names:
            return True
    return False


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

        blocks = _code_blocks(body)
        assert blocks, (
            f"{name}'s README section has no ```python fenced code block — "
            f"a code example is the documentation evidence this check "
            f"requires (see tautology::F14: keyword-matched prose can "
            f"always be gamed by filler text, a code example much less so)"
        )

        parse_errors: list[str] = []
        member_names = REQUIRED_README_METHODS.get(name, frozenset())
        found_valid_block = False
        found_identifier_reference = False
        found_member_reference = not member_names  # vacuously true if none required

        for block in blocks:
            try:
                tree = ast.parse(block)
            except SyntaxError as exc:
                parse_errors.append(str(exc))
                continue
            references_identifier = _references_identifier(tree, name)
            references_member = not member_names or _references_member(tree, member_names)
            found_identifier_reference = found_identifier_reference or references_identifier
            found_member_reference = found_member_reference or references_member
            if references_identifier and references_member:
                found_valid_block = True
                break

        assert not parse_errors or found_valid_block, (
            f"{name}'s README ```python block(s) are not valid Python — "
            f"ast.parse failed: {parse_errors}"
        )
        assert found_identifier_reference, (
            f"{name}'s README ```python code block(s) never use `{name}` as "
            f"actual Python syntax (a call, instantiation, or attribute "
            f"access) — e.g. `{name}(...)` or `{name}.SOMEMEMBER` — prose "
            f"that merely mentions the name is not enough"
        )
        assert found_member_reference, (
            f"{name}'s README ```python code block(s) use `{name}` but "
            f"never access one of its real members {sorted(member_names)} "
            f"as an attribute (e.g. `{name}().{sorted(member_names)[0]}` or "
            f"`{name}.{sorted(member_names)[0]}`) — a bare mention of the "
            f"name with no real usage is not documentation"
        )
        assert found_valid_block, (
            f"{name}'s README has no single ```python code block that is "
            f"both valid Python and references `{name}` (and its real "
            f"members {sorted(member_names)}) together"
        )


def test_run_resolves_to_a_function_not_the_facade_module():
    assert callable(lib_python_harness.run)
    assert not inspect.ismodule(lib_python_harness.run)


def test_seam_names_resolve_to_the_real_implementations():
    """test-critic round 1, tautology::F2: `test_expected_names_are_exported`
    only checks that the six seam names are strings in `__all__`, and
    `test_every_all_entry_resolves_via_getattr` only checks that the
    top-level attribute exists — neither ties the exported name to the
    actual `Provider`/store class the plan's R8 rationale
    (`Harness(store=..., provider=...)` needing these importable) depends
    on. A placeholder object bound to the right name would pass both. This
    adds the missing identity check: each export must be the very class
    object its owning submodule defines, not a look-alike.
    """
    from lib_python_harness.providers.base import LaunchPlan, Provider
    from lib_python_harness.providers.claude_cli import ClaudeCliProvider
    from lib_python_harness.runtime.store import (
        FileRunStore,
        InMemoryRunStore,
        RunStore,
    )

    assert lib_python_harness.Provider is Provider
    assert lib_python_harness.LaunchPlan is LaunchPlan
    assert lib_python_harness.ClaudeCliProvider is ClaudeCliProvider
    assert lib_python_harness.RunStore is RunStore
    assert lib_python_harness.InMemoryRunStore is InMemoryRunStore
    assert lib_python_harness.FileRunStore is FileRunStore
