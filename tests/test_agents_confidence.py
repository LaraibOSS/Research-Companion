"""Tests for ConfidenceAgent — fully deterministic, no LLM."""
from __future__ import annotations

import math

import pytest

from papergraph.agents import events
from papergraph.agents.base import AgentContext
from papergraph.agents.bus import Bus
from papergraph.agents.confidence import ConfidenceAgent, score_claim


def test_score_claim_formula_exact():
    # signals: evidence 1.0 (weight 1.0), novelty 0.8 (weight 0.8), citation 0.5 (weight 0.6)
    score, band = score_claim(True, 0.8, 0.5)
    vals = [1.0, 0.8, 0.5]
    weights = [1.0, 0.8, 0.6]
    expected = sum(v * w for v, w in zip(vals, weights, strict=True)) / sum(weights)
    assert math.isclose(score, expected)
    mean = sum(vals) / 3
    stdev = math.sqrt(sum((v - mean) ** 2 for v in vals) / 3)
    expected_band = min(0.5, max(0.05, 0.5 / math.sqrt(3) + 0.5 * stdev))
    assert math.isclose(band, expected_band)


def test_score_claim_unverified_evidence_scores_lower():
    hi, _ = score_claim(True, 0.9, 1.0)
    lo, _ = score_claim(False, 0.9, 1.0)
    assert lo < hi


def test_band_bounds():
    _, band = score_claim(True, 1.0, 1.0)
    assert 0.05 <= band <= 0.5


@pytest.mark.asyncio
async def test_confidence_agent_emits_card_per_claim():
    ctx = AgentContext(paper_id="local:x", bus=Bus(), data={})
    ctx.data["novelty"] = {"claims": [
        {"text": "claim A", "confidence": 0.8, "evidence_verified": True},
        {"text": "claim B", "confidence": 0.4, "evidence_verified": False},
    ]}
    ctx.data["citation"] = {"counts": {"verified": 3, "suspect": 1, "unverified": 0}}
    result = await ConfidenceAgent().run(ctx)
    assert result.ok
    assert len(result.data["claims"]) == 2
    a, b = result.data["claims"]
    assert a["score"] > b["score"]
    assert all(0.0 <= c["score"] <= 1.0 and 0.05 <= c["band"] <= 0.5
               for c in result.data["claims"])
    cards = [e for e in ctx.bus.history
             if isinstance(e, events.Finding) and e.kind == "confidence_card"]
    assert len(cards) == 2
