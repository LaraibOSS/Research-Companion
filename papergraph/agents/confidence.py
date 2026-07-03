"""ConfidenceAgent: deterministic per-claim confidence score with uncertainty band.

Formula (design spec section 4): weighted mean of three signals -
verified evidence span (weight 1.0), novelty-comparison confidence (0.8),
citation health = verified/total references (0.6). Band half-width is
0.5/sqrt(n) + 0.5*stdev(values), clamped to [0.05, 0.5].
"""
from __future__ import annotations

import math

from papergraph.agents import events
from papergraph.agents.base import Agent, AgentContext, AgentResult

_WEIGHTS = (1.0, 0.8, 0.6)


def score_claim(
    evidence_verified: bool, novelty_confidence: float, citation_health: float,
) -> tuple[float, float]:
    values = (1.0 if evidence_verified else 0.3, novelty_confidence, citation_health)
    score = sum(v * w for v, w in zip(values, _WEIGHTS, strict=True)) / sum(_WEIGHTS)
    mean = sum(values) / len(values)
    stdev = math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))
    band = min(0.5, max(0.05, 0.5 / math.sqrt(len(values)) + 0.5 * stdev))
    return score, band


class ConfidenceAgent(Agent):
    name = "confidence"
    role = "Scores every claim with a confidence value and uncertainty band."
    depends_on = ("citation", "novelty")

    async def run(self, ctx: AgentContext) -> AgentResult:
        counts = ctx.data["citation"]["counts"]
        total = sum(counts.values()) or 1
        citation_health = counts.get("verified", 0) / total

        out = []
        for claim in ctx.data["novelty"]["claims"]:
            score, band = score_claim(
                bool(claim.get("evidence_verified")),
                float(claim.get("confidence", 0.0)),
                citation_health,
            )
            card = {
                "text": claim.get("text", ""),
                "score": round(score, 3),
                "band": round(band, 3),
                "signals": {
                    "evidence_verified": bool(claim.get("evidence_verified")),
                    "novelty_confidence": float(claim.get("confidence", 0.0)),
                    "citation_health": round(citation_health, 3),
                },
            }
            out.append(card)
            await ctx.bus.publish(events.Finding(
                agent=self.name, kind="confidence_card",
                summary=f"{card['score']:.2f} +/- {card['band']:.2f}  {card['text'][:70]}",
                data=card,
            ))
        return AgentResult(agent=self.name, ok=True, data={"claims": out})
