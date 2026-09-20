"""`MistralCliProvider` — the Mistral Vibe CLI (`vibe -p --output streaming`).

Compile-level skeleton (tests phase): behaviour is added in the implement phase.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .base import LaunchPlan, RunResult, RunSpec


class MistralCliProvider:
    """Builds and parses the `vibe` CLI's command line (CLEAN only)."""

    name = "mistral"
    binary_argv = ["vibe"]

    def build_launch_plan(
        self, spec: RunSpec, *, session_id: str, run_dir: Path
    ) -> LaunchPlan:
        raise NotImplementedError

    def parse_events(self, lines: Iterable[str]) -> RunResult:
        raise NotImplementedError
