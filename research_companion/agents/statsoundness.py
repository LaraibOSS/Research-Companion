"""StatSoundnessAgent: deterministic statistical-soundness lane (Statcheck + GRIM).

Thin blackboard wrapper around statcheck.check_stats — no LLM, so it runs in both
fast and full review modes. Recomputes reported p-values from the test statistic
and df and checks reported means for arithmetic plausibility; every finding is a
*reporting inconsistency*, never a claim of error or misconduct.
"""
from __future__ import annotations

from research_companion.agents import events
from research_companion.agents.base import Agent, AgentContext, AgentResult


class StatSoundnessAgent(Agent):
    name = "statsoundness"
    role = "Recomputes reported p-values and checks reported means for arithmetic plausibility."
    depends_on = ("ingest",)

    async def run(self, ctx: AgentContext) -> AgentResult:
        from research_companion.statcheck import check_stats
        from research_companion.store import load_text

        result = check_stats(load_text(ctx.paper_id) or "")
        s = result["summary"]

        await ctx.bus.publish(events.Finding(
            agent=self.name, kind="statsoundness",
            summary=s["text"],
            data={
                "n_inconsistent": s["n_inconsistent"] + s["n_decision_inconsistent"],
                "n_decision_inconsistent": s["n_decision_inconsistent"],
                "n_impossible_means": s["n_impossible_means"],
            },
        ))
        return AgentResult(agent=self.name, ok=True, data=result)
