"""`CodexCliProvider` — skeleton (RED phase): signatures only."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .base import LaunchPlan, RunResult, RunSpec


class CodexCliProvider:
    name = "codex"
    binary_argv = ["codex"]

    def build_launch_plan(
        self, spec: RunSpec, *, session_id: str, run_dir: Path
    ) -> LaunchPlan:
        raise NotImplementedError

    def parse_events(self, lines: Iterable[str]) -> RunResult:
        raise NotImplementedError
