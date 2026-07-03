"""Tests for NoveltyAgent — LLM injected, no network."""
from __future__ import annotations

import json

import pytest

from papergraph import store
from papergraph.agents import events
from papergraph.agents.base import AgentContext
from papergraph.agents.bus import Bus
from papergraph.agents.novelty import NoveltyAgent, _verify_quote
from papergraph.discover import DiscoveredPaper


def test_verify_quote_exact_and_normalized():
    text = "We propose GraphNov, a  graph-based novelty checker."
    assert _verify_quote("We propose GraphNov", text)
    assert _verify_quote("we PROPOSE graphnov,   a graph-based", text)
    assert not _verify_quote("completely absent claim", text)


def _fake_llm_factory():
    calls = []

    def _llm(prompt: str) -> str:
        calls.append(prompt)
        if '"claims"' in prompt:  # contribution extraction call
            return json.dumps({"claims": [
                {"text": "We propose GraphNov.", "kind": "method",
                 "evidence_quote": "We propose GraphNov"},
            ]})
        return json.dumps({"verdict": "overlaps", "confidence": 0.8,
                           "closest_prior": ["GraphRAG"], "rationale": "similar"})

    return _llm, calls


@pytest.mark.asyncio
async def test_novelty_extracts_compares_and_verifies():
    pid = "local:nov1"
    store.PaperMetadata(paper_id=pid, title="GraphNov Paper", authors=[]).save()
    store.save_text(pid, "In this paper We propose GraphNov, a graph novelty checker.")
    llm, calls = _fake_llm_factory()

    ctx = AgentContext(paper_id=pid, bus=Bus(), data={})
    ctx.data["_extraction"] = {"concepts": []}
    ctx.data["_priorart_papers"] = [DiscoveredPaper(
        title="GraphRAG", authors=[], year=2024, citation_count=1,
        arxiv_id=None, doi=None, s2_id=None, url="", abstract="graph rag abstract")]
    ctx.data["_llm"] = llm

    result = await NoveltyAgent().run(ctx)

    assert result.ok
    claim = result.data["claims"][0]
    assert claim["verdict"] == "overlaps"
    assert claim["closest_prior"] == ["GraphRAG"]
    assert claim["evidence_verified"] is True
    assert result.data["counts"] == {"overlaps": 1}
    assert len(calls) == 2  # one extraction + one comparison
    kinds = [e.kind for e in ctx.bus.history if isinstance(e, events.Finding)]
    assert kinds.count("novelty_verdict") == 1 and kinds.count("novelty_report") == 1


@pytest.mark.asyncio
async def test_novelty_unverified_quote_flagged():
    pid = "local:nov2"
    store.PaperMetadata(paper_id=pid, title="T", authors=[]).save()
    store.save_text(pid, "totally different body text")
    llm, _ = _fake_llm_factory()
    ctx = AgentContext(paper_id=pid, bus=Bus(), data={})
    ctx.data.update({"_extraction": {}, "_priorart_papers": [], "_llm": llm})
    result = await NoveltyAgent().run(ctx)
    assert result.ok
    assert result.data["claims"][0]["evidence_verified"] is False


@pytest.mark.asyncio
async def test_novelty_bad_llm_json_fails_cleanly():
    pid = "local:nov3"
    store.PaperMetadata(paper_id=pid, title="T", authors=[]).save()
    store.save_text(pid, "body")
    ctx = AgentContext(paper_id=pid, bus=Bus(), data={})
    ctx.data.update({"_extraction": {}, "_priorart_papers": [],
                     "_llm": lambda p: "NOT JSON AT ALL"})
    result = await NoveltyAgent().run(ctx)
    assert not result.ok
    assert "novelty" in result.error.lower() or "json" in result.error.lower()
