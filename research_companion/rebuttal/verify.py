"""Verify that spans a draft attributes to the paper actually appear in it."""
from __future__ import annotations

import re

_MIN_SPAN = 15


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip()


def locate_quote(quote: str, text: str) -> tuple[int, int] | None:
    """Find the (start, end) character offsets of `quote` within `text`.

    Tries an exact match first, then a whitespace/case-insensitive match.
    Offsets always index into the original `text`. Returns the first
    occurrence, or None if the quote is missing, empty, or too short to
    locate reliably.
    """
    if not quote or not text:
        return None
    if len(quote.strip()) < _MIN_SPAN:
        return None

    idx = text.find(quote)
    if idx >= 0:
        return idx, idx + len(quote)

    pattern = re.compile(r"\s+".join(re.escape(tok) for tok in quote.split()), re.IGNORECASE)
    m = pattern.search(text)
    if m:
        return m.start(), m.end()

    return None


def verify_quote(quote: str, fulltext: str) -> tuple[bool, str]:
    if not quote or not fulltext:
        return False, ""
    if quote in fulltext:
        return True, "exact"
    if _norm(quote) in _norm(fulltext):
        return True, "normalized"
    return False, ""


def verify_reply_quotes(reply: str, fulltext: str) -> list[str]:
    reply = reply.replace("“", '"').replace("”", '"')
    spans = re.findall(r'"([^"]+)"', reply)
    return [s for s in spans if len(s) >= _MIN_SPAN and not verify_quote(s, fulltext)[0]]
