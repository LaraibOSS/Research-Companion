"""Novelty Gate — per-direction novelty check (Brainstorm slice 2c).

"Has anyone already done this?" — a small, synchronous, ephemeral novelty
check for ONE research direction (title + rationale from directions.py,
Brainstorm 2b). No Agent/`ctx`, no disk cache -- consistent with 2b's
ephemeral design. Reuses prompts.format_comparison_prompt (COMPARISON_PROMPT)
as-is; no new prompt. Reuses discover.search_topic_with_fallback for real
prior-art search and rank.tokenize for a token-overlap "closest prior work"
ranking (no semantic-similarity primitive exists yet).

Honest: the verdict is grounded ONLY in real retrieved prior works. Zero
prior works found -> an honest low-confidence "novel" with an explicit
"no prior work found" note, and NO LLM call (nothing to compare against).
Never raises: any search/LLM/parse failure is caught and reported via the
`llm_error` field, mirroring directions.py's synthesize_directions pattern.

See docs/superpowers/specs/2026-08-10-brainstorm-novelty-design.md.
"""
from __future__ import annotations

import json
import math
from collections.abc import Callable

from research_companion import discover
from research_companion.extract import _strip_code_fences
from research_companion.prompts import format_comparison_prompt
from research_companion.rank import tokenize

_VERDICTS = {"novel", "incremental", "overlaps", "anticipated"}


def _field(p, name: str, default=None):
    """Attribute accessor safe against non-DiscoveredPaper items. A bare
    ``str`` in the papers list would make ``getattr(p, "title", "")`` return
    the bound ``str.title`` method rather than the default, so treat any
    ``str`` as having no fields."""
    if isinstance(p, str):
        return default
    return getattr(p, name, default)


# ---------------------------------------------------------------------------
# _novelty_query
# ---------------------------------------------------------------------------

def _novelty_query(title: str) -> str:
    """Build the prior-art search query from a direction's title -- just the
    stripped title (the direction *is* the claim to search for). Empty or
    whitespace-only input returns "" -- the sentinel `check_novelty` treats
    as "no query" (skip search and LLM entirely; nothing to check)."""
    return str(title or "").strip()


# ---------------------------------------------------------------------------
# _rank_prior_works
# ---------------------------------------------------------------------------

def _rank_prior_works(direction_text: str, papers: list, top_n: int = 5) -> list:
    """Score each DiscoveredPaper by token overlap between *direction_text*
    and the paper's title+abstract, using the same rank.tokenize primitive
    gaps.resolve_gaps uses. Score = size of the set intersection of tokens
    (deterministic, no semantic-similarity primitive exists). Sorted
    descending by score; ties keep the papers' original (already
    citation-sorted by discover.search_topic_with_fallback) order -- a
    stable sort key of (-score, original_index). Capped at *top_n*. Empty
    or partial input (missing title/abstract) is safe -- never raises.
    """
    if not papers:
        return []
    direction_tokens = set(tokenize(direction_text))
    scored = []
    for idx, p in enumerate(papers):
        title = _field(p, "title", "") or ""
        abstract = _field(p, "abstract", "") or ""
        paper_tokens = set(tokenize(f"{title} {abstract}"))
        score = len(direction_tokens & paper_tokens)
        scored.append((score, idx, p))
    scored.sort(key=lambda t: (-t[0], t[1]))
    cap = max(0, top_n)
    return [p for _score, _idx, p in scored[:cap]]


# ---------------------------------------------------------------------------
# _prior_block
# ---------------------------------------------------------------------------

def _prior_block(papers: list) -> str:
    """Numbered "[i] {title} ({year}) - {abstract[:300]}" block for the
    COMPARISON_PROMPT's prior_art slot (1-indexed). Missing year renders as
    "n.d."; missing/empty abstract renders as an empty trailing string.
    Empty *papers* returns "" (never raises)."""
    lines = []
    for i, p in enumerate(papers, 1):
        title = _field(p, "title", "") or "Untitled"
        year = _field(p, "year", None)
        year_str = year if year is not None else "n.d."
        abstract = _field(p, "abstract", "") or ""
        lines.append(f"[{i}] {title} ({year_str}) - {abstract[:300]}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# _prior_work_dict / _clamp01 (small private assembly helpers)
# ---------------------------------------------------------------------------

def _prior_work_dict(p) -> dict:
    """The curated, real (clickable) subset of a DiscoveredPaper attached to
    check_novelty's output -- title/year/url/doi/arxiv_id/s2_id/pmid/
    citation_count (NOT the full DiscoveredPaper.to_dict())."""
    return {
        "title": _field(p, "title", "") or "",
        "year": _field(p, "year", None),
        "url": _field(p, "url", "") or "",
        "doi": _field(p, "doi", None),
        "arxiv_id": _field(p, "arxiv_id", None),
        "s2_id": _field(p, "s2_id", None),
        "pmid": _field(p, "pmid", None),
        "citation_count": _field(p, "citation_count", 0) or 0,
    }


def _clamp01(value: object) -> float:
    """Coerce *value* to a finite float in [0.0, 1.0] (mirrors
    agents/novelty.py's _clamp_confidence)."""
    try:
        v = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(v):
        return 0.0
    return max(0.0, min(1.0, v))


# ---------------------------------------------------------------------------
# check_novelty
# ---------------------------------------------------------------------------

def check_novelty(
    title: str,
    rationale: str,
    *,
    year_min: int | None = None,
    year_max: int | None = None,
    limit: int = 15,
    top_n: int = 5,
    search: Callable[..., list] | None = None,
    llm: Callable[[str], str] | None = None,
) -> dict:
    """Check the novelty of ONE research direction (title + rationale)
    against real, freshly-searched prior work. Never raises.

    Pipeline: pure query -> real search -> pure rank -> (zero results: an
    honest low-confidence "novel", no LLM) OR one format_comparison_prompt
    LLM call -> _strip_code_fences + tolerant json.loads -> pure normalize.

    Returns {"verdict": one of "novel"/"incremental"/"overlaps"/
    "anticipated"/None, "confidence": float in [0,1], "rationale": str,
    "closest_prior": list[str], "prior_works": list[dict] (see
    _prior_work_dict), "query": str, "llm_error": str|None}. `llm_error` is
    a short message when the LLM call or its JSON parse failed (a
    retryable failure the caller can surface, verdict stays None); it is
    None for every other outcome, including "zero prior works found" and
    the empty-title shell.
    """
    query = _novelty_query(title)
    if not query:
        return {
            "verdict": None, "confidence": 0.0, "rationale": "",
            "closest_prior": [], "prior_works": [], "query": "", "llm_error": None,
        }

    search_fn = search or discover.search_topic_with_fallback
    try:
        papers = search_fn(query, limit=limit, year_min=year_min, year_max=year_max)
    except Exception as exc:
        # A prior-art search failure (network/provider outage) is a retryable
        # failure, NOT evidence of novelty -- surface it via llm_error (which
        # the endpoint maps to a retry banner) rather than propagating or
        # falsely returning "novel".
        return {
            "verdict": None, "confidence": 0.0, "rationale": "",
            "closest_prior": [], "prior_works": [], "query": query,
            "llm_error": str(exc) or exc.__class__.__name__,
        }

    direction_text = f"{title} {rationale}".strip()
    top = _rank_prior_works(direction_text, papers, top_n=top_n)

    if not top:
        return {
            "verdict": "novel", "confidence": 0.3,
            "rationale": "No prior work found for this direction in the searched sources.",
            "closest_prior": [], "prior_works": [], "query": query, "llm_error": None,
        }

    prior_works = [_prior_work_dict(p) for p in top]
    claim = f"{title}. {rationale}".strip()
    prior_art = _prior_block(top)

    try:
        raw = llm(format_comparison_prompt(claim=claim, prior_art=prior_art))
        parsed = json.loads(_strip_code_fences(raw)) if isinstance(raw, str) else raw
        if not isinstance(parsed, dict):
            raise ValueError("LLM returned non-object JSON")
    except Exception as exc:
        return {
            "verdict": None, "confidence": 0.0, "rationale": "",
            "closest_prior": [], "prior_works": [], "query": query,
            "llm_error": str(exc) or exc.__class__.__name__,
        }

    verdict = parsed.get("verdict")
    if verdict not in _VERDICTS:
        verdict = "novel"
    confidence = _clamp01(parsed.get("confidence", 0.0))
    out_rationale = str(parsed.get("rationale") or "")
    raw_closest = parsed.get("closest_prior")
    closest_prior = [str(x) for x in raw_closest] if isinstance(raw_closest, list) else []

    return {
        "verdict": verdict, "confidence": confidence, "rationale": out_rationale,
        "closest_prior": closest_prior, "prior_works": prior_works, "query": query,
        "llm_error": None,
    }
