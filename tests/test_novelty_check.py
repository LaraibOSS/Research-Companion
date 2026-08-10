"""Tests for research_companion.novelty_check (Brainstorm slice 2c: Novelty
Gate). Reuses prompts.format_comparison_prompt as-is (no new prompt).

Pipeline under test: _novelty_query (pure) -> real search (seam) ->
_rank_prior_works (pure, token-overlap) -> zero-results shortcut OR one
COMPARISON_PROMPT LLM call -> _strip_code_fences + tolerant json.loads ->
pure normalize -> check_novelty (orchestrator, never raises).
"""
from __future__ import annotations

import json

from research_companion.discover import DiscoveredPaper


def _paper(title="Paper", year=2020, abstract="", **kw) -> DiscoveredPaper:
    defaults = dict(
        authors=[], citation_count=0, arxiv_id=None, doi=None, s2_id=None,
        url="", source="", pmid=None, pmcid=None,
    )
    defaults.update(kw)
    return DiscoveredPaper(title=title, year=year, abstract=abstract, **defaults)


# ---------------------------------------------------------------------------
# _novelty_query
# ---------------------------------------------------------------------------

def test_novelty_query_strips_and_returns_title():
    from research_companion.novelty_check import _novelty_query
    assert _novelty_query("  Graph retrieval for code  ") == "Graph retrieval for code"


def test_novelty_query_empty_or_whitespace_returns_empty_sentinel():
    from research_companion.novelty_check import _novelty_query
    assert _novelty_query("") == ""
    assert _novelty_query("   ") == ""
    assert _novelty_query(None) == ""
