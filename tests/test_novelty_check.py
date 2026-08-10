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


# ---------------------------------------------------------------------------
# check_novelty
# ---------------------------------------------------------------------------

def test_check_novelty_empty_title_returns_empty_shell_no_search_no_llm():
    from research_companion.novelty_check import check_novelty

    def exploding_search(*a, **k):
        raise AssertionError("search must not be called for an empty title")

    def exploding_llm(prompt):
        raise AssertionError("llm must not be called for an empty title")

    out = check_novelty("", "some rationale", search=exploding_search, llm=exploding_llm)
    assert out == {
        "verdict": None, "confidence": 0.0, "rationale": "", "closest_prior": [],
        "prior_works": [], "query": "", "llm_error": None,
    }


def test_check_novelty_whitespace_title_returns_empty_shell():
    from research_companion.novelty_check import check_novelty

    def exploding_search(*a, **k):
        raise AssertionError("search must not be called for a whitespace-only title")

    out = check_novelty("   ", "rationale", search=exploding_search, llm=None)
    assert out["verdict"] is None
    assert out["query"] == ""
    assert out["prior_works"] == []


def test_check_novelty_calls_search_with_expected_args():
    from research_companion.novelty_check import check_novelty
    calls = []

    def fake_search(query, *, limit, year_min, year_max):
        calls.append((query, limit, year_min, year_max))
        return []

    check_novelty("Graph retrieval for code", "", year_min=2020, year_max=2024,
                   limit=10, search=fake_search)
    assert calls == [("Graph retrieval for code", 10, 2020, 2024)]


def test_check_novelty_zero_prior_works_returns_honest_novel_no_llm_call():
    from research_companion.novelty_check import check_novelty

    def fake_search(query, *, limit, year_min, year_max):
        return []

    def exploding_llm(prompt):
        raise AssertionError("llm must not be called when there are zero prior works")

    out = check_novelty("Some obscure idea", "rationale", search=fake_search, llm=exploding_llm)
    assert out["verdict"] == "novel"
    assert out["confidence"] == 0.3
    assert out["rationale"] == "No prior work found for this direction in the searched sources."
    assert out["prior_works"] == []
    assert out["closest_prior"] == []
    assert out["llm_error"] is None
    assert out["query"] == "Some obscure idea"


def test_check_novelty_happy_path_with_stub_search_and_llm():
    from research_companion.novelty_check import check_novelty

    papers = [_paper(
        title="GraphRAG for code retrieval", year=2023,
        abstract="Graph retrieval augmented generation for source code search.",
        citation_count=42, arxiv_id="2301.00001", url="https://example.com/1",
    )]

    def fake_search(query, *, limit, year_min, year_max):
        return papers

    def fake_llm(prompt: str) -> str:
        assert "GraphRAG for code retrieval" in prompt
        return json.dumps({
            "verdict": "incremental", "confidence": 0.7,
            "closest_prior": ["GraphRAG for code retrieval"],
            "rationale": "Similar graph retrieval idea already explored.",
        })

    out = check_novelty(
        "Graph retrieval for code search", "Apply graph-based retrieval to code.",
        search=fake_search, llm=fake_llm,
    )
    assert out["verdict"] == "incremental"
    assert out["confidence"] == 0.7
    assert out["rationale"] == "Similar graph retrieval idea already explored."
    assert out["closest_prior"] == ["GraphRAG for code retrieval"]
    assert out["query"] == "Graph retrieval for code search"
    assert out["llm_error"] is None
    assert len(out["prior_works"]) == 1
    pw = out["prior_works"][0]
    assert pw["title"] == "GraphRAG for code retrieval"
    assert pw["year"] == 2023
    assert pw["url"] == "https://example.com/1"
    assert pw["doi"] is None
    assert pw["arxiv_id"] == "2301.00001"
    assert pw["s2_id"] is None
    assert pw["pmid"] is None
    assert pw["citation_count"] == 42


def test_check_novelty_malformed_llm_json_sets_llm_error_no_raise():
    from research_companion.novelty_check import check_novelty
    papers = [_paper(title="X", abstract="x")]

    def fake_search(query, *, limit, year_min, year_max):
        return papers

    def bad_llm(prompt: str) -> str:
        return "not json at all"

    out = check_novelty("Topic", "rationale", search=fake_search, llm=bad_llm)
    assert out["verdict"] is None
    assert out["prior_works"] == []
    assert out["llm_error"]


def test_check_novelty_llm_raises_sets_llm_error_no_raise():
    from research_companion.novelty_check import check_novelty
    papers = [_paper(title="X", abstract="x")]

    def fake_search(query, *, limit, year_min, year_max):
        return papers

    def raising_llm(prompt: str) -> str:
        raise RuntimeError("provider down")

    out = check_novelty("Topic", "rationale", search=fake_search, llm=raising_llm)
    assert out["verdict"] is None
    assert out["prior_works"] == []
    assert out["llm_error"] == "provider down"


def test_check_novelty_normalizes_unknown_verdict_to_novel():
    from research_companion.novelty_check import check_novelty
    papers = [_paper(title="X", abstract="x")]

    def fake_search(query, *, limit, year_min, year_max):
        return papers

    def fake_llm(prompt: str) -> str:
        return json.dumps({"verdict": "groundbreaking", "confidence": 0.9,
                            "closest_prior": [], "rationale": "r"})

    out = check_novelty("Topic", "rationale", search=fake_search, llm=fake_llm)
    assert out["verdict"] == "novel"


def test_check_novelty_clamps_confidence_to_0_1():
    from research_companion.novelty_check import check_novelty
    papers = [_paper(title="X", abstract="x")]

    def fake_search(query, *, limit, year_min, year_max):
        return papers

    def over_llm(prompt: str) -> str:
        return json.dumps({"verdict": "novel", "confidence": 5.0,
                            "closest_prior": [], "rationale": "r"})

    def under_llm(prompt: str) -> str:
        return json.dumps({"verdict": "novel", "confidence": -3.0,
                            "closest_prior": [], "rationale": "r"})

    out_over = check_novelty("Topic", "rationale", search=fake_search, llm=over_llm)
    out_under = check_novelty("Topic", "rationale", search=fake_search, llm=under_llm)
    assert out_over["confidence"] == 1.0
    assert out_under["confidence"] == 0.0


def test_check_novelty_strips_markdown_code_fences():
    from research_companion.novelty_check import check_novelty
    papers = [_paper(title="X", abstract="x")]

    def fake_search(query, *, limit, year_min, year_max):
        return papers

    def fenced_llm(prompt: str) -> str:
        return "```json\n" + json.dumps({
            "verdict": "overlaps", "confidence": 0.5,
            "closest_prior": ["X"], "rationale": "r",
        }) + "\n```"

    out = check_novelty("Topic", "rationale", search=fake_search, llm=fenced_llm)
    assert out["verdict"] == "overlaps"


def test_check_novelty_respects_top_n_cap():
    from research_companion.novelty_check import check_novelty
    papers = [_paper(title=f"Graph retrieval paper {i}") for i in range(10)]

    def fake_search(query, *, limit, year_min, year_max):
        return papers

    def fake_llm(prompt: str) -> str:
        return json.dumps({"verdict": "novel", "confidence": 0.5,
                            "closest_prior": [], "rationale": "r"})

    out = check_novelty("Graph retrieval", "rationale", search=fake_search,
                         llm=fake_llm, top_n=2)
    assert len(out["prior_works"]) == 2
