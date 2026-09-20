"""R1 (loading half) — layered discovery of `.seretos/harness.yml`:
home -> outer repos -> inner repo, inner wins; absent everywhere is None.

Precedence is observed through `resolve(..., config=...)` so the assertions
are about what a dispatched agent actually gets, not about `HarnessConfig`
attribute names.
"""
from __future__ import annotations

from lib_python_harness import resolve
from lib_python_harness.config import load_harness_config

from ._config_support import (
    definition,
    fake_home,
    host,
    make_repo,
    write_harness_yml,
)

AGENT = '"p:reviewer"'


def _model_for(cfg, repo, frontmatter_model="opus"):
    return resolve(
        definition(model=frontmatter_model), host(repo), config=cfg
    ).model


def test_home_outer_and_inner_layers_inner_wins(tmp_path, monkeypatch):
    fake_home(tmp_path, monkeypatch, f"agents:\n  {AGENT}:\n    model: haiku\n")
    outer = make_repo(tmp_path, f"agents:\n  {AGENT}:\n    model: sonnet\n", name="outer")
    inner = make_repo(outer / "sub", f"agents:\n  {AGENT}:\n    model: fable\n", name="inner")

    cfg = load_harness_config(inner)

    assert _model_for(cfg, inner) == "fable"


def test_outer_layer_beats_home_when_inner_is_silent(tmp_path, monkeypatch):
    fake_home(tmp_path, monkeypatch, f"agents:\n  {AGENT}:\n    model: haiku\n")
    outer = make_repo(tmp_path, f"agents:\n  {AGENT}:\n    model: sonnet\n", name="outer")
    inner = make_repo(outer / "sub", "defaults:\n  isolation: inherit\n", name="inner")

    cfg = load_harness_config(inner)

    assert _model_for(cfg, inner) == "sonnet"


def test_harness_yaml_spelling_is_read(tmp_path):
    repo = make_repo(tmp_path)
    write_harness_yml(repo, f"agents:\n  {AGENT}:\n    model: fable\n", "harness.yaml")

    cfg = load_harness_config(repo, home_default=False)

    assert cfg is not None
    assert _model_for(cfg, repo) == "fable"


def test_home_only_config_is_found_and_home_default_false_ignores_it(
    tmp_path, monkeypatch
):
    fake_home(tmp_path, monkeypatch, f"agents:\n  {AGENT}:\n    model: haiku\n")
    repo = make_repo(tmp_path)

    with_home = load_harness_config(repo)
    without_home = load_harness_config(repo, home_default=False)

    assert with_home is not None
    assert _model_for(with_home, repo) == "haiku"
    assert without_home is None


def test_empty_file_changes_nothing(tmp_path):
    repo = make_repo(tmp_path, "")
    cfg = load_harness_config(repo, home_default=False)
    # An existing-but-empty file is an (empty) config, not "no config": this
    # keeps the comparison below from degenerating into config=None twice.
    assert cfg is not None
    baseline = resolve(definition(model="opus"), host(repo))

    assert resolve(definition(model="opus"), host(repo), config=cfg) == baseline


def test_no_config_anywhere_is_none(tmp_path, monkeypatch):
    fake_home(tmp_path, monkeypatch)
    repo = make_repo(tmp_path)
    assert load_harness_config(repo) is None


def test_seretos_dir_without_harness_yml_is_none(tmp_path, monkeypatch):
    fake_home(tmp_path, monkeypatch)
    repo = make_repo(tmp_path)
    (repo / ".seretos").mkdir()
    (repo / ".seretos" / "unrelated.yml").write_text("a: 1\n")
    assert load_harness_config(repo) is None
