"""Shared helpers for the `.seretos/harness.yml` test modules (ticket #3).

Everything here builds real files on disk and goes through the public
`load_harness_config` / `resolve` path — no hand-built `HarnessConfig`
objects, so a test cannot pass by bypassing the loader.
"""
from __future__ import annotations

import uuid
from pathlib import Path

from lib_python_harness.agents.model import AgentDefinition
from lib_python_harness.host.context import HostContext
from lib_python_harness.providers.claude_cli import ClaudeCliProvider


def write_harness_yml(root: Path, text: str, filename: str = "harness.yml") -> Path:
    cfg_dir = root / ".seretos"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    path = cfg_dir / filename
    path.write_text(text, encoding="utf-8")
    return path


def make_repo(tmp_path: Path, yml: str | None = None, *, name: str = "repo") -> Path:
    repo = tmp_path / name
    repo.mkdir(parents=True, exist_ok=True)
    (repo / ".git").mkdir(exist_ok=True)
    if yml is not None:
        write_harness_yml(repo, yml)
    return repo


def fake_home(tmp_path: Path, monkeypatch, yml: str | None = None) -> Path:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    if yml is not None:
        write_harness_yml(home, yml)
    return home


def definition(
    name: str = "reviewer",
    *,
    plugin: str | None = "p",
    scope: str | None = None,
    **fields,
) -> AgentDefinition:
    qualified = f"{plugin}:{name}" if plugin else name
    return AgentDefinition(
        name=name,
        description=f"{name} agent",
        body=fields.pop("body", f"Body of {name}."),
        source_scope=scope or ("plugin" if plugin else "project"),
        path=Path(f"/nonexistent/{name}.md"),
        qualified_name=qualified,
        **fields,
    )


def host(cwd, **fields) -> HostContext:
    return HostContext(cwd=cwd, **fields)


def build_plan(spec, tmp_path: Path):
    return ClaudeCliProvider().build_launch_plan(
        spec, session_id=str(uuid.uuid4()), run_dir=tmp_path / "run"
    )


def flag_values(argv: list[str], flag: str) -> list[str]:
    return [argv[i + 1] for i, tok in enumerate(argv) if tok == flag and i + 1 < len(argv)]
