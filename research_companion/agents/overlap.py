"""OverlapAgent: deterministic near-duplicate lane (local library only).

Thin blackboard wrapper around overlap.near_duplicate_passages — no LLM, no
network, always-on in review. Compares the paper against the rest of the local
library and flags near-duplicate passages. The opt-in, consent-gated external
similarity check is deliberately NOT run here (see the `check-overlap --external`
CLI): the always-on review never sends text off the machine.
"""
from __future__ import annotations

from research_companion.agents import events
from research_companion.agents.base import Agent, AgentContext, AgentResult


class OverlapAgent(Agent):
    name = "overlap"
    role = "Flags passages that near-duplicate another paper in your local library."
    depends_on = ("ingest",)

    async def run(self, ctx: AgentContext) -> AgentResult:
        from research_companion.overlap import near_duplicate_passages
        from research_companion.store import list_papers, load_text

        target = load_text(ctx.paper_id) or ""
        corpus = [
            (p.paper_id, load_text(p.paper_id) or "")
            for p in list_papers()
            if p.paper_id != ctx.paper_id
        ]
        result = near_duplicate_passages(target, corpus)

        await ctx.bus.publish(events.Finding(
            agent=self.name, kind="overlap",
            summary=result["summary"]["text"],
            data={"n_passages": result["summary"]["n_passages"],
                  "papers": result["summary"]["papers"]},
        ))
        return AgentResult(agent=self.name, ok=True, data=result)
