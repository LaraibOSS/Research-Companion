"""Tests for research_companion.suggestions — deterministic suggestions engine.

All fixtures are hand-built from the real lane/alignment payload shapes.
Tests are written RED before implementation (strict TDD).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_str() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _report(*, citation_refs=None, novelty_claims=None, confidence_claims=None,
            benchmark_suggestions=None):
    """Build a minimal review-report dict matching report.build_report_json shape."""
    lanes: dict = {}
    if citation_refs is not None:
        lanes["citation"] = {
            "ok": True,
            "error": "",
            "data": {
                "counts": {
                    "verified": sum(1 for r in citation_refs if r.get("status") == "verified"),
                    "unverified": sum(1 for r in citation_refs if r.get("status") == "unverified"),
                    "suspect": sum(1 for r in citation_refs if r.get("status") == "suspect"),
                },
                "references": citation_refs,
            },
        }
    if novelty_claims is not None:
        lanes["novelty"] = {
            "ok": True,
            "error": "",
            "data": {"claims": novelty_claims},
        }
    if confidence_claims is not None:
        lanes["confidence"] = {
            "ok": True,
            "error": "",
            "data": {"claims": confidence_claims},
        }
    if benchmark_suggestions is not None:
        lanes["benchmark"] = {
            "ok": True,
            "error": "",
            "data": {"suggestions": benchmark_suggestions},
        }
    return {
        "paper_id": "local:draft0001",
        "title": "Test Draft",
        "lanes": lanes,
        "generated_by": "research-companion",
    }


def _alignment(*, candidate_paper_id="local:cand0001", sections=None):
    """Build a minimal alignment payload matching alignment.py canonical shape."""
    return {
        "version": 1,
        "draft_paper_id": "local:draft0001",
        "candidate_paper_id": candidate_paper_id,
        "prompt_sha256": "abc123",
        "computed_at": _now_str(),
        "score": 0.6,
        "band": 0.1,
        "verdict": "medium",
        "signals": {"quote_verification": 0.5, "llm_relevance": 0.6, "lexical_overlap": 0.4},
        "sections": sections or [],
    }


# ---------------------------------------------------------------------------
# 1. Citation lane rules
# ---------------------------------------------------------------------------

class TestCitationRules:
    def test_unverified_ref_generates_high_citation_suggestion(self):
        from research_companion.suggestions import generate_suggestions
        report = _report(citation_refs=[
            {"title": "Smith et al. 2023", "status": "unverified"},
        ])
        result = generate_suggestions(draft_id="local:draft0001", report=report, alignments=[])
        sugs = result["suggestions"]
        assert any(
            s["kind"] == "citation"
            and s["severity"] == "high"
            and "Smith et al. 2023" in s["title"]
            for s in sugs
        ), f"no high citation suggestion found in: {[s['title'] for s in sugs]}"

    def test_suspect_ref_generates_medium_citation_suggestion(self):
        from research_companion.suggestions import generate_suggestions
        report = _report(citation_refs=[
            {"title": "Jones 2022", "status": "suspect"},
        ])
        result = generate_suggestions(draft_id="local:draft0001", report=report, alignments=[])
        sugs = result["suggestions"]
        assert any(
            s["kind"] == "citation"
            and s["severity"] == "medium"
            and "Jones 2022" in s["title"]
            for s in sugs
        )

    def test_verified_ref_generates_no_suggestion(self):
        from research_companion.suggestions import generate_suggestions
        report = _report(citation_refs=[
            {"title": "Good Ref", "status": "verified"},
        ])
        result = generate_suggestions(draft_id="local:draft0001", report=report, alignments=[])
        sugs = result["suggestions"]
        assert not any(s["kind"] == "citation" for s in sugs)

    def test_citation_source_type_is_lane(self):
        from research_companion.suggestions import generate_suggestions
        report = _report(citation_refs=[{"title": "A Ref", "status": "unverified"}])
        result = generate_suggestions(draft_id="local:draft0001", report=report, alignments=[])
        sugs = [s for s in result["suggestions"] if s["kind"] == "citation"]
        assert sugs[0]["source"]["type"] == "lane"
        assert sugs[0]["source"]["lane"] == "citation"


# ---------------------------------------------------------------------------
# 2. Novelty lane rules
# ---------------------------------------------------------------------------

class TestNoveltyRules:
    def test_overlaps_verdict_generates_high_novelty(self):
        from research_companion.suggestions import generate_suggestions
        report = _report(novelty_claims=[
            {"text": "We propose X", "verdict": "overlaps", "evidence_verified": True,
             "confidence": 0.8, "closest_prior": ["Prior A"]},
        ])
        result = generate_suggestions(draft_id="local:draft0001", report=report, alignments=[])
        sugs = result["suggestions"]
        assert any(s["kind"] == "novelty" and s["severity"] == "high" for s in sugs)

    def test_anticipated_verdict_generates_high_novelty(self):
        from research_companion.suggestions import generate_suggestions
        report = _report(novelty_claims=[
            {"text": "We propose Y", "verdict": "anticipated", "evidence_verified": True,
             "confidence": 0.8},
        ])
        result = generate_suggestions(draft_id="local:draft0001", report=report, alignments=[])
        sugs = result["suggestions"]
        assert any(s["kind"] == "novelty" and s["severity"] == "high" for s in sugs)

    def test_incremental_verdict_generates_medium_novelty(self):
        from research_companion.suggestions import generate_suggestions
        report = _report(novelty_claims=[
            {"text": "We extend Z", "verdict": "incremental", "evidence_verified": True,
             "confidence": 0.7},
        ])
        result = generate_suggestions(draft_id="local:draft0001", report=report, alignments=[])
        sugs = result["suggestions"]
        assert any(s["kind"] == "novelty" and s["severity"] == "medium" for s in sugs)

    def test_novel_verdict_generates_no_novelty_suggestion(self):
        from research_companion.suggestions import generate_suggestions
        report = _report(novelty_claims=[
            {"text": "Truly new claim", "verdict": "novel", "evidence_verified": True,
             "confidence": 0.9},
        ])
        result = generate_suggestions(draft_id="local:draft0001", report=report, alignments=[])
        sugs = result["suggestions"]
        assert not any(s["kind"] == "novelty" for s in sugs)

    def test_evidence_not_verified_generates_evidence_medium(self):
        from research_companion.suggestions import generate_suggestions
        report = _report(novelty_claims=[
            {"text": "Unverified claim", "verdict": "novel", "evidence_verified": False,
             "confidence": 0.8},
        ])
        result = generate_suggestions(draft_id="local:draft0001", report=report, alignments=[])
        sugs = result["suggestions"]
        assert any(s["kind"] == "evidence" and s["severity"] == "medium" for s in sugs)

    def test_novelty_detail_mentions_closest_prior(self):
        from research_companion.suggestions import generate_suggestions
        report = _report(novelty_claims=[
            {"text": "Our method", "verdict": "overlaps", "evidence_verified": True,
             "confidence": 0.8, "closest_prior": ["Prior Work Title"]},
        ])
        result = generate_suggestions(draft_id="local:draft0001", report=report, alignments=[])
        sugs = [s for s in result["suggestions"] if s["kind"] == "novelty"]
        assert any("Prior Work Title" in s["detail"] for s in sugs)

    def test_novelty_source_type_is_lane(self):
        from research_companion.suggestions import generate_suggestions
        report = _report(novelty_claims=[
            {"text": "Overlap claim", "verdict": "overlaps", "evidence_verified": True,
             "confidence": 0.8},
        ])
        result = generate_suggestions(draft_id="local:draft0001", report=report, alignments=[])
        sugs = [s for s in result["suggestions"] if s["kind"] == "novelty"]
        assert sugs[0]["source"]["type"] == "lane"
        assert sugs[0]["source"]["lane"] == "novelty"


# ---------------------------------------------------------------------------
# 3. Confidence lane rules
# ---------------------------------------------------------------------------

class TestConfidenceRules:
    def test_score_below_0_3_generates_evidence_high(self):
        from research_companion.suggestions import generate_suggestions
        report = _report(confidence_claims=[
            {"text": "Low confidence claim", "score": 0.2, "band": 0.05},
        ])
        result = generate_suggestions(draft_id="local:draft0001", report=report, alignments=[])
        sugs = result["suggestions"]
        assert any(s["kind"] == "evidence" and s["severity"] == "high" for s in sugs)

    def test_score_exactly_0_3_generates_evidence_medium(self):
        from research_companion.suggestions import generate_suggestions
        report = _report(confidence_claims=[
            {"text": "Boundary claim 0.3", "score": 0.3, "band": 0.05},
        ])
        result = generate_suggestions(draft_id="local:draft0001", report=report, alignments=[])
        sugs = result["suggestions"]
        assert any(s["kind"] == "evidence" and s["severity"] == "medium" for s in sugs)

    def test_score_below_0_5_generates_evidence_medium(self):
        from research_companion.suggestions import generate_suggestions
        report = _report(confidence_claims=[
            {"text": "Medium confidence", "score": 0.4, "band": 0.05},
        ])
        result = generate_suggestions(draft_id="local:draft0001", report=report, alignments=[])
        sugs = result["suggestions"]
        assert any(s["kind"] == "evidence" and s["severity"] == "medium" for s in sugs)

    def test_score_0_5_or_above_no_suggestion(self):
        from research_companion.suggestions import generate_suggestions
        report = _report(confidence_claims=[
            {"text": "High confidence claim", "score": 0.5, "band": 0.05},
        ])
        result = generate_suggestions(draft_id="local:draft0001", report=report, alignments=[])
        sugs = result["suggestions"]
        assert not any(s["kind"] == "evidence" for s in sugs)


# ---------------------------------------------------------------------------
# 4. Benchmark lane rules
# ---------------------------------------------------------------------------

class TestBenchmarkRules:
    def test_benchmark_suggestion_generates_low(self):
        from research_companion.suggestions import generate_suggestions
        report = _report(benchmark_suggestions=[
            {"name": "MMLU", "graph_degree": 5, "prior_art_mentions": 2},
        ])
        result = generate_suggestions(draft_id="local:draft0001", report=report, alignments=[])
        sugs = result["suggestions"]
        assert any(
            s["kind"] == "benchmark"
            and s["severity"] == "low"
            and "MMLU" in s["title"]
            for s in sugs
        )


# ---------------------------------------------------------------------------
# 5. Alignment rules
# ---------------------------------------------------------------------------

class TestAlignmentRules:
    def test_challenges_relevance_0_7_generates_evidence_high(self):
        from research_companion.suggestions import generate_suggestions
        alignment = _alignment(sections=[
            {"section_id": "s2", "section_title": "Methods", "relation": "challenges",
             "relevance": 0.7, "rationale": "Contradicts.", "evidence": []},
        ])
        result = generate_suggestions(
            draft_id="local:draft0001", report=_report(), alignments=[alignment]
        )
        sugs = result["suggestions"]
        assert any(
            s["kind"] == "evidence"
            and s["severity"] == "high"
            and s["section_id"] == "s2"
            for s in sugs
        )

    def test_challenges_relevance_0_5_generates_evidence_medium(self):
        from research_companion.suggestions import generate_suggestions
        alignment = _alignment(sections=[
            {"section_id": "s3", "section_title": "Results", "relation": "challenges",
             "relevance": 0.5, "rationale": "Challenges results.", "evidence": []},
        ])
        result = generate_suggestions(
            draft_id="local:draft0001", report=_report(), alignments=[alignment]
        )
        sugs = result["suggestions"]
        assert any(
            s["kind"] == "evidence"
            and s["severity"] == "medium"
            and s["section_id"] == "s3"
            for s in sugs
        )

    def test_challenges_relevance_below_0_5_no_suggestion(self):
        from research_companion.suggestions import generate_suggestions
        alignment = _alignment(sections=[
            {"section_id": "s1", "section_title": "Intro", "relation": "challenges",
             "relevance": 0.4, "rationale": "Low relevance.", "evidence": []},
        ])
        result = generate_suggestions(
            draft_id="local:draft0001", report=_report(), alignments=[alignment]
        )
        sugs = result["suggestions"]
        assert not any(s["kind"] == "evidence" and s["section_id"] == "s1" for s in sugs)

    def test_alternative_relevance_0_5_generates_related_work_medium(self):
        from research_companion.suggestions import generate_suggestions
        alignment = _alignment(candidate_paper_id="local:cand0002", sections=[
            {"section_id": "s4", "section_title": "Related Work", "relation": "alternative",
             "relevance": 0.5, "rationale": "Alternative view.", "evidence": []},
        ])
        result = generate_suggestions(
            draft_id="local:draft0001", report=_report(), alignments=[alignment]
        )
        sugs = result["suggestions"]
        assert any(
            s["kind"] == "related_work"
            and s["severity"] == "medium"
            and "local:cand0002" in s["title"]
            for s in sugs
        )

    def test_alignment_source_type_is_paper(self):
        from research_companion.suggestions import generate_suggestions
        alignment = _alignment(candidate_paper_id="local:cand0003", sections=[
            {"section_id": "s2", "section_title": "Methods", "relation": "challenges",
             "relevance": 0.6, "rationale": "Challenges methods.", "evidence": []},
        ])
        result = generate_suggestions(
            draft_id="local:draft0001", report=_report(), alignments=[alignment]
        )
        sugs = [s for s in result["suggestions"] if s["kind"] == "evidence"]
        assert sugs[0]["source"]["type"] == "paper"
        assert sugs[0]["source"]["paper_id"] == "local:cand0003"

    def test_challenges_section_id_set_on_suggestion(self):
        from research_companion.suggestions import generate_suggestions
        alignment = _alignment(sections=[
            {"section_id": "s5", "section_title": "Experiments", "relation": "challenges",
             "relevance": 0.65, "rationale": "Challenges experiments.", "evidence": []},
        ])
        result = generate_suggestions(
            draft_id="local:draft0001", report=_report(), alignments=[alignment]
        )
        sugs = [s for s in result["suggestions"] if s["kind"] == "evidence"]
        assert sugs[0]["section_id"] == "s5"

    def test_challenges_title_matches_spec_template(self):
        """Title must be 'Strengthen §<section_title> against challenge from <label>'."""
        from research_companion.suggestions import generate_suggestions
        alignment = _alignment(candidate_paper_id="local:cand0099", sections=[
            {"section_id": "s2", "section_title": "Methods", "relation": "challenges",
             "relevance": 0.7, "rationale": "Contradicts.", "evidence": []},
        ])
        result = generate_suggestions(
            draft_id="local:draft0001", report=_report(), alignments=[alignment]
        )
        sugs = [s for s in result["suggestions"] if s["kind"] == "evidence"
                and s["section_id"] == "s2"]
        assert len(sugs) == 1
        title = sugs[0]["title"]
        assert title.startswith("Strengthen §"), f"title={title!r}"
        assert "Methods" in title
        assert "challenge from" in title

    def test_alternative_title_matches_spec_template(self):
        """Title must be 'Discuss <label> as an alternative in related work'."""
        from research_companion.suggestions import generate_suggestions
        alignment = _alignment(candidate_paper_id="local:cand0088", sections=[
            {"section_id": "s4", "section_title": "Related Work", "relation": "alternative",
             "relevance": 0.6, "rationale": "Alternative view.", "evidence": []},
        ])
        result = generate_suggestions(
            draft_id="local:draft0001", report=_report(), alignments=[alignment]
        )
        sugs = [s for s in result["suggestions"] if s["kind"] == "related_work"]
        assert len(sugs) == 1
        title = sugs[0]["title"]
        assert title.startswith("Discuss "), f"title={title!r}"
        assert title.endswith("as an alternative in related work"), f"title={title!r}"

    def test_alignment_title_uses_paper_title_when_metadata_loadable(self):
        """When paper metadata is available, title uses the paper's title, not the id."""
        from research_companion import store
        from research_companion.suggestions import generate_suggestions

        paper_id = "local:cand_with_meta"
        meta = store.PaperMetadata(
            paper_id=paper_id,
            title="The Important Paper",
            authors=["Author A"],
            added_at="2024-01-01T00:00:00Z",
        )
        meta.save()

        alignment = _alignment(candidate_paper_id=paper_id, sections=[
            {"section_id": "s2", "section_title": "Discussion", "relation": "challenges",
             "relevance": 0.7, "rationale": "Contradicts.", "evidence": []},
        ])
        result = generate_suggestions(
            draft_id="local:draft0001", report=_report(), alignments=[alignment]
        )
        sugs = [s for s in result["suggestions"] if s["kind"] == "evidence"
                and s["section_id"] == "s2"]
        assert len(sugs) == 1
        title = sugs[0]["title"]
        # Should use "The Important Paper" as the label, not the paper_id
        assert "The Important Paper" in title, f"expected paper title in: {title!r}"


# ---------------------------------------------------------------------------
# 6. Gaps rules
# ---------------------------------------------------------------------------

class TestGapsRules:
    def test_relevant_unaddressed_gap_generates_medium_gap(self):
        from research_companion.suggestions import generate_suggestions
        gaps = [{"gap_id": "g1", "statement": "Gap in coverage", "relevant": True,
                 "addressed_by_draft": False}]
        result = generate_suggestions(
            draft_id="local:draft0001", report=_report(), alignments=[], gaps=gaps
        )
        sugs = result["suggestions"]
        assert any(s["kind"] == "gap" and s["severity"] == "medium" for s in sugs)

    def test_addressed_gap_not_generated(self):
        from research_companion.suggestions import generate_suggestions
        gaps = [{"gap_id": "g2", "statement": "Already addressed", "relevant": True,
                 "addressed_by_draft": True}]
        result = generate_suggestions(
            draft_id="local:draft0001", report=_report(), alignments=[], gaps=gaps
        )
        sugs = result["suggestions"]
        assert not any(s["kind"] == "gap" for s in sugs)

    def test_irrelevant_gap_not_generated(self):
        from research_companion.suggestions import generate_suggestions
        gaps = [{"gap_id": "g3", "statement": "Not relevant", "relevant": False,
                 "addressed_by_draft": False}]
        result = generate_suggestions(
            draft_id="local:draft0001", report=_report(), alignments=[], gaps=gaps
        )
        sugs = result["suggestions"]
        assert not any(s["kind"] == "gap" for s in sugs)

    def test_gaps_none_is_ignored(self):
        from research_companion.suggestions import generate_suggestions
        result = generate_suggestions(
            draft_id="local:draft0001", report=_report(), alignments=[], gaps=None
        )
        assert "suggestions" in result


# ---------------------------------------------------------------------------
# 7. Confidence + novelty dedup — same claim keeps higher severity
# ---------------------------------------------------------------------------

class TestDedup:
    def test_confidence_high_and_novelty_evidence_medium_same_claim_keeps_high(self):
        """score<0.3 fires confidence evidence high; evidence_verified=False fires novelty evidence medium.
        Dedup on same claim text (source_key) keeps the single higher-severity suggestion."""
        from research_companion.suggestions import generate_suggestions
        claim_text = "Our method is superior"
        report = _report(
            novelty_claims=[
                {"text": claim_text, "verdict": "novel", "evidence_verified": False,
                 "confidence": 0.25},
            ],
            confidence_claims=[
                {"text": claim_text, "score": 0.25, "band": 0.05},
            ],
        )
        result = generate_suggestions(draft_id="local:draft0001", report=report, alignments=[])
        evidence_sugs = [s for s in result["suggestions"] if s["kind"] == "evidence"]
        # Should be exactly ONE evidence suggestion for this claim (dedup)
        assert len(evidence_sugs) == 1, (
            f"expected 1 evidence suggestion, got {len(evidence_sugs)}: "
            f"{[(s['title'], s['severity']) for s in evidence_sugs]}"
        )
        assert evidence_sugs[0]["severity"] == "high"


# ---------------------------------------------------------------------------
# 8. ID stability
# ---------------------------------------------------------------------------

class TestIdStability:
    def test_same_inputs_same_ids(self):
        from research_companion.suggestions import generate_suggestions
        report = _report(citation_refs=[{"title": "Smith 2023", "status": "unverified"}])
        r1 = generate_suggestions(draft_id="local:draft0001", report=report, alignments=[])
        r2 = generate_suggestions(draft_id="local:draft0001", report=report, alignments=[])
        ids1 = {s["id"] for s in r1["suggestions"]}
        ids2 = {s["id"] for s in r2["suggestions"]}
        assert ids1 == ids2

    def test_title_case_spacing_change_same_id(self):
        """_norm strips case/spaces, so case-only title changes must not change ID."""
        from research_companion.suggestions import _make_sug_id
        id1 = _make_sug_id("citation", "Smith 2023", "Unverified citation: Smith 2023")
        id2 = _make_sug_id("citation", "Smith 2023", "UNVERIFIED CITATION:  SMITH   2023")
        assert id1 == id2

    def test_id_format_prefix(self):
        from research_companion.suggestions import _make_sug_id
        sid = _make_sug_id("citation", "source_key_here", "Some Title")
        assert sid.startswith("sug_")
        assert len(sid) == len("sug_") + 12

    def test_alignment_source_key_includes_relation(self):
        """source_key with relation differs from source_key without relation."""
        from research_companion.suggestions import _make_sug_id
        id_with = _make_sug_id("evidence", "local:cand0001:s2:challenges", "Some Title")
        id_without = _make_sug_id("evidence", "local:cand0001:s2", "Some Title")
        assert id_with != id_without


# ---------------------------------------------------------------------------
# 9. Merge semantics
# ---------------------------------------------------------------------------

class TestMerge:
    def test_dismissed_survives_regeneration(self):
        from research_companion.suggestions import dismiss_suggestion, generate_suggestions
        report = _report(citation_refs=[{"title": "Survive Ref", "status": "unverified"}])
        r1 = generate_suggestions(draft_id="local:draft0001", report=report, alignments=[])
        sug_id = r1["suggestions"][0]["id"]
        dismiss_suggestion(sug_id)

        r2 = generate_suggestions(draft_id="local:draft0001", report=report, alignments=[])
        sugs_by_id = {s["id"]: s for s in r2["suggestions"]}
        assert sug_id in sugs_by_id
        assert sugs_by_id[sug_id]["status"] == "dismissed"

    def test_open_item_removed_from_report_becomes_auto_addressed(self):
        from research_companion.suggestions import generate_suggestions
        report_with = _report(citation_refs=[{"title": "Temp Ref", "status": "unverified"}])
        r1 = generate_suggestions(draft_id="local:draft0001", report=report_with, alignments=[])
        sug_id = r1["suggestions"][0]["id"]
        assert any(s["id"] == sug_id and s["status"] == "open" for s in r1["suggestions"])

        report_without = _report()
        r2 = generate_suggestions(draft_id="local:draft0001", report=report_without, alignments=[])
        sugs_by_id = {s["id"]: s for s in r2["suggestions"]}
        assert sug_id in sugs_by_id
        gone = sugs_by_id[sug_id]
        assert gone["status"] == "addressed"
        assert gone["addressed_by"]["by"] == "auto"
        assert gone["addressed_by"]["note"] == "no longer detected"

    def test_auto_addressed_reopens_when_reappears(self):
        """An auto-addressed suggestion that reappears in the fresh set reopens as open."""
        from research_companion.suggestions import generate_suggestions
        report = _report(citation_refs=[{"title": "Flapping Ref", "status": "unverified"}])
        r1 = generate_suggestions(draft_id="local:draft0001", report=report, alignments=[])
        sug_id = r1["suggestions"][0]["id"]
        # Run 2 — absent → auto-addressed
        generate_suggestions(draft_id="local:draft0001", report=_report(), alignments=[])
        # Run 3 — present again
        r3 = generate_suggestions(draft_id="local:draft0001", report=report, alignments=[])
        sugs_by_id = {s["id"]: s for s in r3["suggestions"]}
        assert sugs_by_id[sug_id]["status"] == "open"

    def test_user_dismissed_never_reopens(self):
        """User-dismissed suggestions stay dismissed even if cause reappears."""
        from research_companion.suggestions import dismiss_suggestion, generate_suggestions
        report = _report(citation_refs=[{"title": "Persistent Ref", "status": "unverified"}])
        r1 = generate_suggestions(draft_id="local:draft0001", report=report, alignments=[])
        sug_id = r1["suggestions"][0]["id"]
        dismiss_suggestion(sug_id)
        r2 = generate_suggestions(draft_id="local:draft0001", report=report, alignments=[])
        sugs_by_id = {s["id"]: s for s in r2["suggestions"]}
        assert sugs_by_id[sug_id]["status"] == "dismissed"


# ---------------------------------------------------------------------------
# 10. LLM structure pass
# ---------------------------------------------------------------------------

class TestStructurePass:
    def _fake_llm_5_proposals(self, prompt: str) -> str:
        return json.dumps({
            "suggestions": [
                {"title": f"Proposal {i}", "detail": f"Detail {i}",
                 "section_id": None, "severity": "medium"}
                for i in range(5)
            ]
        })

    def _fake_llm_unknown_section(self, prompt: str) -> str:
        return json.dumps({
            "suggestions": [
                {"title": "Fix section order", "detail": "Move intro last.",
                 "section_id": "s999", "severity": "low"},
            ]
        })

    def _fake_llm_bad_json(self, prompt: str) -> str:
        return "not json at all !!!"

    def test_5_proposed_only_3_kept(self):
        from research_companion.suggestions import generate_suggestions
        result = generate_suggestions(
            draft_id="local:draft0001", report=_report(), alignments=[],
            llm=self._fake_llm_5_proposals, include_llm=True,
        )
        structure_sugs = [s for s in result["suggestions"] if s["kind"] == "structure"]
        assert len(structure_sugs) <= 3

    def test_unknown_section_id_becomes_null(self):
        from research_companion.suggestions import generate_suggestions
        result = generate_suggestions(
            draft_id="local:draft0001", report=_report(), alignments=[],
            llm=self._fake_llm_unknown_section, include_llm=True,
        )
        structure_sugs = [s for s in result["suggestions"] if s["kind"] == "structure"]
        for s in structure_sugs:
            assert s["section_id"] is None

    def test_bad_json_skip_silently(self):
        from research_companion.suggestions import generate_suggestions
        result = generate_suggestions(
            draft_id="local:draft0001", report=_report(), alignments=[],
            llm=self._fake_llm_bad_json, include_llm=True,
        )
        assert "suggestions" in result
        structure_sugs = [s for s in result["suggestions"] if s["kind"] == "structure"]
        assert len(structure_sugs) == 0

    def test_llm_not_called_when_include_llm_false(self):
        call_count = [0]

        def counting_llm(prompt: str) -> str:
            call_count[0] += 1
            return json.dumps({"suggestions": []})

        from research_companion.suggestions import generate_suggestions
        generate_suggestions(
            draft_id="local:draft0001", report=_report(), alignments=[],
            llm=counting_llm, include_llm=False,
        )
        assert call_count[0] == 0

    def test_structure_sha_recorded_when_llm_runs(self):
        """When LLM structure pass runs, structure_prompt_sha256 is set in payload."""
        from research_companion.suggestions import generate_suggestions
        result = generate_suggestions(
            draft_id="local:draft0001", report=_report(), alignments=[],
            llm=self._fake_llm_5_proposals, include_llm=True,
        )
        sha = result.get("structure_prompt_sha256")
        assert sha is not None, "structure_prompt_sha256 must be set when LLM runs"
        assert isinstance(sha, str) and len(sha) == 64  # sha256 hex digest

    def test_structure_sha_null_when_llm_not_run(self):
        """When include_llm=False, structure_prompt_sha256 is None."""
        from research_companion.suggestions import generate_suggestions
        result = generate_suggestions(
            draft_id="local:draft0001", report=_report(), alignments=[],
            include_llm=False,
        )
        assert result.get("structure_prompt_sha256") is None


# ---------------------------------------------------------------------------
# 11. Payload shape and persistence
# ---------------------------------------------------------------------------

class TestPayloadShape:
    def test_generate_returns_version_1_payload(self):
        from research_companion.suggestions import generate_suggestions
        result = generate_suggestions(draft_id="local:draft0001", report=_report(), alignments=[])
        assert result["version"] == 1
        assert result["draft_paper_id"] == "local:draft0001"
        assert "draft_version" in result
        assert "generated_at" in result
        assert "suggestions" in result
        assert isinstance(result["suggestions"], list)

    def test_each_suggestion_has_required_keys(self):
        from research_companion.suggestions import generate_suggestions
        report = _report(citation_refs=[{"title": "Ref A", "status": "unverified"}])
        result = generate_suggestions(draft_id="local:draft0001", report=report, alignments=[])
        for s in result["suggestions"]:
            for key in ("id", "kind", "severity", "section_id", "title", "detail",
                        "source", "status", "created_at", "addressed_at", "addressed_by"):
                assert key in s, f"missing key {key!r} in suggestion {s}"

    def test_status_defaults_to_open(self):
        from research_companion.suggestions import generate_suggestions
        report = _report(citation_refs=[{"title": "New Ref", "status": "suspect"}])
        result = generate_suggestions(draft_id="local:draft0001", report=report, alignments=[])
        for s in result["suggestions"]:
            assert s["status"] == "open"

    def test_save_load_roundtrip(self):
        from research_companion.suggestions import generate_suggestions, load_suggestions
        report = _report(citation_refs=[{"title": "Round Ref", "status": "unverified"}])
        result = generate_suggestions(draft_id="local:draft0001", report=report, alignments=[])
        loaded = load_suggestions("local:draft0001")
        assert loaded is not None
        assert loaded["version"] == 1
        assert len(loaded["suggestions"]) == len(result["suggestions"])

    def test_generate_fallback_loads_report_from_store(self):
        """When report=None, generate_suggestions loads from store and uses it."""
        from research_companion import store
        from research_companion.suggestions import generate_suggestions

        draft_id = "local:fallback_draft"
        stored_report = _report(citation_refs=[{"title": "Stored Ref", "status": "unverified"}])
        stored_report["paper_id"] = draft_id
        store.save_review_report(draft_id, stored_report)

        result = generate_suggestions(draft_id=draft_id, report=None, alignments=[])
        assert result["draft_paper_id"] == draft_id
        sugs = result["suggestions"]
        assert any(s["kind"] == "citation" and "Stored Ref" in s["title"] for s in sugs), (
            f"expected citation from stored report; got titles: {[s['title'] for s in sugs]}"
        )

    def test_generate_fallback_loads_alignments_from_store(self):
        """When alignments=None, generate_suggestions loads from store for all papers."""
        from research_companion import store
        from research_companion.suggestions import generate_suggestions

        draft_id = "local:fallback_draft2"
        cand_id = "local:cand_fallback"

        cand_meta = store.PaperMetadata(
            paper_id=cand_id,
            title="Fallback Candidate",
            authors=["Auth"],
            added_at="2024-01-01T00:00:00Z",
        )
        cand_meta.save()

        alignment = _alignment(candidate_paper_id=cand_id, sections=[
            {"section_id": "s1", "section_title": "Introduction", "relation": "alternative",
             "relevance": 0.6, "rationale": "Alt.", "evidence": []},
        ])
        alignment["draft_paper_id"] = draft_id
        store.save_alignment(cand_id, alignment)

        stored_report = _report()
        stored_report["paper_id"] = draft_id

        result = generate_suggestions(draft_id=draft_id, report=stored_report, alignments=None)
        sugs = result["suggestions"]
        assert any(s["kind"] == "related_work" for s in sugs), (
            f"expected related_work from stored alignment; kinds: {[s['kind'] for s in sugs]}"
        )


# ---------------------------------------------------------------------------
# 12. dismiss_suggestion
# ---------------------------------------------------------------------------

class TestDismiss:
    def test_dismiss_sets_status_dismissed(self):
        from research_companion.suggestions import dismiss_suggestion, generate_suggestions
        report = _report(citation_refs=[{"title": "Dismiss Me", "status": "unverified"}])
        r = generate_suggestions(draft_id="local:draft0001", report=report, alignments=[])
        sug_id = r["suggestions"][0]["id"]
        updated = dismiss_suggestion(sug_id)
        assert updated["status"] == "dismissed"
        assert updated["addressed_by"]["by"] == "user"
        assert updated["addressed_by"]["note"] == "dismissed"

    def test_dismiss_unknown_id_raises_key_error(self):
        from research_companion.suggestions import dismiss_suggestion
        with pytest.raises(KeyError):
            dismiss_suggestion("sug_nonexistent0000")
