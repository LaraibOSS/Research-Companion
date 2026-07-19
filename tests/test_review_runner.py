"""run_review: programmatic, read-only review -> report dict (offline seams)."""
from __future__ import annotations

import asyncio
import json

from research_companion import store
from research_companion.discover import DiscoveredPaper
from research_companion.prompts import extraction_prompt_sha256
from research_companion.review_runner import run_review


def _seed_paper():
    paper_id = "local:runner00001"
    store.PaperMetadata(paper_id=paper_id, title="Graph RAG Survey", authors=["A"]).save()
    store.save_extraction(
        paper_id,
        {"concepts": [{"name": "RAG", "definition": "d"}], "methods": [], "datasets": [],
         "claims": [], "results": [],
         "related_work": ["Attention Is All You Need", "A Fabricated Paper Title"]},
        prompt_sha=extraction_prompt_sha256(),
    )
    return paper_id


def _fake_lookup(ref):
    if "attention" in ref.title.lower():
        return {"title": ref.title, "authors": [], "year": 2017,
                "doi": None, "arxiv_id": None}
    return None


def _fake_search(query):
    return [DiscoveredPaper(title="GraphRAG", authors=[], year=2024, citation_count=5,
                            arxiv_id="2404.00001", doi=None, s2_id=None, url="")]


def _fake_llm(prompt):
    if '"evidence_quote"' in prompt:
        return json.dumps({"claims": []})
    return json.dumps({"verdict": "novel", "confidence": 0.9,
                       "closest_prior": [], "rationale": "r"})


def test_run_review_returns_report_dict(monkeypatch, tmp_path):
    paper_id = _seed_paper()
    saved = []
    monkeypatch.setattr("research_companion.store.save_review_report",
                        lambda pid, rep: saved.append(pid))
    report = run_review(paper_id, fast=False, llm=_fake_llm, lookup=_fake_lookup,
                        search=_fake_search)
    assert report["paper_id"] == paper_id
    assert "lanes" in report and report["lanes"]
    assert "citation" in report["lanes"]
    assert report.get("readiness")  # deterministic readiness rides in via build_report_json
    assert saved == []              # READ-ONLY: never persists
    json.dumps(report)              # JSON-safe end to end


def test_run_review_fast_skips_llm_lanes(monkeypatch):
    paper_id = _seed_paper()

    def _boom(prompt):
        raise AssertionError("llm must not be called in fast mode")
    report = run_review(paper_id, fast=True, llm=_boom, lookup=_fake_lookup,
                        search=_fake_search)
    assert "novelty" not in report["lanes"]
    assert "citation" in report["lanes"]


def test_run_review_works_inside_running_event_loop(monkeypatch):
    # FastMCP executes tools inside an async server; the runner must not crash
    # with "asyncio.run() cannot be called from a running event loop".
    paper_id = _seed_paper()

    async def _call():
        return run_review(paper_id, fast=True, lookup=_fake_lookup, search=_fake_search)

    report = asyncio.run(_call())
    assert report["paper_id"] == paper_id
