"""Skeleton for ticket #3 (tests phase): signatures only, no behaviour."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class HarnessConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")


def load_harness_config(cwd, *, home_default: bool = True) -> HarnessConfig | None:
    return None


def apply_config(spec, definition, config):
    return spec
