"""R6 — the public API is reachable, callable and documented.

Driving test for R6: every public name must import from lib_python_harness
top-level and appear in __all__; the criterion's bare `run(...)` must
resolve to a function, not the façade module.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import lib_python_harness

README = Path(__file__).resolve().parent.parent / "README.md"

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


def test_every_all_entry_is_documented_in_readme():
    text = README.read_text()
    for name in lib_python_harness.__all__:
        assert name in text, f"{name} is exported but not mentioned in README.md"


def test_run_resolves_to_a_function_not_the_facade_module():
    assert callable(lib_python_harness.run)
    assert not inspect.ismodule(lib_python_harness.run)
