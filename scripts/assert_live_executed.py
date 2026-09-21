"""Assert a junit report proves the live suite was executed.

Exit 0 only when the report holds at least one ``<testcase>``, none of them
carries a ``<skipped>`` child, and every ``--require <path>`` has at least one
executed testcase attributed to it. A failing testcase still counts as
executed: this script proves execution, not success (pytest's own exit code
covers that).
"""
from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from collections.abc import Sequence


def _norm(path: str) -> str:
    return path.replace("\\", "/")


def _matches(case: ET.Element, required: str) -> bool:
    req = _norm(required)
    file_attr = case.get("file")
    if file_attr is not None and _norm(file_attr) == req:
        return True
    dotted = req.removesuffix(".py").replace("/", ".")
    classname = case.get("classname", "")
    return classname == dotted or classname.startswith(dotted + ".")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", help="junit XML written by pytest --junitxml")
    parser.add_argument("--require", action="append", default=[], metavar="PATH",
                        help="test module that must have an executed testcase")
    args = parser.parse_args(argv)

    try:
        root = ET.parse(args.report).getroot()
    except (OSError, ET.ParseError) as exc:
        print(f"ERROR: cannot read junit report {args.report}: {exc}", file=sys.stderr)
        return 1

    cases = list(root.iter("testcase"))
    skipped = [c for c in cases if c.find("skipped") is not None]
    executed = [c for c in cases if c.find("skipped") is None]
    summary = f"executed={len(executed)} skipped={len(skipped)}"

    problems: list[str] = []
    if not cases:
        problems.append("no testcase in report (nothing was collected or executed)")
    if skipped:
        names = ", ".join(f"{c.get('classname', '')}::{c.get('name', '')}" for c in skipped)
        problems.append(f"skipped testcases are not allowed: {names}")
    for req in args.require:
        if not any(_matches(c, req) for c in executed):
            problems.append(f"required module has no executed testcase: {req}")

    if problems:
        print(f"FAIL ({summary})", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    print(f"OK ({summary})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
