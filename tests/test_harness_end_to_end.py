"""Live-CLI driving tests: R1, R1b, R4; plus R7's live half.

requires_claude: needs the installed `claude` CLI + subscription auth.
Excluded from the default `python -m pytest` run (see pyproject.toml's
addopts).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
import uuid
from pathlib import Path

import pytest

from lib_python_harness import Harness, RunSpec, Isolation, RunState

pytestmark = pytest.mark.requires_claude

VERSION_RE = re.compile(r"\d+\.\d+\.\d+")


def test_clean_run_returns_ok():
    """R1 driving test."""
    harness = Harness()
    result = harness.run(
        RunSpec(prompt="Reply with exactly OK", isolation=Isolation.CLEAN, model="haiku")
    )
    print(f"session_id={result.session_id}")
    print(f"transcript_path={result.transcript_path}")

    assert result.text == "OK"
    assert result.session_id
    assert result.transcript_path.exists()
    assert result.state == RunState.COMPLETED
    assert result.duration_s < 60

    record = harness.store.get(result.run_id)
    provenance_path = Path(record["provenance_path"])
    print(f"provenance_path={provenance_path}")
    assert provenance_path.exists()


def test_resume_after_cleanup(tmp_path):
    """R1b driving test."""
    harness = Harness()
    nonce = f"harness-nonce-{uuid.uuid4().hex}"
    result = harness.run(
        RunSpec(
            prompt=f"Remember the word {nonce}. Reply with exactly OK.",
            isolation=Isolation.CLEAN,
            model="haiku",
        )
    )
    run_cwd = harness.store.get(result.run_id)["cwd"]
    harness.cleanup(result.run_id)  # default remove_cwd=False

    resumed = subprocess.run(
        [
            "claude", "--resume", result.session_id, "-p",
            "What word did I ask you to remember? Reply with just the word.",
        ],
        cwd=run_cwd,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert nonce in resumed.stdout

    # Additional edge-case coverage — printed, not asserted: does resume
    # still work from an unrelated cwd? That decides whether remove_cwd=True
    # is ever safe (see plan R1b and docs/run-lifecycle.md).
    unrelated_cwd = tmp_path / "unrelated"
    unrelated_cwd.mkdir()
    resumed_elsewhere = subprocess.run(
        [
            "claude", "--resume", result.session_id, "-p",
            "What word did I ask you to remember? Reply with just the word.",
        ],
        cwd=str(unrelated_cwd),
        capture_output=True,
        text=True,
        timeout=60,
    )
    print(f"resume from the run's own cwd contains the nonce: {nonce in resumed.stdout}")
    print(
        "resume from an unrelated cwd contains the nonce (informational only, "
        f"not asserted): {nonce in resumed_elsewhere.stdout}"
    )


def test_stop_cancels_long_run():
    """R4 driving test."""
    harness = Harness()
    record = harness.start(
        RunSpec(
            prompt="Count to one million, one number per line.",
            isolation=Isolation.CLEAN,
            model="haiku",
        )
    )
    time.sleep(2)  # let the child actually start emitting events
    pid_before_stop = harness.store.get(record.run_id).get("pid")

    stopped = harness.stop(record.run_id, timeout=10.0)
    assert stopped.state == RunState.CANCELLED

    if pid_before_stop is not None:
        with pytest.raises(ProcessLookupError):
            os.kill(pid_before_stop, 0)

    events_path = Path(harness.store.get(record.run_id)["events_path"])
    assert events_path.exists()
    assert events_path.stat().st_size > 0


def test_provenance_of_live_run():
    """R7 additional edge-case coverage (live half)."""
    harness = Harness()
    result = harness.run(
        RunSpec(prompt="Reply with exactly OK", isolation=Isolation.CLEAN, model="haiku")
    )
    record = harness.store.get(result.run_id)
    provenance = json.loads(Path(record["provenance_path"]).read_text())

    version_check = subprocess.run(["claude", "--version"], capture_output=True, text=True)
    installed_version = VERSION_RE.search(
        version_check.stdout or version_check.stderr
    ).group(0)

    assert provenance["claude_version"] == installed_version
    assert provenance["exit_code"] == 0
