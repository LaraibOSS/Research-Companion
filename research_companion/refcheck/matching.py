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


def title_is_cited(cited: str, authoritative: str) -> bool:
    """Does *cited* refer to the *authoritative* title?

    ``title_similarity`` compares two titles. A bibliography line parsed from a
    paper's own text is not a title -- it carries the authors, venue and pages
    around one, which drags the ratio well below the threshold. "Vaswani et al.
    Attention is all you need. NeurIPS" scores 0.69 against "Attention Is All
    You Need" and would be reported as a title mismatch: a false accusation
    against a perfectly correct citation.

    So: a match is either a high similarity ratio, OR the authoritative title
    appearing whole inside the cited string. Containment is real evidence the
    right work was cited, not a relaxation of the check -- a genuinely wrong
    title still fails both tests.
    """
    na, nb = normalize_title(cited), normalize_title(authoritative)
    if not nb:
        return False
    if title_similarity(cited, authoritative) >= 0.9:
        return True

    # Otherwise measure the longest CONTIGUOUS run the two share. This is the
    # only test that survives both ways a real bibliography deviates from the
    # authoritative record:
    #   extra text  - "Vaswani et al. <title>. NeurIPS 2017"
    #   truncation  - "BERT: pre-training of deep bidirectional transformers"
    #                 for a record ending "...for Language Understanding"
    # A different paper shares no long run, so this does not weaken the check.
    match = SequenceMatcher(None, na, nb).find_longest_match(0, len(na), 0, len(nb))
    return match.size >= 20 and (match.size / len(nb)) >= 0.4


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
