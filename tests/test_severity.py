"""Tests for the deterministic severity classifier (agents/severity.py)."""
from __future__ import annotations

from research_companion.agents.severity import (
    SEVERITY_RANK,
    rank_findings,
    summarize,
)


class TestRankFindingsEmpty:
    def test_all_none_is_empty(self):
        assert rank_findings() == []

    def test_empty_dicts_is_empty(self):
        assert rank_findings(novelty={}, citation={}, confidence={}) == []

    def test_verified_novel_claim_produces_no_finding(self):
        novelty = {"claims": [
            {"text": "A new method", "verdict": "novel", "evidence_verified": True}]}
        assert rank_findings(novelty=novelty) == []


class TestNoveltyFindings:
    def test_unsupported_novel_claim_is_major(self):
        novelty = {"claims": [
            {"text": "Claim X", "verdict": "novel", "evidence_verified": False}]}
        out = rank_findings(novelty=novelty)
        assert len(out) == 1
        assert out[0]["severity"] == "major"
        assert out[0]["category"] == "unsupported_claim"

    def test_unsupported_and_unoriginal_claim_escalates_to_critical(self):
        novelty = {"claims": [
            {"text": "Claim X", "verdict": "anticipated", "evidence_verified": False}]}
        out = rank_findings(novelty=novelty)
        cats = {(f["severity"], f["category"]) for f in out}
        # Both an unsupported-claim (critical) and a not-novel (major) finding.
        assert ("critical", "unsupported_claim") in cats
        assert ("major", "not_novel") in cats

    def test_verdict_tiers(self):
        for verdict, sev in [("anticipated", "major"), ("overlaps", "major"),
                             ("incremental", "minor")]:
            novelty = {"claims": [
                {"text": "C", "verdict": verdict, "evidence_verified": True}]}
            out = rank_findings(novelty=novelty)
            assert len(out) == 1
            assert out[0]["category"] == "not_novel"
            assert out[0]["severity"] == sev


class TestConfidenceFindings:
    def test_low_confidence_is_major(self):
        conf = {"claims": [{"text": "C", "score": 0.2}]}
        out = rank_findings(confidence=conf)
        assert out[0]["severity"] == "major"
        assert out[0]["category"] == "low_confidence"

    def test_moderate_confidence_is_minor(self):
        conf = {"claims": [{"text": "C", "score": 0.5}]}
        out = rank_findings(confidence=conf)
        assert out[0]["severity"] == "minor"

    def test_high_confidence_no_finding(self):
        conf = {"claims": [{"text": "C", "score": 0.9}]}
        assert rank_findings(confidence=conf) == []


class TestCitationFindings:
    def test_unverified_reference_is_major(self):
        cit = {"references": [
            {"title": "Ghost et al.", "status": "unverified", "reasons": ["not found"]}]}
        out = rank_findings(citation=cit)
        assert out[0]["severity"] == "major"
        assert out[0]["category"] == "unverified_reference"

    def test_suspect_reference_is_minor(self):
        cit = {"references": [
            {"title": "Foo", "status": "suspect", "reasons": ["year mismatch"]}]}
        out = rank_findings(citation=cit)
        assert out[0]["severity"] == "minor"

    def test_verified_reference_no_finding(self):
        cit = {"references": [{"title": "Real", "status": "verified", "reasons": []}]}
        assert rank_findings(citation=cit) == []


class TestOrderingAndSummary:
    def _mixed(self):
        return rank_findings(
            novelty={"claims": [
                {"text": "unsupported+overlap", "verdict": "overlaps",
                 "evidence_verified": False},          # critical + major
                {"text": "incremental", "verdict": "incremental",
                 "evidence_verified": True}]},          # minor
            citation={"references": [
                {"title": "ghost", "status": "unverified"},   # major
                {"title": "fuzzy", "status": "suspect"}]},    # minor
            confidence={"claims": [{"text": "lowconf", "score": 0.1}]},  # major
        )

    def test_sorted_most_severe_first_with_ranks(self):
        out = self._mixed()
        severities = [f["severity"] for f in out]
        weights = [SEVERITY_RANK[s] for s in severities]
        assert weights == sorted(weights), severities
        assert [f["rank"] for f in out] == list(range(len(out)))
        assert out[0]["severity"] == "critical"

    def test_summarize_counts(self):
        counts = summarize(self._mixed())
        assert counts == {"critical": 1, "major": 3, "minor": 2}
