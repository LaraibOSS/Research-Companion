"""PriorArtAgent: find and map related work for the paper."""
from __future__ import annotations

from papergraph.agents import events
from papergraph.agents.base import Agent, AgentContext, AgentResult


class PriorArtAgent(Agent):
    name = "priorart"
    role = "Searches scholarly databases for related work and maps it onto the graph."
    depends_on = ("ingest",)

    async def run(self, ctx: AgentContext) -> AgentResult:
        from papergraph.discover import search_topic
        from papergraph.store import PaperMetadata

        meta = PaperMetadata.load(ctx.paper_id)
        title = meta.title if meta else ""
        concepts = [c.get("name", "") for c in ctx.data["_extraction"].get("concepts", [])]
        query = " ".join([title] + [c for c in concepts[:3] if c]).strip()

        search = ctx.data.get("_search") or (lambda q: search_topic(q, limit=15))
        found = search(query)
        papers = [
            {"title": p.title, "year": p.year,
             "id": p.arxiv_id or p.doi or p.s2_id or ""}
            for p in found
        ]
        await ctx.bus.publish(events.Finding(
            agent=self.name, kind="prior_art",
            summary=f"{len(papers)} related papers mapped",
            data={"count": len(papers)},
        ))
        return AgentResult(agent=self.name, ok=True,
                           data={"count": len(papers), "papers": papers})
