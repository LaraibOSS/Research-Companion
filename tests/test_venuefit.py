"""Tests for the venue-fit prompt + pure verdict normalization."""
from __future__ import annotations

from research_companion.agents.venuefit import VALID_FITS, normalize_verdict
from research_companion.prompts import format_venuefit_prompt, venuefit_prompt_sha256


class TestPrompt:
    def test_placeholders_substituted(self):
        p = format_venuefit_prompt(
            venue_name="NeurIPS", venue_scope="ML scope",
            abstract="We do X.", contributions_block="- C1")
        assert "NeurIPS" in p and "ML scope" in p
        assert "We do X." in p and "- C1" in p
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
                              venue_name="NeurIPS", overlap=0.66)
        assert v["fit"] == "strong"
        assert v["venue"] == "neurips" and v["venue_name"] == "NeurIPS"
        assert v["confidence"] == 0.8
        assert v["topic_overlap"] == 0.66
        assert v["reasons"] == ["on-topic"]
        assert v["desk_reject_risk"] is False

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
