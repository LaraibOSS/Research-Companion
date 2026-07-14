"""ReproducibilityAgent: deterministic reproducibility / data-availability lane.

Thin blackboard wrapper around reproducibility.assess_reproducibility — no LLM,
so it runs in both fast and full review modes. Depends on citation so reference
links can be folded into the scan.
"""
from __future__ import annotations

from research_companion.agents import events
from research_companion.agents.base import Agent, AgentContext, AgentResult


class ReproducibilityAgent(Agent):
    name = "reproducibility"
    role = "Checks for public code/data, availability statements, and methods completeness."
    depends_on = ("ingest", "citation")

    async def run(self, ctx: AgentContext) -> AgentResult:
        from research_companion.reproducibility import assess_reproducibility
        from research_companion.store import load_text

        fulltext = load_text(ctx.paper_id) or ""
        references = (ctx.data.get("citation") or {}).get("references")
        result = assess_reproducibility(fulltext, references=references)

        await ctx.bus.publish(events.Finding(
            agent=self.name, kind="reproducibility",
            summary=(f"level={result['level']} · {len(result['code_links'])} code · "
                     f"{len(result['data_links'])} data links"),
            data={"level": result["level"], "missing": result["missing"]},
        ))
        return AgentResult(agent=self.name, ok=True, data=result)
