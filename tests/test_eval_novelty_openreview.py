"""Tests for the novelty-vs-OpenReview evaluation harness.

All seams injected — no network, no LLM, no real store access.

Two tests:
1. Two fake cases with fake llm → returns per-paper scores + rank-agreement float in [-1,1].
2. Verdict→score mapping is exact.
"""
from __future__ import annotations

import json

from research_companion import store
from research_companion.prompts import extraction_prompt_sha256

# ---------------------------------------------------------------------------
# Helpers: seed two fake papers into the isolated store
# ---------------------------------------------------------------------------

def _seed_cases() -> list[dict]:
    """Seed two fake papers and return the cases list for run_cases."""
    cases = [
        {"paper_id": "local:nov_eval_001", "human_novelty": 5},
        {"paper_id": "local:nov_eval_002", "human_novelty": 2},
    ]
    for case in cases:
        pid = case["paper_id"]
        store.PaperMetadata(
            paper_id=pid,
            title=f"Test paper {pid}",
            authors=["Author A"],
        ).save()
        store.save_extraction(
            pid,
            {
                "concepts": [{"name": "RAG", "definition": "retrieval-augmented generation"}],
                "methods": [],
                "datasets": [],
                "claims": [],
                "results": [],
                "related_work": [],
            },
            prompt_sha=extraction_prompt_sha256(),
        )
        store.save_text(pid, f"Fulltext of {pid}. We propose X here.")
    return cases


def _fake_llm(prompt: str) -> str:
    """Fake LLM that returns minimal valid JSON for any novelty/contribution call."""
    if '"evidence_quote"' in prompt:
        # contribution extraction call
        return json.dumps({
            "claims": [
                {"text": "We propose X.", "kind": "method", "evidence_quote": "We propose X"}
            ]
        })
    # comparison call → always novel with confidence 1.0
    return json.dumps({
        "verdict": "novel",
        "confidence": 1.0,
        "closest_prior": [],
        "rationale": "Looks new to me",
    })


def _fake_search(query: str):
    """Fake search that returns an empty list (no prior art found)."""
    from research_companion.discover import DiscoveredPaper
    return [
        DiscoveredPaper(
            title="Related Work", authors=[], year=2023,
            citation_count=0, arxiv_id=None, doi=None, s2_id=None, url="",
        )
    ]


# ---------------------------------------------------------------------------
# Test 1: run_cases returns per-paper scores and rank-agreement float
# ---------------------------------------------------------------------------

def test_run_cases_returns_scores_and_rank_agreement():
    """Two fake cases → result has per-paper scores and a rank_agreement in [-1, 1]."""
    from research_companion.eval.novelty_openreview import run_cases

    cases = _seed_cases()
    result = run_cases(cases, llm=_fake_llm, search=_fake_search)

    # Top-level keys
    assert "papers" in result, "result must have 'papers' key"
    assert "rank_agreement" in result, "result must have 'rank_agreement' key"

    # Per-paper scores present for both cases
    papers = result["papers"]
    assert len(papers) == 2, f"expected 2 paper entries, got {len(papers)}"

    paper_ids = {p["paper_id"] for p in papers}
    assert "local:nov_eval_001" in paper_ids
    assert "local:nov_eval_002" in paper_ids

    for p in papers:
        assert "paper_id" in p
        assert "model_score" in p
        score = p["model_score"]
        assert 1.0 <= score <= 5.0, f"model_score {score} not in [1, 5]"
        assert "human_novelty" in p

    # Rank agreement is a float in [-1, 1]
    ra = result["rank_agreement"]
    assert isinstance(ra, float), f"rank_agreement must be float, got {type(ra)}"
    assert -1.0 <= ra <= 1.0, f"rank_agreement {ra} not in [-1, 1]"


# ---------------------------------------------------------------------------
# Test 2: verdict → score mapping is exact
# ---------------------------------------------------------------------------

def test_verdict_to_score_mapping():
    """novel=5, incremental=3.5, overlaps=2, anticipated=1."""
    from research_companion.eval.novelty_openreview import VERDICT_SCORES

    assert VERDICT_SCORES["novel"] == 5.0
    assert VERDICT_SCORES["incremental"] == 3.5
    assert VERDICT_SCORES["overlaps"] == 2.0
    assert VERDICT_SCORES["anticipated"] == 1.0
