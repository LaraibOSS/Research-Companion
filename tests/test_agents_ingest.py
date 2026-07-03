"""Tests for IngestAgent — loads extraction and builds the knowledge graph."""
from __future__ import annotations

import pytest

from papergraph import store
from papergraph.agents import events
from papergraph.agents.base import AgentContext
from papergraph.agents.bus import Bus
from papergraph.agents.ingest import IngestAgent
from papergraph.prompts import extraction_prompt_sha256


def _seed(paper_id="local:ingest0001", extraction=None):
    store.PaperMetadata(paper_id=paper_id, title="Seed Paper", authors=["A"]).save()
    store.save_extraction(
        paper_id,
        extraction or {"concepts": [{"name": "RAG", "definition": "d"}],
                       "methods": [], "datasets": [], "claims": [], "results": [],
                       "related_work": []},
        prompt_sha=extraction_prompt_sha256(),
    )
    return paper_id


@pytest.mark.asyncio
async def test_ingest_builds_graph_and_publishes_finding():
    paper_id = _seed()
    ctx = AgentContext(paper_id=paper_id, bus=Bus(), data={})
    result = await IngestAgent().run(ctx)
    assert result.ok
    assert result.data["graph_nodes"] > 0
    assert result.data["graph_edges"] >= 0
    assert "_graph" in ctx.data and "_extraction" in ctx.data
    assert any(isinstance(e, events.Finding) and e.kind == "graph_built"
               for e in ctx.bus.history)


@pytest.mark.asyncio
async def test_ingest_fails_cleanly_without_extraction():
    ctx = AgentContext(paper_id="local:doesnotexist", bus=Bus(), data={})
    result = await IngestAgent().run(ctx)
    assert not result.ok
    assert "papergraph build" in result.error
