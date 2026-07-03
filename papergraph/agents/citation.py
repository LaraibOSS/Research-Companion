"""CitationAgent: validate the paper's bibliography against live scholarly databases."""
from __future__ import annotations

import asyncio

from papergraph.agents import events
from papergraph.agents.base import Agent, AgentContext, AgentResult


class CitationAgent(Agent):
    name = "citation"
    role = "Verifies every reference against CrossRef/OpenAlex; flags fabricated citations."
    depends_on = ("ingest",)

    async def run(self, ctx: AgentContext) -> AgentResult:
        from papergraph.refcheck.parse import references_from_extraction
        from papergraph.refcheck.retrieval import default_lookup
        from papergraph.refcheck.validate import validate_bibliography

        ext = ctx.data["_extraction"]
        refs = references_from_extraction(ext)
        lookup = ctx.data.get("_lookup") or default_lookup()
        report = await asyncio.to_thread(validate_bibliography, refs, lookup)

        for ref, verdict in report.entries:
            if verdict.status != "verified":
                await ctx.bus.publish(events.Finding(
                    agent=self.name, kind="bad_reference",
                    summary=f"[{verdict.status}] {ref.title}",
                    data={"title": ref.title, "status": verdict.status,
                          "reasons": verdict.reasons},
                ))
        counts = report.counts()
        ref_list = [
            {"title": ref.title, "status": v.status, "reasons": v.reasons}
            for ref, v in report.entries
        ]
        await ctx.bus.publish(events.Finding(
            agent=self.name, kind="citation_report",
            summary=(f"{counts['verified']} verified · {counts['suspect']} suspect · "
                     f"{counts['unverified']} unverified"),
            data={"counts": counts, "references": ref_list[:50]},
        ))
        return AgentResult(agent=self.name, ok=True, data={
            "counts": counts,
            "references": ref_list,
        })
