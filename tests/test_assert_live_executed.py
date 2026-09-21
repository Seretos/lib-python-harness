"""Tests for scripts/assert_live_executed.py (junit execution assertion)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "assert_live_executed.py"


def _load():
    spec = importlib.util.spec_from_file_location("assert_live_executed", _SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _case(module: str, name: str, *, skipped=False, file=True, failed=False) -> str:
    attrs = f'classname="{module.replace("/", ".").removesuffix(".py")}" name="{name}"'
    if file:
        attrs += f' file="{module}"'
    body = ""
    if skipped:
        body = '<skipped message="nope"/>'
    elif failed:
        body = '<failure message="boom"/>'
    return f"<testcase {attrs}>{body}</testcase>"


def _report(tmp_path: Path, *cases: str) -> str:
    p = tmp_path / "live-results.xml"
    p.write_text(
        '<?xml version="1.0"?><testsuites><testsuite name="pytest">'
        + "".join(cases)
        + "</testsuite></testsuites>",
        encoding="utf-8",
    )
    return str(p)


INHERIT = "tests/test_inherit_live.py"
CONFIG = "tests/test_config_live.py"


def test_zero_testcases_fails(tmp_path):
    assert _load().main([_report(tmp_path)]) == 1


def test_skipped_testcase_fails(tmp_path):
    assert _load().main([_report(tmp_path, _case(CONFIG, "a", skipped=True))]) == 1


def test_all_executed_passes(tmp_path):
    rep = _report(tmp_path, _case(CONFIG, "a"), _case(CONFIG, "b"))
    assert _load().main([rep]) == 0


def test_required_module_absent_fails_and_is_named(tmp_path, capsys):
    rep = _report(tmp_path, _case(CONFIG, "a"), _case(CONFIG, "b"))
    assert _load().main([rep, "--require", INHERIT]) == 1
    out = capsys.readouterr()
    assert INHERIT in out.out + out.err


def test_required_module_only_skipped_fails_and_is_named(tmp_path, capsys):
    rep = _report(tmp_path, _case(CONFIG, "a"), _case(INHERIT, "x", skipped=True))
    assert _load().main([rep, "--require", INHERIT]) != 0
    out = capsys.readouterr()
    assert INHERIT in out.out + out.err


def test_required_module_executed_passes(tmp_path):
    rep = _report(tmp_path, _case(CONFIG, "a"), _case(INHERIT, "x"))
    assert _load().main([rep, "--require", INHERIT]) == 0


def test_failing_testcase_still_counts_as_executed(tmp_path):
    rep = _report(tmp_path, _case(INHERIT, "x", failed=True))
    assert _load().main([rep, "--require", INHERIT]) == 0


def test_missing_file_fails(tmp_path):
    assert _load().main([str(tmp_path / "nope.xml")]) != 0


def test_malformed_file_fails(tmp_path):
    p = tmp_path / "bad.xml"
    p.write_text("<testsuites><oops", encoding="utf-8")
    assert _load().main([str(p)]) != 0


def test_require_matches_on_classname_alone(tmp_path):
    rep = _report(tmp_path, _case(INHERIT, "x", file=False))
    assert _load().main([rep, "--require", INHERIT]) == 0


def test_require_classname_prefix_for_class_based_tests(tmp_path):
    p = tmp_path / "r.xml"
    p.write_text(
        '<testsuites><testsuite><testcase classname="tests.test_inherit_live.TestX" '
        'name="t"/></testsuite></testsuites>',
        encoding="utf-8",
    )
    assert _load().main([str(p), "--require", INHERIT]) == 0


def test_require_does_not_match_similarly_named_module(tmp_path):
    rep = _report(tmp_path, _case("tests/test_inherit_live_extra.py", "x"))
    assert _load().main([rep, "--require", INHERIT]) != 0
