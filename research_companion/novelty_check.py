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
        title = getattr(p, "title", "") or ""
        abstract = getattr(p, "abstract", "") or ""
        paper_tokens = set(tokenize(f"{title} {abstract}"))
        score = len(direction_tokens & paper_tokens)
        scored.append((score, idx, p))
    scored.sort(key=lambda t: (-t[0], t[1]))
    cap = max(0, top_n)
    return [p for _score, _idx, p in scored[:cap]]
