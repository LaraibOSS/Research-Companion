"""discover_rank.py — transparent ranking for Brainstorm discovery results.

Search used to be ordered by citation count alone, which quietly buries recent
work from strong venues under older, heavily-cited papers. This adds two more
orderings and, crucially, makes the choice explicit and explainable in the UI:

    citations — most-cited first (what the tool always did)
    venue     — recognized top venues first, then citations
    balanced  — a blend, so a well-cited paper at an unknown venue and a newer
                paper at a top venue can both surface (the default)

Pure and deterministic: no network, no LLM. Venue recognition reuses the
existing 9-discipline venue KB (`venues.py`) — the same source the review
pipeline's venue-fit lane uses — so "top venue" means one concrete, auditable
thing rather than a hidden heuristic.
"""
from __future__ import annotations

RANK_MODES = ("balanced", "citations", "venue")
DEFAULT_RANK = "balanced"

# Weight applied to the venue signal in "balanced". Citation score is log10, so
# 2.0 is worth ~100x citations: enough that a recent top-venue paper clears the
# mid-tier, while a genuinely dominant paper (orders of magnitude more
# citations) still wins. A top-venue paper is surfaced, never force-ranked #1.
_VENUE_BONUS = 2.0


def is_top_venue(venue: str) -> bool:
    """True when *venue* matches a venue in the curated KB (`venues.py`).

    Matching is deliberately forgiving — sources report venues as "NeurIPS",
    "Proc. of ACL 2024", "Conference on ... (EMNLP)" — so KB names and aliases
    are matched as whole tokens (longest wins) against the venue string and any
    parenthesized acronym in it. Best-effort by design: the KB holds short
    names, so a long-form venue with no acronym simply goes unrecognized and
    loses only its badge. Never raises.
    """
    return top_venue_name(venue) is not None


def top_venue_name(venue: str) -> str | None:
    """The canonical KB name for *venue*, or None when unrecognized."""
    text = str(venue or "").strip().lower()
    if not text:
        return None
    try:
        from research_companion.venues import VENUES
    except Exception:  # noqa: BLE001 — ranking must never depend on the KB loading
        return None

    # Sources report venues in wildly different forms; also try any
    # parenthesized acronym ("Conference on ... (ACL)"), which is where the
    # recognizable short name usually hides in a long-form venue string.
    import re as _re
    haystacks = [text]
    haystacks.extend(m.strip() for m in _re.findall(r"\(([^)]{2,40})\)", text))

    best: tuple[int, str] | None = None
    for venue_rec in VENUES.values():
        candidates = [venue_rec.name, venue_rec.slug, *getattr(venue_rec, "aliases", ())]
        for cand in candidates:
            c = str(cand or "").strip().lower()
            if len(c) < 3:
                continue
            if any(_contains_token(h, c) for h in haystacks) and (
                    best is None or len(c) > best[0]):
                best = (len(c), venue_rec.name)
    return best[1] if best else None


def _contains_token(haystack: str, needle: str) -> bool:
    """Whole-token containment: "acl" matches "proc. of acl 2024" but not
    "practical"."""
    idx = haystack.find(needle)
    while idx != -1:
        before_ok = idx == 0 or not haystack[idx - 1].isalnum()
        end = idx + len(needle)
        after_ok = end >= len(haystack) or not haystack[end].isalnum()
        if before_ok and after_ok:
            return True
        idx = haystack.find(needle, idx + 1)
    return False


def _citation_score(count: int) -> float:
    """Diminishing-returns citation score, so 10k vs 5k citations does not swamp
    every other signal the way a raw count does."""
    from math import log10

    n = max(0, int(count or 0))
    return log10(n + 1)


def rank_results(results: list[dict], mode: str = DEFAULT_RANK) -> list[dict]:
    """Order discovery results by *mode*, annotating each with venue info.

    Every result gains:
        `top_venue`      — canonical KB name, or None
        `is_top_venue`   — bool, for the UI badge

    Ordering is total and deterministic (ties broken by year then title), so the
    same results always render in the same order. Unknown modes fall back to
    DEFAULT_RANK. Never raises.
    """
    items = [r for r in (results or []) if isinstance(r, dict)]
    for r in items:
        name = top_venue_name(r.get("venue", ""))
        r["top_venue"] = name
        r["is_top_venue"] = name is not None

    m = mode if mode in RANK_MODES else DEFAULT_RANK

    def key(r: dict):
        cites = _citation_score(r.get("citation_count", 0))
        top = 1 if r.get("is_top_venue") else 0
        year = r.get("year") or 0
        title = str(r.get("title") or "")
        if m == "citations":
            primary = cites
        elif m == "venue":
            primary = top * 1000 + cites   # venue dominates, citations order within
        else:
            primary = cites + _VENUE_BONUS * top
        # negate numerics for descending, title ascending for a stable tail
        return (-primary, -year, title)

    return sorted(items, key=key)
