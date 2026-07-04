"""Tests for TrackerAgent — one-shot new-related-work sweep."""
from __future__ import annotations

import pytest

from research_companion import store
from research_companion.agents import events
from research_companion.agents.base import AgentContext
from research_companion.agents.bus import Bus
from research_companion.agents.tracker import TrackerAgent
from research_companion.discover import DiscoveredPaper


def _paper(title, year=2025, arxiv_id="2501.00001"):
    return DiscoveredPaper(title=title, authors=["A"], year=year, citation_count=5,
                           arxiv_id=arxiv_id, doi=None, s2_id=None, url="")


@pytest.mark.asyncio
async def test_tracker_returns_new_papers_and_finding():
    store.PaperMetadata(paper_id="local:tr1", title="LLM Survey 2024", authors=[]).save()
    seen_queries: list[str] = []

    def fake_search(query):
        seen_queries.append(query)
        return [_paper("New LLM Work"), _paper("Recent Graph LLM", arxiv_id=None)]

    ctx = AgentContext(paper_id="local:tr1", bus=Bus(), data={})
    ctx.data["_extraction"] = {"concepts": [{"name": "LLM"}, {"name": "Graph"}, {"name": "RAG"}]}
    ctx.data["_search_recent"] = fake_search
    result = await TrackerAgent().run(ctx)

    assert result.ok
    assert result.data["count"] == 2
    assert len(result.data["new_papers"]) == 2
    assert result.data["new_papers"][0] == {"title": "New LLM Work", "year": 2025, "id": "2501.00001"}
    assert result.data["new_papers"][1] == {"title": "Recent Graph LLM", "year": 2025, "id": ""}
    # query includes title and top-3 concept names
    assert "LLM Survey 2024" in seen_queries[0]
    assert "LLM" in seen_queries[0]
    assert "Graph" in seen_queries[0]
    # Finding published on bus
    assert any(
        isinstance(e, events.Finding) and e.kind == "new_related_work"
        for e in ctx.bus.history
    )


@pytest.mark.asyncio
async def test_tracker_empty_results_still_ok():
    store.PaperMetadata(paper_id="local:tr2", title="T", authors=[]).save()
    ctx = AgentContext(paper_id="local:tr2", bus=Bus(), data={})
    ctx.data["_extraction"] = {"concepts": []}
    ctx.data["_search_recent"] = lambda q: []
    result = await TrackerAgent().run(ctx)
    assert result.ok
    assert result.data["count"] == 0
    assert result.data["new_papers"] == []
