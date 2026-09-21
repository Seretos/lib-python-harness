"""Tests for scripts/ci/claude-shim.sh (CI-only token-injecting exec wrapper)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_SHIM = Path(__file__).resolve().parent.parent / "scripts" / "ci" / "claude-shim.sh"
_BASH = shutil.which("bash")

pytestmark = pytest.mark.skipif(_BASH is None, reason="bash not available")


def _posix(p: Path) -> str:
    return p.as_posix()


@pytest.fixture
def recorder(tmp_path):
    out = tmp_path / "rec.json"
    script = tmp_path / "recorder.py"
    script.write_text(
        "import json, os, sys\n"
        f"open({str(out)!r}, 'w').write(json.dumps({{'argv': sys.argv[1:],"
        " 'token': os.environ.get('CLAUDE_CODE_OAUTH_TOKEN'),"
        " 'stdin': sys.stdin.read(),"
        " 'other': os.environ.get('SOME_UNRELATED_VAR')}))\n",
        encoding="utf-8",
    )
    real = tmp_path / "real-claude"
    real.write_text(
        f"#!/usr/bin/env bash\nexec {_posix(Path(sys.executable))!r} "
        f"{_posix(script)!r} \"$@\"\n",
        encoding="utf-8",
    )
    real.chmod(0o755)
    return real, out


def _run(env_extra, args=("-p", "--model", "haiku", "hello"), stdin="prompt"):
    env = dict(os.environ)
    for k in ("HARNESS_CI_CLAUDE_REAL_BIN", "HARNESS_CI_CLAUDE_OAUTH_TOKEN",
              "CLAUDE_CODE_OAUTH_TOKEN"):
        env.pop(k, None)
    env.update(env_extra)
    return subprocess.run(
        [_BASH, _posix(_SHIM), *args], input=stdin, env=env,
        capture_output=True, text=True, timeout=60,
    )


def test_execs_real_bin_with_argv_token_and_stdin(recorder):
    real, out = recorder
    r = _run({"HARNESS_CI_CLAUDE_REAL_BIN": _posix(real),
              "HARNESS_CI_CLAUDE_OAUTH_TOKEN": "nonce-123",
              "SOME_UNRELATED_VAR": "keep-me"})
    assert r.returncode == 0, r.stderr
    rec = json.loads(out.read_text(encoding="utf-8"))
    assert rec["argv"] == ["-p", "--model", "haiku", "hello"]
    assert rec["token"] == "nonce-123"
    assert rec["stdin"] == "prompt"
    assert rec["other"] == "keep-me"


def test_unset_real_bin_exits_127():
    r = _run({"HARNESS_CI_CLAUDE_OAUTH_TOKEN": "t"})
    assert r.returncode == 127
    assert "HARNESS_CI_CLAUDE_REAL_BIN" in r.stderr


def test_non_executable_real_bin_exits_127(tmp_path):
    f = tmp_path / "not-exec"
    f.write_text("x", encoding="utf-8")
    f.chmod(0o644)
    r = _run({"HARNESS_CI_CLAUDE_REAL_BIN": _posix(f)})
    assert r.returncode == 127


def test_real_bin_equal_to_shim_exits_nonzero_without_looping():
    r = _run({"HARNESS_CI_CLAUDE_REAL_BIN": _posix(_SHIM)})
    assert r.returncode == 127


def test_empty_token_still_execs_real_binary(recorder):
    real, out = recorder
    r = _run({"HARNESS_CI_CLAUDE_REAL_BIN": _posix(real),
              "HARNESS_CI_CLAUDE_OAUTH_TOKEN": ""})
    assert r.returncode == 0, r.stderr
    rec = json.loads(out.read_text(encoding="utf-8"))
    assert rec["argv"] == ["-p", "--model", "haiku", "hello"]
    assert not rec["token"]
