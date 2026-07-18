"""ComplianceAgent: deterministic desk-reject compliance lane (venue-gated)."""
from __future__ import annotations

from research_companion.agents import events
from research_companion.agents.base import Agent, AgentContext, AgentResult


class ComplianceAgent(Agent):
    name = "compliance"
    role = ("Checks the paper against the target venue's submission rules "
            "(page limit, required sections, anonymization, citations).")
    depends_on = ("ingest",)

    async def run(self, ctx: AgentContext) -> AgentResult:
        from research_companion.compliance import check_compliance
        from research_companion.refcheck.parse import references_from_extraction
        from research_companion.sections import Section, build_section_tree
        from research_companion.store import (
            PaperMetadata,
            load_sections,
            load_text,
            pdf_page_count,
        )
        from research_companion.venues import get_venue

        venue = get_venue(ctx.data.get("_venue") or "")
        if venue is None:
            return AgentResult(agent=self.name, ok=True, data={"checks": [], "counts": {}})

        fulltext = load_text(ctx.paper_id) or ""

        # store.load_sections() returns a persisted payload dict
        # ({"sections": [...plain dicts...], ...}) or None (missing/stale
        # cache) — never a bare list of Section objects. check_compliance
        # needs real Section objects (it reads `.title`), so convert the
        # payload's plain dicts into Section instances; when there's no
        # cached payload at all, build fresh from the fulltext instead.
        raw = load_sections(ctx.paper_id)
        sections: list[Section] | None = None
        if isinstance(raw, dict):
            try:
                sections = [Section(**s) for s in raw.get("sections", [])]
            except TypeError:
                sections = None
        if not sections and fulltext:
            try:
                sections = build_section_tree(fulltext)
            except Exception:
                sections = None

        meta = PaperMetadata.load(ctx.paper_id)
        abstract = meta.abstract if meta else ""
        ext = ctx.data.get("_extraction")
        references = references_from_extraction(ext) if ext else None
        page_count = pdf_page_count(ctx.paper_id)

        result = check_compliance(
            venue, fulltext=fulltext, sections=sections, abstract=abstract,
            references=references, page_count=page_count)

        await ctx.bus.publish(events.Finding(
            agent=self.name, kind="compliance",
            summary=f"{result['counts'].get('desk_reject', 0)} desk-reject · "
                    f"{result['counts'].get('warning', 0)} warning",
            data={"counts": result["counts"]},
        ))
        return AgentResult(agent=self.name, ok=True, data=result)
