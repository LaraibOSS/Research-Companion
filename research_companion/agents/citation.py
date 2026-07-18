"""CitationAgent: validate the paper's bibliography against live scholarly databases."""
from __future__ import annotations

import asyncio

from research_companion.agents import events
from research_companion.agents.base import Agent, AgentContext, AgentResult


class CitationAgent(Agent):
    name = "citation"
    role = "Verifies every reference against CrossRef/OpenAlex; reports each as verified, suspect, or unverified."
    depends_on = ("ingest",)

    async def run(self, ctx: AgentContext) -> AgentResult:
        from research_companion.agents.venuefit import _contributions
        from research_companion.nudge import connectors_nudge
        from research_companion.refcheck.parse import references_from_extraction
        from research_companion.refcheck.retrieval import default_lookup
        from research_companion.refcheck.validate import validate_bibliography
        from research_companion.settings import get_settings
        from research_companion.store import PaperMetadata, load_text
        from research_companion.venues import infer_discipline

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
        nudge = None
        try:
            enabled = set(get_settings().get("connectors") or [])
            meta = PaperMetadata.load(ctx.paper_id)
            title = meta.title if meta else ""
            abstract = (meta.abstract if meta else "") or (load_text(ctx.paper_id) or "")[:1500]
            concept_names = [str(c.get("name", "")) for c in ext.get("concepts", [])]
            contribs = _contributions(ctx.data, ext)
            paper_terms = [title, abstract, *concept_names, *contribs]
            discipline = infer_discipline(paper_terms)[0]
            nudge = connectors_nudge(refs, enabled=enabled, discipline=discipline,
                                      n_unverified=counts["unverified"])
        except Exception:
            nudge = None

        return AgentResult(agent=self.name, ok=True, data={
            "counts": counts,
            "references": ref_list,
            "connectors_nudge": nudge,
        })
