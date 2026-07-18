import asyncio

from research_companion.agents.base import AgentContext
from research_companion.agents.bus import Bus
from research_companion.agents.taxonomy import TaxonomyAgent


class _P:
    def __init__(self, title, abstract, year, arxiv_id=None):
        self.title, self.abstract, self.year = title, abstract, year
        self.arxiv_id, self.doi, self.s2_id = arxiv_id, None, None

def test_groups_prior_art_without_llm():
    prior = [_P("Graph retrieval", "graph retrieval", 2020, "1"),
             _P("Graph ranking retrieval", "graph retrieval ranking", 2021, "2"),
             _P("Protein folding", "protein folding", 2019, "3")]
    ctx = AgentContext(paper_id="p", bus=Bus(), data={"_priorart_papers": prior})
    res = asyncio.run(TaxonomyAgent().run(ctx))
    assert res.ok
    ids = sorted(p["id"] for g in res.data["groups"] for p in g["papers"])
    assert ids == ["1", "2", "3"]

def test_empty_prior_art_ok():
    ctx = AgentContext(paper_id="p", bus=Bus(), data={"_priorart_papers": []})
    res = asyncio.run(TaxonomyAgent().run(ctx))
    assert res.ok and res.data["groups"] == []
