"""NoveltyAgent: extract claimed contributions, compare against prior art,
and verify every evidence quote against the paper's own fulltext.

The LLM is reached only through ctx.data["_llm"] (callable prompt -> raw text);
tests inject it, production falls back to the extract.py clients.
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import re

from papergraph.agents import events
from papergraph.agents.base import Agent, AgentContext, AgentResult


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip()


def _verify_quote(quote: str, fulltext: str) -> bool:
    """True iff the quote appears in the fulltext (exact or normalized)."""
    if not quote or not fulltext:
        return False
    return quote in fulltext or _normalize(quote) in _normalize(fulltext)


def _default_llm(prompt: str) -> str:
    from papergraph.extract import _call_anthropic, _call_openai, resolve_model

    provider = os.environ.get("PAPERGRAPH_PROVIDER", "anthropic")
    call = _call_openai if provider == "openai" else _call_anthropic
    text, _usage = call(prompt, model=resolve_model(provider, os.environ.get("PAPERGRAPH_MODEL")))
    return text


def _parse_json(raw: str, what: str) -> dict:
    from papergraph.extract import _strip_code_fences

    try:
        parsed = json.loads(_strip_code_fences(raw))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"novelty: LLM returned invalid JSON for {what}: {exc}") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError(f"novelty: LLM returned non-object JSON for {what}")
    return parsed


def _clamp_confidence(raw_value: object) -> float:
    """Coerce *raw_value* to a finite float in [0.0, 1.0]."""
    try:
        v = float(raw_value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(v):
        return 0.0
    return max(0.0, min(1.0, v))


class NoveltyAgent(Agent):
    name = "novelty"
    role = "Assesses each claimed contribution against prior art, with verified evidence."
    depends_on = ("priorart",)

    async def run(self, ctx: AgentContext) -> AgentResult:
        from papergraph.prompts import format_comparison_prompt, format_contribution_prompt
        from papergraph.store import PaperMetadata, load_text

        try:
            llm = ctx.data.get("_llm") or _default_llm
            meta = PaperMetadata.load(ctx.paper_id)
            title = meta.title if meta else ""
            fulltext = load_text(ctx.paper_id) or ""

            raw = await asyncio.to_thread(llm, format_contribution_prompt(title, fulltext[:20000]))
            parsed = _parse_json(raw, "contribution extraction")
            claims = parsed.get("claims", [])
            if not isinstance(claims, list):
                raise RuntimeError("novelty: 'claims' is not a list")

            prior = ctx.data.get("_priorart_papers") or []
            prior_block = "\n".join(
                f"{i}. {p.title} ({p.year}) - {p.abstract[:300]}" for i, p in enumerate(prior, 1)
            ) or "(no prior work found)"

            out_claims = []
            counts: dict[str, int] = {}
            buffered_findings: list[events.Finding] = []
            for c in claims:
                raw_cmp = await asyncio.to_thread(
                    llm, format_comparison_prompt(c.get("text", ""), prior_block)
                )
                cmp = _parse_json(raw_cmp, "comparison")
                verdict = cmp.get("verdict", "novel")
                entry = {
                    "text": c.get("text", ""),
                    "kind": c.get("kind", ""),
                    "verdict": verdict,
                    "confidence": _clamp_confidence(cmp.get("confidence", 0.0)),
                    "closest_prior": cmp.get("closest_prior", []),
                    "rationale": cmp.get("rationale", ""),
                    "evidence_verified": _verify_quote(c.get("evidence_quote", ""), fulltext),
                }
                out_claims.append(entry)
                counts[verdict] = counts.get(verdict, 0) + 1
                buffered_findings.append(events.Finding(
                    agent=self.name, kind="novelty_verdict",
                    summary=f"[{verdict}] {entry['text'][:80]}",
                    data=entry,
                ))

            # Publish all per-claim findings AFTER the loop completes successfully.
            for finding in buffered_findings:
                await ctx.bus.publish(finding)

            await ctx.bus.publish(events.Finding(
                agent=self.name, kind="novelty_report",
                summary=", ".join(f"{v}: {n}" for v, n in sorted(counts.items())) or "no claims",
                data={"counts": counts},
            ))
            return AgentResult(agent=self.name, ok=True,
                               data={"claims": out_claims, "counts": counts})
        except Exception as exc:
            return AgentResult(agent=self.name, ok=False, error=str(exc))
