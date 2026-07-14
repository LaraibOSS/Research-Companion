"""VenueFitAgent: judge whether a paper matches a target venue's scope.

Scope/venue mismatch is a leading desk-rejection cause. The agent runs a
two-stage check: a deterministic topic-overlap prefilter (venues.topic_overlap)
grounds an LLM verdict comparing the paper's abstract + contributions against the
venue scope. normalize_verdict() is the pure coercion of the LLM output into a
stable result shape and is unit-tested without any LLM.
"""
from __future__ import annotations

import asyncio
import math

from research_companion.agents import events
from research_companion.agents.base import Agent, AgentContext, AgentResult

VALID_FITS = ("strong", "moderate", "weak", "out_of_scope")
# Fits that should warn the author of desk-rejection risk.
_RISKY_FITS = {"weak", "out_of_scope"}


def _clamp01(raw: object) -> float:
    try:
        v = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(v):
        return 0.0
    return max(0.0, min(1.0, v))


def _str_list(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(x).strip() for x in raw if str(x).strip()]


def normalize_verdict(
    raw: dict, *, venue_slug: str, venue_name: str, overlap: float,
    discipline: str = "general", checklists: tuple[str, ...] = (),
) -> dict:
    """Coerce a raw LLM venue-fit response into a stable, JSON-safe verdict.

    Unknown/missing ``fit`` values fall back to "out_of_scope". ``overlap`` is
    the deterministic topic_overlap prefilter carried through for transparency;
    ``discipline`` and ``checklists`` come from the venue KB entry.
    """
    fit = raw.get("fit", "")
    if fit not in VALID_FITS:
        fit = "out_of_scope"
    return {
        "venue": venue_slug,
        "venue_name": venue_name,
        "discipline": discipline,
        "fit": fit,
        "confidence": round(_clamp01(raw.get("confidence", 0.0)), 3),
        "topic_overlap": round(float(overlap), 3),
        "rationale": str(raw.get("rationale", "")),
        "reasons": _str_list(raw.get("reasons")),
        "checklists": list(checklists),
        "suggested_alternatives": _str_list(raw.get("suggested_alternatives")),
        "desk_reject_risk": fit in _RISKY_FITS,
    }


def _requirements_block(venue) -> str:
    """Render a venue's checklists + desk-reject rules for the prompt."""
    lines: list[str] = []
    if venue.checklists:
        lines.append("Reporting checklists: " + "; ".join(venue.checklists))
    if venue.desk_reject_rules:
        lines.append("Common desk-reject triggers:")
        lines.extend(f"- {r}" for r in venue.desk_reject_rules)
    return "\n".join(lines) or "(none specified)"


def _contributions(ctx_data: dict, extraction: dict) -> list[str]:
    """Prefer the novelty lane's claim texts; fall back to extraction claims."""
    nov = ctx_data.get("novelty") or {}
    contribs = [str(c.get("text", "")) for c in nov.get("claims", []) if isinstance(c, dict)]
    if not any(contribs):
        contribs = [
            c.get("text", "") if isinstance(c, dict) else str(c)
            for c in extraction.get("claims", [])
        ]
    return [c for c in contribs if c]


class VenueFitAgent(Agent):
    name = "venuefit"
    role = "Checks whether the paper's scope matches the target venue."
    depends_on = ("ingest",)

    async def run(self, ctx: AgentContext) -> AgentResult:
        from research_companion.agents.novelty import _default_llm, _parse_json
        from research_companion.prompts import format_venuefit_prompt
        from research_companion.store import PaperMetadata, load_text
        from research_companion.venues import get_venue, suggest_alternatives, topic_overlap

        slug = ctx.data.get("_venue")
        if not slug:
            return AgentResult(agent=self.name, ok=True,
                               data={"skipped": True, "reason": "no target venue specified"})
        venue = get_venue(slug)
        if venue is None:
            return AgentResult(agent=self.name, ok=True,
                               data={"skipped": True, "reason": f"unknown venue: {slug}"})

        try:
            meta = PaperMetadata.load(ctx.paper_id)
            title = meta.title if meta else ""
            abstract = (meta.abstract if meta else "") or (load_text(ctx.paper_id) or "")[:1500]
            ext = ctx.data.get("_extraction") or {}
            concept_names = [str(c.get("name", "")) for c in ext.get("concepts", [])]
            contribs = _contributions(ctx.data, ext)
            contributions_block = "\n".join(f"- {c}" for c in contribs[:10]) or \
                "(no explicit contributions extracted)"

            paper_terms = [title, abstract, *concept_names, *contribs]
            overlap = topic_overlap(paper_terms, venue)

            llm = ctx.data.get("_llm") or _default_llm
            raw = await asyncio.to_thread(llm, format_venuefit_prompt(
                venue_name=venue.name, venue_scope=venue.scope,
                requirements_block=_requirements_block(venue),
                abstract=abstract[:2000], contributions_block=contributions_block))
            parsed = _parse_json(raw, "venue fit")
            verdict = normalize_verdict(
                parsed, venue_slug=venue.slug, venue_name=venue.name, overlap=overlap,
                discipline=venue.discipline, checklists=venue.checklists)

            # For a risky fit, if the model offered no alternatives, suggest
            # in-discipline peers ranked by topic overlap with the paper.
            if verdict["desk_reject_risk"] and not verdict["suggested_alternatives"]:
                verdict["suggested_alternatives"] = suggest_alternatives(venue, paper_terms)

            await ctx.bus.publish(events.Finding(
                agent=self.name, kind="venue_fit",
                summary=f"[{verdict['fit']}] {venue.name} (overlap {overlap:.2f})",
                data=verdict))
            return AgentResult(agent=self.name, ok=True, data=verdict)
        except Exception as exc:
            return AgentResult(agent=self.name, ok=False, error=str(exc))
