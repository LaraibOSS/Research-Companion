"""Small helpers shared by the labelled-file benchmark harnesses.

Both harnesses read a JSONL file row by row and must report what they could not
read rather than drop it: a benchmark that silently skips rows states a
denominator it never had.
"""
from __future__ import annotations

import json
from pathlib import Path


class BenchFormatError(ValueError):
    """The input file does not match the format the harness expects."""


def read_jsonl(path: str | Path) -> list[tuple[int, dict | None, str]]:
    """Every non-blank line of *path* as ``(line_no, object_or_None, error)``.

    A line that is not a JSON object comes back with ``None`` and the reason,
    so the caller can count it as skipped instead of losing it.
    """
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise BenchFormatError(f"Cannot read {p}: {exc}") from exc
    rows: list[tuple[int, dict | None, str]] = []
    for no, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            rows.append((no, None, f"not valid JSON ({exc.msg})"))
            continue
        if not isinstance(obj, dict):
            rows.append((no, None, "not a JSON object"))
            continue
        rows.append((no, obj, ""))
    return rows


def rate(numerator: int, denominator: int) -> float | None:
    """``numerator / denominator``, or None when nothing was measured.

    None, not 0.0: a rate over zero checked entries is undefined, and printing
    0% would read as "never fails" when it means "never tried".
    """
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def fmt_rate(numerator: int, denominator: int) -> str:
    """A rate with its denominator always beside it."""
    r = rate(numerator, denominator)
    if r is None:
        return "n/a (0 checked)"
    return f"{r:.1%} ({numerator} of {denominator} checked)"
