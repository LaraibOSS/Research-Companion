#!/usr/bin/env python3
"""Fail when the test suite shrinks.

Coverage can be deleted silently: a refactor drops a test file, a flaky case is
removed instead of fixed, a merge resolves a conflict by keeping one side. None
of that turns CI red — the remaining tests still pass, so the suite reports
success while protecting less than it did yesterday.

This records the pytest count in ``tests/.test-count`` and the ``node --test``
count in ``tests/.test-count-js``, failing if either drops. The node suite
needs its own ratchet for a specific reason: CI runs
``node --test tests/js/*.test.mjs``, so a deleted test file makes the glob
expand to fewer files, every one of which passes — exit 0, CI green, coverage
silently gone.

Usage::

    python scripts/check_test_count.py            # verify (CI)
    python scripts/check_test_count.py --update   # accept the current count
"""
from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
BASELINE = REPO_ROOT / "tests" / ".test-count"
JS_BASELINE = REPO_ROOT / "tests" / ".test-count-js"


def collected_count() -> int:
    """Number of tests pytest can collect. Raises on a collection error —
    a suite that cannot be collected must never silently report a count."""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=False,
    )
    # pytest -q prints a trailing summary like "2880 tests collected in 4.20s"
    match = re.search(r"(\d+)\s+tests?\s+collected", proc.stdout)
    if match is None:
        sys.stderr.write(proc.stdout[-2000:] + proc.stderr[-2000:])
        raise SystemExit("could not determine the collected test count")
    if proc.returncode != 0:
        raise SystemExit(f"pytest collection failed (exit {proc.returncode})")
    return int(match.group(1))


def node_collected_count() -> int:
    """Number of node:test tests, counted over the same glob CI runs.

    The TAP reporter is pinned explicitly: node's default reporter is
    ``spec`` on a TTY and ``tap`` otherwise, so an unpinned format parses
    locally and silently fails to match in CI (or the reverse).
    """
    files = sorted((REPO_ROOT / "tests" / "js").glob("*.test.mjs"))
    if not files:
        raise SystemExit("no node test files found at tests/js/*.test.mjs")
    proc = subprocess.run(
        ["node", "--test", "--test-reporter=tap", *[str(f) for f in files]],
        cwd=REPO_ROOT, capture_output=True, text=True, check=False,
    )
    match = re.search(r"^# pass (\d+)", proc.stdout, re.MULTILINE)
    if match is None:
        sys.stderr.write(proc.stdout[-2000:] + proc.stderr[-2000:])
        raise SystemExit("could not determine the node test count")
    if proc.returncode != 0:
        raise SystemExit(f"node --test failed (exit {proc.returncode})")
    return int(match.group(1))


def read_baseline(path: pathlib.Path) -> int | None:
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8").strip()
    return int(text) if text.isdigit() else None


def check(label: str, current: int, path: pathlib.Path, update: bool) -> int:
    """Compare one suite's count against its baseline. Returns an exit code."""
    baseline = read_baseline(path)

    if update or baseline is None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{current}\n", encoding="utf-8")
        print(f"{label} baseline set to {current}")
        return 0

    if current < baseline:
        print(
            f"FAIL: {label} dropped {baseline} -> {current} "
            f"({baseline - current} fewer).\n"
            "Tests were removed. If that is intentional, lower the baseline in "
            "the same commit:\n"
            "    python scripts/check_test_count.py --update\n"
            "so the removal is visible in review.",
            file=sys.stderr,
        )
        return 1

    if current > baseline:
        path.write_text(f"{current}\n", encoding="utf-8")
        print(f"{label} grew {baseline} -> {current}; baseline updated")
        return 0

    print(f"{label} unchanged at {current}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", action="store_true",
                        help="write the current counts as the new baselines")
    args = parser.parse_args()

    # Both run even when the first fails, so one invocation reports both
    # problems rather than hiding the second behind the first.
    py = check("python test count", collected_count(), BASELINE, args.update)
    js = check("node test count", node_collected_count(), JS_BASELINE, args.update)
    return py or js


if __name__ == "__main__":
    raise SystemExit(main())
