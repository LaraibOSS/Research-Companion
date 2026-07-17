"""Tests for PriorArtAgent — finds related work via scholarly search."""
from __future__ import annotations

import pytest

from research_companion import store
from research_companion.agents import events
from research_companion.agents.base import AgentContext
from research_companion.agents.bus import Bus
from research_companion.agents.priorart import PriorArtAgent
from research_companion.discover import DiscoveredPaper


def _paper(title, year=2024, arxiv_id="2401.00001"):
    return DiscoveredPaper(title=title, authors=["A"], year=year, citation_count=10,
                           arxiv_id=arxiv_id, doi=None, s2_id=None, url="")


@pytest.mark.asyncio
async def test_priorart_returns_related_papers_and_query_uses_concepts():
    store.PaperMetadata(paper_id="local:pa1", title="Graph RAG Survey", authors=[]).save()
    seen_queries = []

    def fake_search(query):
        seen_queries.append(query)
        return [_paper("GraphRAG"), _paper("LightRAG", arxiv_id=None)]

    ctx = AgentContext(paper_id="local:pa1", bus=Bus(), data={})
    ctx.data["_extraction"] = {"concepts": [{"name": "Knowledge graph"}, {"name": "RAG"}]}
    ctx.data["_search"] = fake_search
    result = await PriorArtAgent().run(ctx)

    assert result.ok
    assert result.data["count"] == 2
    assert result.data["papers"][0] == {"title": "GraphRAG", "year": 2024, "id": "2401.00001"}
    assert "Graph RAG Survey" in seen_queries[0]
    assert "Knowledge graph" in seen_queries[0]
    assert any(isinstance(e, events.Finding) and e.kind == "prior_art"
               for e in ctx.bus.history)


@pytest.mark.asyncio
async def test_priorart_empty_results_still_ok():
    store.PaperMetadata(paper_id="local:pa2", title="T", authors=[]).save()
    ctx = AgentContext(paper_id="local:pa2", bus=Bus(), data={})
    ctx.data["_extraction"] = {"concepts": []}
    ctx.data["_search"] = lambda q: []
    result = await PriorArtAgent().run(ctx)
    assert result.ok and result.data["count"] == 0


@pytest.mark.asyncio
async def test_priorart_stashes_full_papers_for_downstream():
    store.PaperMetadata(paper_id="local:pa3", title="T", authors=[]).save()
    ctx = AgentContext(paper_id="local:pa3", bus=Bus(), data={})
    ctx.data["_extraction"] = {"concepts": []}
    papers = [_paper("GraphRAG")]
    ctx.data["_search"] = lambda q: papers
    await PriorArtAgent().run(ctx)
    assert ctx.data["_priorart_papers"] is papers
