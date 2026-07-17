"""PriorArtAgent: find and map related work for the paper."""
from __future__ import annotations

import asyncio

from research_companion.agents import events
from research_companion.agents.base import Agent, AgentContext, AgentResult


class PriorArtAgent(Agent):
    name = "priorart"
    role = "Searches scholarly databases for related work relevant to the paper."
    depends_on = ("ingest",)

    async def run(self, ctx: AgentContext) -> AgentResult:
        from research_companion.discover import search_topic_with_fallback
        from research_companion.store import PaperMetadata

        meta = PaperMetadata.load(ctx.paper_id)
        title = meta.title if meta else ""
        concepts = [c.get("name", "") for c in ctx.data["_extraction"].get("concepts", [])]
        query = " ".join([title] + [c for c in concepts[:3] if c]).strip()

        search = ctx.data.get("_search") or (lambda q: search_topic_with_fallback(q, limit=15))
        found = await asyncio.to_thread(search, query)
        ctx.data["_priorart_papers"] = found
        papers = [
            {"title": p.title, "year": p.year,
             "id": p.arxiv_id or p.doi or p.s2_id or ""}
            for p in found
        ]
        await ctx.bus.publish(events.Finding(
            agent=self.name, kind="prior_art",
            summary=f"{len(papers)} related papers found",
            data={"count": len(papers)},
        ))
        return AgentResult(agent=self.name, ok=True,
                           data={"count": len(papers), "papers": papers})
