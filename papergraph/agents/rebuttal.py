"""RebuttalAgent: grounded point-by-point replies to reviewer concerns."""
from __future__ import annotations

import asyncio
from dataclasses import asdict

from papergraph.agents import events
from papergraph.agents.base import Agent, AgentContext, AgentResult


class RebuttalAgent(Agent):
    name = "rebuttal"
    role = "Drafts evidence-grounded responses to every reviewer concern."
    depends_on = ("ingest",)

    async def run(self, ctx: AgentContext) -> AgentResult:
        from papergraph.agents.novelty import _default_llm
        from papergraph.rebuttal.draft import draft_rebuttal
        from papergraph.rebuttal.segment import segment_reviews
        from papergraph.store import load_text

        concerns = ctx.data.get("_concerns")
        if concerns is None:
            reviews_text = ctx.data.get("_reviews_text", "")
            if not reviews_text.strip():
                return AgentResult(agent=self.name, ok=False,
                                   error="no reviews provided (use --reviews or --segments)")
            concerns = segment_reviews(reviews_text)
        if not concerns:
            return AgentResult(agent=self.name, ok=False, error="no concerns found in reviews")

        llm = ctx.data.get("_llm") or _default_llm
        tone = ctx.data.get("_tone", "balanced")
        fulltext = load_text(ctx.paper_id) or ""

        report = await asyncio.to_thread(draft_rebuttal, concerns, fulltext, llm, tone)
        for d in report.drafts:
            await ctx.bus.publish(events.Finding(
                agent=self.name, kind="rebuttal_draft",
                summary=f"{d.concern_id}: {'verified' if d.verified else 'CHECK quotes'}",
                data={"concern_id": d.concern_id, "verified": d.verified},
            ))
        await ctx.bus.publish(events.Finding(
            agent=self.name, kind="rebuttal_report",
            summary=f"{len(report.drafts)} draft(s), {len(report.changelog)} planned revision(s)",
            data={"drafts": len(report.drafts)},
        ))
        data = report.to_dict()
        data["concerns"] = [asdict(c) for c in concerns]
        return AgentResult(agent=self.name, ok=True, data=data)
