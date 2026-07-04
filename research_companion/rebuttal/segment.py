"""Split raw reviewer text into individual Concern items (deterministic heuristics)."""
from __future__ import annotations

import re

from research_companion.rebuttal.models import Concern

_REVIEWER_RE = re.compile(r"^\s*(?:[#=\s]*)reviewer\s*#?\s*(\w+)", re.IGNORECASE)
_R_PREFIX_RE = re.compile(r"^R(\d+)[:.]\s")
_ITEM_RE = re.compile(r"^\s*(?:\d+[.)]|[-*])\s+")
_MIN_LEN = 20


def segment_reviews(text: str) -> list[Concern]:
    concerns: list[Concern] = []
    reviewer_n = 0
    reviewer = "R1"
    counter = 0
    buf: list[str] = []

    def flush():
        nonlocal counter
        body = re.sub(r"\s+", " ", " ".join(buf)).strip()
        buf.clear()
        if not body:
            return
        if len(body) < _MIN_LEN and concerns:
            concerns[-1].text += " " + body
            return
        counter += 1
        concerns.append(Concern(concern_id=f"{reviewer}.{counter}", reviewer=reviewer, text=body))

    def _switch_reviewer(label: str) -> None:
        nonlocal reviewer_n, reviewer, counter
        flush()
        if label.isdigit():
            reviewer = f"R{label}"
        else:
            reviewer_n += 1
            reviewer = f"R{reviewer_n}"
        counter = 0

    for line in text.splitlines():
        m = _REVIEWER_RE.match(line)
        if m:
            _switch_reviewer(m.group(1))
            continue
        r = _R_PREFIX_RE.match(line)
        if r:
            _switch_reviewer(r.group(1))
            remainder = line[r.end():]
            if remainder.strip():
                buf.append(remainder)
            continue
        if _ITEM_RE.match(line):
            flush()
            buf.append(_ITEM_RE.sub("", line))
        elif not line.strip():
            flush()
        else:
            buf.append(line)
    flush()
    return concerns
