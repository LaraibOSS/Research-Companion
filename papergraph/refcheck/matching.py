"""Pure, network-free matching helpers for reference validation.

These are the deterministic pre-filters: cheap string comparisons that decide
whether a bibliography entry plausibly matches an authoritative record before
any expensive lookup or LLM call.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher


def normalize_title(title: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace — for comparison only."""
    title = re.sub(r"[^a-z0-9\s]", " ", title.lower())
    return re.sub(r"\s+", " ", title).strip()


def title_similarity(a: str, b: str) -> float:
    """Similarity ratio in [0, 1] between two titles, ignoring case/punctuation."""
    na, nb = normalize_title(a), normalize_title(b)
    if not na and not nb:
        return 1.0
    return SequenceMatcher(None, na, nb).ratio()


def _last_name(author: str) -> str:
    """Best-effort surname extraction, normalized to lowercase alphanumerics.

    Handles "John Smith" -> "smith" and "Smith, John" -> "smith".
    """
    author = author.strip()
    if "," in author:
        surname = author.split(",", 1)[0]
    else:
        parts = author.split()
        surname = parts[-1] if parts else ""
    return re.sub(r"[^a-z0-9]", "", surname.lower())


def author_overlap(claimed: list[str], authoritative: list[str]) -> float:
    """Fraction of `claimed` authors whose surname appears in `authoritative`.

    Matching is on normalized surname, so "J. Smith" matches "John Smith".
    Returns 0.0 when `claimed` is empty (nothing to confirm).
    """
    if not claimed:
        return 0.0
    auth_surnames = {_last_name(a) for a in authoritative}
    auth_surnames.discard("")
    matched = sum(1 for c in claimed if _last_name(c) in auth_surnames)
    return matched / len(claimed)
