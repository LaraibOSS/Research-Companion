"""End-to-end test for `papergraph review` — all network injected, no LLM."""
from __future__ import annotations

import json

import pytest

from papergraph import cli, store
from papergraph.discover import DiscoveredPaper
from papergraph.prompts import extraction_prompt_sha256


def _seed():
    paper_id = "local:review00001"
    store.PaperMetadata(paper_id=paper_id, title="Graph RAG Survey", authors=["A"]).save()
    store.save_extraction(
        paper_id,
        {"concepts": [{"name": "RAG", "definition": "d"}], "methods": [], "datasets": [],
         "claims": [], "results": [],
         "related_work": ["Attention Is All You Need", "A Fabricated Paper Title"]},
        prompt_sha=extraction_prompt_sha256(),
    )
    return paper_id


def _overrides():
    def lookup(ref):
        if "attention" in ref.title.lower():
            return {"title": ref.title, "authors": [], "year": 2017,
                    "doi": None, "arxiv_id": None}
        return None

    def search(query):
        return [DiscoveredPaper(title="GraphRAG", authors=[], year=2024, citation_count=5,
                                arxiv_id="2404.00001", doi=None, s2_id=None, url="")]

    def llm(prompt):
        if '"evidence_quote"' in prompt:
            return json.dumps({"claims": []})
        return json.dumps({"verdict": "novel", "confidence": 0.9,
                           "closest_prior": [], "rationale": "r"})

    return {"_lookup": lookup, "_search": search, "_llm": llm}


def test_review_cli_runs_all_agents(monkeypatch: pytest.MonkeyPatch, capsys):
    paper_id = _seed()
    monkeypatch.setattr(cli, "REVIEW_CONTEXT_OVERRIDES", _overrides())
    rc = cli.main(["review", paper_id])
    out = capsys.readouterr().out
    assert rc == 0
    for lane in ("ingest", "citation", "priorart"):
        assert lane in out
    assert "1 verified" in out and "1 unverified" in out
    assert "1 related papers" in out


def test_review_cli_json(monkeypatch: pytest.MonkeyPatch, capsys):
    paper_id = _seed()
    monkeypatch.setattr(cli, "REVIEW_CONTEXT_OVERRIDES", _overrides())
    rc = cli.main(["review", paper_id, "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["paper_id"] == paper_id
    assert payload["agents"]["citation"]["ok"] is True
    assert payload["agents"]["citation"]["data"]["counts"]["verified"] == 1


def test_review_cli_fails_without_extraction(capsys):
    rc = cli.main(["review", "local:nothere"])
    assert rc == 1
    out = capsys.readouterr().out
    assert "FAILED" in out


def _full_overrides():
    ov = _overrides()

    def llm(prompt):
        if '"evidence_quote"' in prompt:
            return json.dumps({"claims": [{"text": "We propose X.", "kind": "method",
                                           "evidence_quote": "We propose X"}]})
        return json.dumps({"verdict": "novel", "confidence": 0.9,
                           "closest_prior": [], "rationale": "r"})

    ov["_llm"] = llm
    return ov


def test_review_cli_full_pipeline_six_lanes(monkeypatch: pytest.MonkeyPatch, capsys):
    paper_id = _seed()
    store.save_text(paper_id, "Body. We propose X here.")
    monkeypatch.setattr(cli, "REVIEW_CONTEXT_OVERRIDES", _full_overrides())
    rc = cli.main(["review", paper_id])
    out = capsys.readouterr().out
    assert rc == 0
    for lane in ("ingest", "citation", "priorart", "novelty", "confidence", "benchmark"):
        assert lane in out


def test_review_cli_fast_skips_llm_lanes(monkeypatch: pytest.MonkeyPatch, capsys):
    paper_id = _seed()
    monkeypatch.setattr(cli, "REVIEW_CONTEXT_OVERRIDES", _overrides())
    rc = cli.main(["review", paper_id, "--fast"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "novelty" not in out and "confidence" not in out
