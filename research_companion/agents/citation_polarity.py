"""CitationPolarityAgent: classify the paper's stance toward each cited work,
grounded by a verbatim evidence quote. LLM only via ctx.data['_llm']."""
from __future__ import annotations

import asyncio

from research_companion.agents import events
from research_companion.agents.base import Agent, AgentContext, AgentResult
from research_companion.agents.novelty import _default_llm, _parse_json, _verify_quote

_ALLOWED = {"based_on", "support", "contrast", "refutation", "mention"}


class CitationPolarityAgent(Agent):
    name = "citation_polarity"
    role = "Types each citation by the paper's stance (based-on/support/contrast/refutation/mention), grounded in verbatim evidence."
    depends_on = ("ingest",)

    async def run(self, ctx: AgentContext) -> AgentResult:
        from research_companion.prompts import format_citation_polarity_prompt
        from research_companion.store import (
            PaperMetadata,
            load_text,
            save_citation_polarity,
        )

        ext = ctx.data.get("_extraction") or {}
        cites = [str(c).strip() for c in ext.get("related_work", []) if str(c).strip()]
        if not cites:
            return AgentResult(agent=self.name, ok=True, data={"citations": [], "counts": {}})

        meta = PaperMetadata.load(ctx.paper_id)
        title = (meta.title if meta else "") or (ext.get("paper_meta", {}) or {}).get("title", "")
        fulltext = load_text(ctx.paper_id) or ""

        llm = ctx.data.get("_llm") or _default_llm
        raw = await asyncio.to_thread(llm, format_citation_polarity_prompt(title, fulltext[:20000], cites))
        parsed = _parse_json(raw, "citation polarity")
        returned = {str(c.get("cite", "")): c for c in parsed.get("citations", []) if isinstance(c, dict)}

        out = []
        for cite in cites:
            item = returned.get(cite) or {}
            polarity = item.get("polarity", "mention")
            quote = item.get("evidence_quote", "") or ""
            verified = bool(quote) and _verify_quote(quote, fulltext)
            if polarity not in _ALLOWED or not verified:
                polarity, verified = "mention", verified if polarity == "mention" else False
            out.append({"cite": cite, "polarity": polarity, "evidence_quote": quote,
                        "rationale": item.get("rationale", ""), "verified": verified})

        counts: dict[str, int] = {}
        for c in out:
            counts[c["polarity"]] = counts.get(c["polarity"], 0) + 1
        save_citation_polarity(ctx.paper_id, {c["cite"]: {"polarity": c["polarity"], "verified": c["verified"]} for c in out})

        await ctx.bus.publish(events.Finding(
            agent=self.name, kind="citation_polarity",
            summary=" · ".join(f"{k}:{v}" for k, v in sorted(counts.items())) or "no citations",
            data={"counts": counts},
        ))
        return AgentResult(agent=self.name, ok=True, data={"citations": out, "counts": counts})
