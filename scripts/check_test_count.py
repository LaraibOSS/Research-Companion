#!/usr/bin/env python3
"""Fail when the test suite shrinks.

Coverage can be deleted silently: a refactor drops a test file, a flaky case is
removed instead of fixed, a merge resolves a conflict by keeping one side. None
of that turns CI red — the remaining tests still pass, so the suite reports
success while protecting less than it did yesterday.

This records the collected test count in ``tests/.test-count`` and fails if the
current count is lower. Adding tests is normal (the baseline moves up); removing
them requires deliberately lowering the baseline in the same commit, which makes
the removal visible in review.

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


def read_baseline() -> int | None:
    if not BASELINE.exists():
        return None
    text = BASELINE.read_text(encoding="utf-8").strip()
    return int(text) if text.isdigit() else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", action="store_true",
                        help="write the current count as the new baseline")
    args = parser.parse_args()

    current = collected_count()
    baseline = read_baseline()

    if args.update or baseline is None:
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE.write_text(f"{current}\n", encoding="utf-8")
        print(f"test-count baseline set to {current}")
        return 0

    if current < baseline:
        print(
            f"FAIL: test count dropped {baseline} -> {current} "
            f"({baseline - current} fewer).\n"
            "Tests were removed. If that is intentional, lower the baseline in "
            "the same commit:\n"
            "    python scripts/check_test_count.py --update\n"
            "so the removal is visible in review.",
            file=sys.stderr,
        )
        return 1

    if current > baseline:
        BASELINE.write_text(f"{current}\n", encoding="utf-8")
        print(f"test count grew {baseline} -> {current}; baseline updated")
        return 0

    print(f"test count unchanged at {current}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
