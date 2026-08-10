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


# ---------------------------------------------------------------------------
# _rank_prior_works
# ---------------------------------------------------------------------------

def test_rank_prior_works_orders_by_token_overlap_desc():
    from research_companion.novelty_check import _rank_prior_works
    low = _paper(title="Completely unrelated topic", abstract="Something else entirely.")
    high = _paper(title="Graph retrieval augmented generation for code search", abstract="")
    out = _rank_prior_works("graph retrieval for code search", [low, high], top_n=5)
    assert out == [high, low]


def test_rank_prior_works_ties_broken_by_original_order():
    from research_companion.novelty_check import _rank_prior_works
    a = _paper(title="Graph retrieval", year=2020)
    b = _paper(title="Graph retrieval", year=2021)
    out = _rank_prior_works("graph retrieval", [a, b], top_n=5)
    assert out == [a, b]


def test_rank_prior_works_caps_at_top_n():
    from research_companion.novelty_check import _rank_prior_works
    papers = [_paper(title=f"Graph retrieval paper {i}") for i in range(10)]
    out = _rank_prior_works("graph retrieval", papers, top_n=3)
    assert len(out) == 3


def test_rank_prior_works_empty_papers_returns_empty():
    from research_companion.novelty_check import _rank_prior_works
    assert _rank_prior_works("graph retrieval", [], top_n=5) == []


def test_rank_prior_works_missing_title_and_abstract_safe():
    from research_companion.novelty_check import _rank_prior_works
    p = _paper(title="", abstract="")
    out = _rank_prior_works("graph retrieval", [p], top_n=5)
    assert out == [p]


# ---------------------------------------------------------------------------
# _prior_block
# ---------------------------------------------------------------------------

def test_prior_block_numbers_and_truncates_abstract():
    from research_companion.novelty_check import _prior_block
    long_abstract = "x" * 400
    p1 = _paper(title="Paper One", year=2020, abstract=long_abstract)
    p2 = _paper(title="Paper Two", year=2021, abstract="short")
    block = _prior_block([p1, p2])
    lines = block.split("\n")
    assert lines[0] == f"[1] Paper One (2020) - {'x' * 300}"
    assert lines[1] == "[2] Paper Two (2021) - short"


def test_prior_block_missing_year_and_abstract_safe():
    from research_companion.novelty_check import _prior_block
    p = _paper(title="No Year Paper", year=None, abstract="")
    block = _prior_block([p])
    assert block == "[1] No Year Paper (n.d.) - "


def test_prior_block_empty_list_returns_empty_string():
    from research_companion.novelty_check import _prior_block
    assert _prior_block([]) == ""
