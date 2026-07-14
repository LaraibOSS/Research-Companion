"""Tests for the venue-fit prompt + pure verdict normalization + agent."""
from __future__ import annotations

import json

import pytest

from research_companion import store
from research_companion.agents import events
from research_companion.agents.base import AgentContext
from research_companion.agents.bus import Bus
from research_companion.agents.venuefit import (
    VALID_FITS,
    VenueFitAgent,
    normalize_verdict,
)
from research_companion.prompts import format_venuefit_prompt, venuefit_prompt_sha256


class TestPrompt:
    def test_placeholders_substituted(self):
        p = format_venuefit_prompt(
            venue_name="NeurIPS", venue_scope="ML scope",
            requirements_block="Reporting checklists: X",
            abstract="We do X.", contributions_block="- C1")
        assert "NeurIPS" in p and "ML scope" in p
        assert "We do X." in p and "- C1" in p
        assert "Reporting checklists: X" in p
        assert "<<" not in p  # every placeholder replaced

    def test_sha_stable_and_hex(self):
        sha = venuefit_prompt_sha256()
        assert len(sha) == 64
        assert sha == venuefit_prompt_sha256()


class TestNormalizeVerdict:
    def _raw(self, **kw):
        base = {"fit": "strong", "confidence": 0.8, "rationale": "fits well",
                "reasons": ["on-topic"], "suggested_alternatives": []}
        base.update(kw)
        return base

    def test_happy_path(self):
        v = normalize_verdict(self._raw(), venue_slug="neurips",
                              venue_name="NeurIPS", overlap=0.66,
                              discipline="machine_learning",
                              checklists=("NeurIPS Paper Checklist",))
        assert v["fit"] == "strong"
        assert v["venue"] == "neurips" and v["venue_name"] == "NeurIPS"
        assert v["discipline"] == "machine_learning"
        assert v["checklists"] == ["NeurIPS Paper Checklist"]
        assert v["confidence"] == 0.8
        assert v["topic_overlap"] == 0.66
        assert v["reasons"] == ["on-topic"]
        assert v["desk_reject_risk"] is False

    def test_defaults_when_kb_fields_omitted(self):
        v = normalize_verdict(self._raw(), venue_slug="x", venue_name="X", overlap=0.0)
        assert v["discipline"] == "general"
        assert v["checklists"] == []

    def test_unknown_fit_falls_back_to_out_of_scope(self):
        v = normalize_verdict(self._raw(fit="perfect"), venue_slug="x",
                              venue_name="X", overlap=0.0)
        assert v["fit"] == "out_of_scope"
        assert v["desk_reject_risk"] is True

    def test_all_valid_fits_pass_through(self):
        for fit in VALID_FITS:
            v = normalize_verdict(self._raw(fit=fit), venue_slug="x",
                                  venue_name="X", overlap=0.5)
            assert v["fit"] == fit

    def test_confidence_clamped(self):
        assert normalize_verdict(self._raw(confidence=5.0), venue_slug="x",
                                 venue_name="X", overlap=0)["confidence"] == 1.0
        assert normalize_verdict(self._raw(confidence="bad"), venue_slug="x",
                                 venue_name="X", overlap=0)["confidence"] == 0.0

    def test_weak_and_out_of_scope_flag_risk(self):
        for fit in ("weak", "out_of_scope"):
            v = normalize_verdict(self._raw(fit=fit), venue_slug="x",
                                  venue_name="X", overlap=0.1)
            assert v["desk_reject_risk"] is True

    def test_non_list_fields_coerced(self):
        v = normalize_verdict(
            {"fit": "moderate", "reasons": "nope", "suggested_alternatives": None},
            venue_slug="x", venue_name="X", overlap=0.3)
        assert v["reasons"] == []
        assert v["suggested_alternatives"] == []


class TestVenueFitAgent:
    @pytest.mark.asyncio
    async def test_skips_when_no_venue(self):
        ctx = AgentContext(paper_id="local:v0", bus=Bus(), data={})
        result = await VenueFitAgent().run(ctx)
        assert result.ok and result.data["skipped"] is True

    @pytest.mark.asyncio
    async def test_skips_unknown_venue(self):
        ctx = AgentContext(paper_id="local:v0", bus=Bus(),
                           data={"_venue": "no-such-venue"})
        result = await VenueFitAgent().run(ctx)
        assert result.ok and result.data["skipped"] is True
        assert "unknown venue" in result.data["reason"]

    @pytest.mark.asyncio
    async def test_happy_path_with_injected_llm(self):
        pid = "local:vf1"
        store.PaperMetadata(paper_id=pid, title="A deep learning method",
                            authors=[], abstract="We train a neural network.").save()
        store.save_text(pid, "We train a neural network for representation learning.")

        captured = {}

        def _llm(prompt: str) -> str:
            captured["prompt"] = prompt
            return json.dumps({"fit": "strong", "confidence": 0.9,
                               "rationale": "on-topic", "reasons": ["deep learning"],
                               "suggested_alternatives": []})

        ctx = AgentContext(paper_id=pid, bus=Bus(), data={
            "_venue": "iclr", "_llm": _llm,
            "_extraction": {"concepts": [{"name": "representation learning"}],
                            "claims": []},
        })
        result = await VenueFitAgent().run(ctx)

        assert result.ok
        assert result.data["fit"] == "strong"
        assert result.data["venue"] == "iclr"
        assert result.data["discipline"] == "machine_learning"
        assert result.data["checklists"]  # KB checklists surfaced
        assert result.data["topic_overlap"] > 0.0  # ICLR topics present
        assert "ICLR" in captured["prompt"]
        assert "desk-reject" in captured["prompt"].lower()  # requirements block present
        kinds = [e.kind for e in ctx.bus.history if isinstance(e, events.Finding)]
        assert "venue_fit" in kinds

    @pytest.mark.asyncio
    async def test_risky_fit_fills_in_discipline_alternatives(self):
        pid = "local:vf3"
        store.PaperMetadata(paper_id=pid, title="A deep learning study",
                            authors=[], abstract="We train neural networks.").save()
        store.save_text(pid, "deep learning representation optimization")

        def _llm(prompt: str) -> str:
            # Weak fit, and the model offers NO alternatives.
            return json.dumps({"fit": "weak", "confidence": 0.6,
                               "rationale": "borderline", "reasons": [],
                               "suggested_alternatives": []})

        ctx = AgentContext(paper_id=pid, bus=Bus(), data={
            "_venue": "neurips", "_llm": _llm,
            "_extraction": {"concepts": [{"name": "deep learning"}], "claims": []}})
        result = await VenueFitAgent().run(ctx)

        assert result.ok and result.data["desk_reject_risk"] is True
        # Agent backfilled in-discipline (ML) alternatives.
        assert result.data["suggested_alternatives"]
        assert "NeurIPS" not in result.data["suggested_alternatives"]

    @pytest.mark.asyncio
    async def test_bad_llm_json_fails_lane(self):
        pid = "local:vf2"
        store.PaperMetadata(paper_id=pid, title="T", authors=[]).save()
        store.save_text(pid, "body")
        ctx = AgentContext(paper_id=pid, bus=Bus(), data={
            "_venue": "neurips", "_llm": lambda p: "not json",
            "_extraction": {"concepts": [], "claims": []}})
        result = await VenueFitAgent().run(ctx)
        assert result.ok is False and result.error
