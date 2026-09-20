"""Provider-independent CLEAN-isolation helpers: the cwd recipe and the
env scrub. Shared by every CLI adapter so none imports another's privates.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Iterable

from ..errors import UnsafeCwdError
from .base import RunSpec


def _raises_if_git_ancestor(path: Path) -> None:
    resolved = path.resolve()
    for candidate in (resolved, *resolved.parents):
        if (candidate / ".git").exists():
            raise UnsafeCwdError(
                f"{path} is inside a git repository ({candidate}); "
                "Isolation.CLEAN requires an empty temp directory outside any repo"
            )


def _resolve_clean_cwd(spec: RunSpec) -> Path:
    if spec.cwd is None:
        # Fresh every call: this is the load-bearing half of the auto-memory
        # guarantee. A directory the CLI has never run in has no per-cwd
        # memory tree to load from — the guarantee comes from the cwd being
        # new, not from any flag.
        return Path(tempfile.mkdtemp(prefix="lib-python-harness-cwd-"))

    cwd = Path(spec.cwd)
    if not cwd.exists():
        raise UnsafeCwdError(f"{cwd} does not exist")
    if not cwd.is_dir():
        raise UnsafeCwdError(f"{cwd} is not a directory")

    _raises_if_git_ancestor(cwd)

    if any(cwd.iterdir()) and not spec.allow_nonempty_cwd:
        raise UnsafeCwdError(
            f"{cwd} is not empty; Isolation.CLEAN requires an empty cwd unless "
            "allow_nonempty_cwd=True is set (the single, provenance-recorded opt-out)"
        )
    return cwd


def scrub_env(names: Iterable[str], prefixes: Iterable[str] = ()) -> dict[str, str]:
    """A copy of this process's environment minus every name in `names` and
    every variable starting with one of `prefixes`."""
    prefixes = tuple(prefixes)
    env = dict(os.environ)
    for name in names:
        env.pop(name, None)
    if prefixes:
        for name in list(env):
            if name.startswith(prefixes):
                env.pop(name, None)
    return env
