"""Report Coverage / Saturation -- Phase 2, slice 2e-3.

Honest coverage/saturation signal for a saved deep-research report: for
each section, how much of the library material our OWN search judged
RELEVANT to that section's question is actually reflected in the answer's
citations. Coverage is defined relative to the search's own relevance set
(BM25 heuristic, threshold 0.35 -- reused verbatim from gaps.py's/
directions.py's "relevant" gating), NEVER as "% of the whole library". A
0-denominator (no relevant material found) surfaces as an honest pct 0,
never a fake 100%. LLM-FREE: pure retrieval math, no new prompt. A post-pass
over an ALREADY-BUILT report (deep_research.build_report stays pure and
unchanged), mirroring rcs.py's shape.

Pipeline:
    1. _relevant_units (pure)   -- rank ALL units for a question (rank_fn
                                    called with k=len(units) -- a threshold
                                    COUNT, not a top-k), keep normalized
                                    (gaps._relevance_score) score >= threshold
    2. _section_coverage (pure) -- cited (distinct citation units) INTERSECT
                                    relevant_set / relevant_available;
                                    0-denominator -> honest pct 0
    3. score_report              -- build the unit index once, per-section
                                    coverage + report-level roll-up + a
                                    staleness stamp; never raises, additive,
                                    non-mutating (returns a NEW dict)

See docs/superpowers/specs/2026-08-10-report-coverage-design.md.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from research_companion.gaps import _relevance_score
from research_companion.rank import tokenize

_DEFAULT_THRESHOLD = 0.35


# ---------------------------------------------------------------------------
# _relevant_units
# ---------------------------------------------------------------------------

def _relevant_units(
    question: str,
    units: list,
    *,
    rank_fn: Callable[..., list],
    threshold: float = _DEFAULT_THRESHOLD,
) -> set:
    """Every distinct (paper_id, section_id, chunk_index) unit whose
    normalized relevance to *question* (gaps._relevance_score, the SAME
    mode-independent [0,1] normalization gaps.py/directions.py use for
    their own "relevant" gating) is >= *threshold*. Ranks ALL units --
    *rank_fn* (shaped exactly like retrieve.rank_units:
    rank_fn(question, q_tokens, units, *, k) -> list[{"unit", "score",
    "bm25", "cosine", "mode"}]) is called with k=len(units), so this is a
    THRESHOLD COUNT over the whole unit universe, not a top-k retrieval.
    q_tokens come from rank.tokenize(question), the same tokenizer
    qa.answer/gaps.py use.

    Empty *units* -> empty set (no library material at all). *rank_fn*
    raising, returning something that isn't a list, or entries missing a
    usable "unit"/"score" all degrade to being skipped rather than
    propagating -- never raises.
    """
    if not units:
        return set()

    try:
        q_tokens = tokenize(str(question or ""))
        ranked = rank_fn(question, q_tokens, units, k=len(units))
    except Exception:
        return set()

    if not isinstance(ranked, list):
        return set()

    relevant: set = set()
    for r in ranked:
        if not isinstance(r, dict):
            continue
        try:
            score = _relevance_score(r)
        except Exception:
            continue
        if score < threshold:
            continue
        unit = r.get("unit")
        if not isinstance(unit, dict):
            continue
        relevant.add((
            unit.get("paper_id", ""),
            unit.get("section_id", ""),
            unit.get("chunk_index", 0),
        ))
    return relevant


# ---------------------------------------------------------------------------
# _section_coverage
# ---------------------------------------------------------------------------

def _section_coverage(section: Any, relevant_set: set) -> dict:
    """{"pct", "cited", "relevant_available"} for one report section.
    relevant_available = len(relevant_set) (the size of the question's OWN
    relevance set, computed by _relevant_units); cited = the count of
    DISTINCT (paper_id, section_id, chunk_index) citation units that are
    ALSO in relevant_set (a citation outside the relevant set never
    inflates the count); pct = round(100 * cited / relevant_available), or
    an honest 0 when relevant_available == 0 (never a fake 100%). A
    malformed *section* (not a dict, non-list/malformed "citations")
    degrades to cited=0 rather than raising. Never raises.
    """
    relevant_available = len(relevant_set)
    citations = section.get("citations") if isinstance(section, dict) else None
    citations = citations if isinstance(citations, list) else []

    cited_units: set = set()
    for c in citations:
        if not isinstance(c, dict):
            continue
        key = (c.get("paper_id", ""), c.get("section_id", ""), c.get("chunk_index", 0))
        if key in relevant_set:
            cited_units.add(key)

    cited = len(cited_units)
    pct = round(100 * cited / relevant_available) if relevant_available > 0 else 0
    return {"pct": pct, "cited": cited, "relevant_available": relevant_available}
