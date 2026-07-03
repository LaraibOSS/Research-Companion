"""Verify that spans a draft attributes to the paper actually appear in it."""
from __future__ import annotations

import re

_MIN_SPAN = 15


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip()


def verify_quote(quote: str, fulltext: str) -> tuple[bool, str]:
    if not quote or not fulltext:
        return False, ""
    if quote in fulltext:
        return True, "exact"
    if _norm(quote) in _norm(fulltext):
        return True, "normalized"
    return False, ""


def verify_reply_quotes(reply: str, fulltext: str) -> list[str]:
    spans = re.findall(r'"([^"]+)"', reply)
    return [s for s in spans if len(s) >= _MIN_SPAN and not verify_quote(s, fulltext)[0]]
