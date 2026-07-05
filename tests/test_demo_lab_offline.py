"""tests/test_demo_lab_offline.py — Smoke test for the zero-key Lab offline demo.

Runs examples/demo_lab_offline.py as a subprocess and asserts:
  - exit code 0
  - expected narrative lines appear in stdout
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
DEMO_SCRIPT = REPO_ROOT / "examples" / "demo_lab_offline.py"


def test_demo_lab_offline_script_exists():
    """The demo script must exist."""
    assert DEMO_SCRIPT.exists(), f"Missing: {DEMO_SCRIPT}"


def test_demo_lab_offline_runs_successfully():
    """demo_lab_offline.py must exit 0 and print expected narrative lines."""
    result = subprocess.run(
        [sys.executable, str(DEMO_SCRIPT)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    stdout = result.stdout
    stderr = result.stderr

    assert result.returncode == 0, (
        f"demo_lab_offline.py exited {result.returncode}\n"
        f"stdout:\n{stdout}\n"
        f"stderr:\n{stderr}"
    )

    # Must mention paper replay
    assert "paper_added" in stdout, (
        "Expected '[paper_added]' line in stdout"
    )

    # Must report ingest failure for fixture paper_b
    assert "ingest_failed" in stdout, (
        "Expected '[ingest_failed]' line in stdout (fixture paper_b fails)"
    )

    # Must print 'Demo complete.'
    assert "Demo complete." in stdout, (
        "Expected 'Demo complete.' in stdout"
    )

    # Must report zero API keys
    assert "Zero API keys" in stdout, (
        "Expected 'Zero API keys used' summary in stdout"
    )

    # Must mention Papers added summary
    assert "Papers added" in stdout, (
        "Expected 'Papers added' summary line"
    )
