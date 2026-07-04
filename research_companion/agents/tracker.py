"""TrackerAgent: one-shot sweep for new related work published recently.

Scheduled / watch mode (polling on a cron) is explicitly future work.
"""
from __future__ import annotations

import asyncio

from research_companion.agents import events
from research_companion.agents.base import Agent, AgentContext, AgentResult


class TrackerAgent(Agent):
    name = "tracker"
    role = "Sweeps recent publications for new related work on the paper's topics."
    depends_on = ("ingest",)

    async def run(self, ctx: AgentContext) -> AgentResult:
        from datetime import datetime

        from research_companion.discover import search_topic
        from research_companion.store import PaperMetadata

        meta = PaperMetadata.load(ctx.paper_id)
        title = meta.title if meta else ""
        concepts = [c.get("name", "") for c in ctx.data["_extraction"].get("concepts", [])]
        query = " ".join([title] + [c for c in concepts[:3] if c]).strip()

        search = ctx.data.get("_search_recent") or (
            lambda q: search_topic(q, limit=10, year_min=datetime.now().year - 1)
        )
        found = await asyncio.to_thread(search, query)

        new_papers = [
            {
                "title": p.title,
                "year": p.year,
                "id": p.arxiv_id or p.doi or p.s2_id or "",
            }
            for p in found
        ]
        await ctx.bus.publish(events.Finding(
            agent=self.name,
            kind="new_related_work",
            summary=f"{len(new_papers)} new related papers found",
            data={"count": len(new_papers)},
        ))
        return AgentResult(
            agent=self.name,
            ok=True,
            data={"count": len(new_papers), "new_papers": new_papers},
        )
