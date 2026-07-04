"""Tests for BenchmarkAgent — deterministic graph mining, no LLM/network."""
from __future__ import annotations

import networkx as nx
import pytest

from research_companion.agents import events
from research_companion.agents.base import AgentContext
from research_companion.agents.benchmark import BenchmarkAgent
from research_companion.agents.bus import Bus
from research_companion.discover import DiscoveredPaper


def _paper(title, abstract):
    return DiscoveredPaper(title=title, authors=[], year=2024, citation_count=1,
                           arxiv_id=None, doi=None, s2_id=None, url="", abstract=abstract)


@pytest.mark.asyncio
async def test_benchmark_ranks_datasets_by_prior_art_mentions_then_degree():
    G = nx.Graph()
    G.add_node("d1", kind="dataset", label="HotpotQA")
    G.add_node("d2", kind="dataset", label="MuSiQue")
    G.add_node("p1", kind="paper", label="P1")
    G.add_edge("p1", "d1")
    G.add_edge("p1", "d2")
    G.add_node("c1", kind="concept", label="RAG")
    G.add_edge("c1", "d1")  # d1 degree 2, d2 degree 1

    ctx = AgentContext(paper_id="local:b1", bus=Bus(), data={})
    ctx.data["_graph"] = G
    ctx.data["_priorart_papers"] = [
        _paper("A", "evaluated on MuSiQue and MuSiQue again"),
        _paper("B", "we test on MuSiQue"),
        _paper("C", "uses HotpotQA"),
    ]
    result = await BenchmarkAgent().run(ctx)
    assert result.ok
    names = [s["name"] for s in result.data["suggestions"]]
    # MuSiQue mentioned in 2 prior papers > HotpotQA in 1 (degree breaks ties only)
    assert names[0] == "MuSiQue" and names[1] == "HotpotQA"
    assert result.data["suggestions"][0]["prior_art_mentions"] == 2
    assert any(isinstance(e, events.Finding) and e.kind == "benchmarks"
               for e in ctx.bus.history)


@pytest.mark.asyncio
async def test_benchmark_no_datasets_is_ok_and_empty():
    ctx = AgentContext(paper_id="local:b2", bus=Bus(), data={})
    ctx.data["_graph"] = nx.Graph()
    ctx.data["_priorart_papers"] = []
    result = await BenchmarkAgent().run(ctx)
    assert result.ok and result.data["suggestions"] == []
