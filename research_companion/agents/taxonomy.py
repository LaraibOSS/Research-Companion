"""TaxonomyAgent: group the retrieved prior-art set into labeled clusters."""
from __future__ import annotations

import asyncio

from research_companion.agents import events
from research_companion.agents.base import Agent, AgentContext, AgentResult


def _pid(p) -> str:
    return getattr(p, "arxiv_id", None) or getattr(p, "doi", None) or getattr(p, "s2_id", None) or ""


class TaxonomyAgent(Agent):
    name = "taxonomy"
    role = "Groups retrieved prior art into a labeled taxonomy of themes."
    depends_on = ("priorart",)

    async def run(self, ctx: AgentContext) -> AgentResult:
        from research_companion.taxonomy import build_taxonomy

        prior = ctx.data.get("_priorart_papers") or []
        papers = [{"title": getattr(p, "title", ""), "abstract": getattr(p, "abstract", ""),
                   "year": getattr(p, "year", None), "id": _pid(p)} for p in prior]
        llm = ctx.data.get("_llm")  # None -> keyword labels; never fabricate a default here
        groups = await asyncio.to_thread(build_taxonomy, papers, llm=llm)

        await ctx.bus.publish(events.Finding(
            agent=self.name, kind="taxonomy",
            summary=f"{len(groups)} prior-art group(s)",
            data={"count": len(groups)},
        ))
        return AgentResult(agent=self.name, ok=True, data={"groups": groups, "count": len(groups)})
