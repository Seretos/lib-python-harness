"""Layered discovery + validation of `.seretos/harness.yml`."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from lib_python_config import (
    ConfigError as _LibConfigError,
    load_yaml,
    merge_layers,
    resolve_config_paths,
)
from pydantic import ValidationError

from ..errors import ConfigError
from .schema import HarnessConfig


def _describe(exc: ValidationError, label: str) -> str:
    parts = []
    for err in exc.errors():
        loc = " -> ".join(str(p) for p in err["loc"]) or "<root>"
        # Union members add noise segments ("list[str]", "ListPatch"); the
        # key path up to them is what identifies the offending key.
        detail = f"{loc}: {err['msg']}"
        if "input" in err and not isinstance(err["input"], (dict, list)):
            detail += f" (value: {err['input']!r})"
        elif err.get("type") == "extra_forbidden":
            detail += " (unknown key)"
        parts.append(detail)
    return f"invalid harness config in {label}: " + "; ".join(parts)


def _validate(data: dict[str, Any], label: str) -> HarnessConfig:
    try:
        return HarnessConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(_describe(exc, label)) from exc


def load_harness_config(cwd, *, home_default: bool = True) -> HarnessConfig | None:
    """Merge every `.seretos/harness.yml` (or `.yaml`) from `~` down to
    `cwd`'s innermost repo — inner wins — into one validated
    `HarnessConfig`. `None` when no file exists anywhere.
    """
    try:
        existing, _ = resolve_config_paths(
            Path(cwd),
            config_dir=".seretos",
            filenames=("harness.yml", "harness.yaml"),
            home_default=home_default,
        )
    except _LibConfigError as exc:
        raise ConfigError(str(exc)) from exc
    if not existing:
        return None

    layers: list[dict[str, Any]] = []
    for path in existing:
        try:
            data = load_yaml(path)
        except _LibConfigError as exc:
            message = str(exc)
            raise ConfigError(
                message if str(path) in message else f"{path}: {message}"
            ) from exc
        # Validate each layer alone: after merging, a key is no longer
        # attributable to a file.
        _validate(data, str(path))
        layers.append(data)

    merged = merge_layers(layers, list_strategy="replace")
    return _validate(merged, "merged layers " + ", ".join(str(p) for p in existing))
