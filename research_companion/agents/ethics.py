"""EthicsAgent: deterministic integrity-declaration lane.

Thin blackboard wrapper around ethics.detect_declarations — no LLM, runs in both
fast and full review modes.
"""
from __future__ import annotations

from research_companion.agents import events
from research_companion.agents.base import Agent, AgentContext, AgentResult


class EthicsAgent(Agent):
    name = "ethics"
    role = "Checks for funding, conflict-of-interest, ethics, and consent declarations."
    depends_on = ("ingest",)

    async def run(self, ctx: AgentContext) -> AgentResult:
        from research_companion.ethics import detect_declarations
        from research_companion.store import load_text

        result = detect_declarations(load_text(ctx.paper_id) or "")

        await ctx.bus.publish(events.Finding(
            agent=self.name, kind="ethics_declarations",
            summary=(f"{len(result['present'])} present · "
                     f"{len(result['missing_expected'])} expected-but-missing"),
            data={"present": result["present"],
                  "missing_expected": result["missing_expected"]},
        ))
        return AgentResult(agent=self.name, ok=True, data=result)
