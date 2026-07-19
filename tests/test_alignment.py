"""Tests for research_companion.alignment — draft alignment engine.

Strict TDD: all tests were written before the implementation.
"""
from __future__ import annotations

import json
import math

import pytest

from research_companion import cli, extract, store
from research_companion.prompts import alignment_prompt_sha256, extraction_prompt_sha256
from research_companion.sections import Section

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_paper(paper_id: str, title: str = "Test Paper", text: str = "Some text.") -> str:
    meta = store.PaperMetadata(paper_id=paper_id, title=title, authors=["Author A"], year=2024)
    meta.save()
    store.save_text(paper_id, text)
    return paper_id


def _make_extraction(paper_id: str, claims: list | None = None) -> dict:
    ext = {
        "concepts": [{"name": "concept A"}],
        "methods": [{"name": "method B"}],
        "datasets": [],
        "claims": claims or [{"text": "We propose a method."}],
        "results": [],
        "related_work": [],
    }
    store.save_extraction(paper_id, ext, prompt_sha=extraction_prompt_sha256())
    return ext


# ---------------------------------------------------------------------------
# score_alignment / usefulness_verdict
# ---------------------------------------------------------------------------

class TestScoreAlignment:
    def test_high_verdict_at_and_above_0_7(self):
        from research_companion.alignment import score_alignment, usefulness_verdict
        score, _ = score_alignment(1.0, 1.0, 1.0)
        assert usefulness_verdict(score) == "high"

    def test_high_verdict_exactly_0_7(self):
        from research_companion.alignment import usefulness_verdict
        assert usefulness_verdict(0.7) == "high"

    def test_medium_verdict_at_0_4(self):
        from research_companion.alignment import usefulness_verdict
        assert usefulness_verdict(0.4) == "medium"

    def test_medium_verdict_between_0_4_and_0_7(self):
        from research_companion.alignment import usefulness_verdict
        assert usefulness_verdict(0.5) == "medium"
        assert usefulness_verdict(0.699) == "medium"

    def test_low_verdict_below_0_4(self):
        from research_companion.alignment import usefulness_verdict
        assert usefulness_verdict(0.3) == "low"
        assert usefulness_verdict(0.0) == "low"

    def test_score_formula(self):
        from research_companion.alignment import score_alignment
        # score = (1.0*vf + 0.8*mr + 0.6*lx) / (1.0+0.8+0.6) = (1.0*0.8 + 0.8*0.6 + 0.6*0.4) / 2.4
        # = (0.8 + 0.48 + 0.24) / 2.4 = 1.52 / 2.4 = 0.6333...
        score, band = score_alignment(0.8, 0.6, 0.4)
        expected_score = (1.0 * 0.8 + 0.8 * 0.6 + 0.6 * 0.4) / (1.0 + 0.8 + 0.6)
        assert abs(score - expected_score) < 1e-9

    def test_band_formula(self):
        from research_companion.alignment import score_alignment
        # band = clamp(0.5/sqrt(3) + 0.5*stdev([vf, mr, lx]), 0.05, 0.5)
        vf, mr, lx = 0.8, 0.6, 0.4
        values = [vf, mr, lx]
        mean = sum(values) / len(values)
        stdev = math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))
        expected_band = min(0.5, max(0.05, 0.5 / math.sqrt(3) + 0.5 * stdev))
        _, band = score_alignment(vf, mr, lx)
        assert abs(band - expected_band) < 1e-9

    def test_band_clamped_to_min_0_05(self):
        from research_companion.alignment import score_alignment
        # All equal signals -> stdev=0 -> band = 0.5/sqrt(3) = ~0.289 > 0.05
        _, band = score_alignment(0.5, 0.5, 0.5)
        assert band >= 0.05

    def test_band_clamped_to_max_0_5(self):
        from research_companion.alignment import score_alignment
        # Edge case: even max stdev (0..1 range) + 0.5/sqrt(3) should be <= 0.5
        _, band = score_alignment(0.0, 1.0, 0.0)
        assert band <= 0.5

    def test_zero_signals_all_zero_score(self):
        from research_companion.alignment import score_alignment
        score, _ = score_alignment(0.0, 0.0, 0.0)
        assert score == 0.0

    def test_all_one_signals_score_one(self):
        from research_companion.alignment import score_alignment
        score, _ = score_alignment(1.0, 1.0, 1.0)
        assert abs(score - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# lexical_overlap
# ---------------------------------------------------------------------------

class TestLexicalOverlap:
    def test_identical_sets(self):
        from research_companion.alignment import lexical_overlap
        tokens = {"hello", "world", "test"}
        assert lexical_overlap(tokens, tokens) == 1.0

    def test_disjoint_sets(self):
        from research_companion.alignment import lexical_overlap
        assert lexical_overlap({"hello", "world"}, {"foo", "bar"}) == 0.0

    def test_partial_overlap(self):
        from research_companion.alignment import lexical_overlap
        a = {"hello", "world", "test"}
        b = {"hello", "world", "other"}
        # intersection=2, union=4 -> 0.5
        assert abs(lexical_overlap(a, b) - 0.5) < 1e-9

    def test_empty_sets(self):
        from research_companion.alignment import lexical_overlap
        assert lexical_overlap(set(), set()) == 0.0

    def test_one_empty(self):
        from research_companion.alignment import lexical_overlap
        assert lexical_overlap({"hello"}, set()) == 0.0


# ---------------------------------------------------------------------------
# rank_draft_sections
# ---------------------------------------------------------------------------

class TestRankDraftSections:
    def _make_sections(self):
        """Make 4 sections, one of which is boilerplate."""
        return [
            Section("s1", "Introduction", 1, None, 0, 100),
            Section("s2", "Methods", 1, None, 100, 200),
            Section("s3", "Results", 1, None, 200, 300),
            Section("s4", "References", 1, None, 300, 400),  # boilerplate
        ]

    def test_excludes_boilerplate(self):
        from research_companion.alignment import rank_draft_sections
        sections = self._make_sections()
        draft_text = "Introduction body\n" * 5 + "Methods body\n" * 5 + \
                     "Results body\n" * 5 + "References body\n" * 5
        candidate_meta = store.PaperMetadata(
            paper_id="arxiv:9999.00001", title="Results Methods", authors=[], year=2024
        )
        extraction = {
            "claims": [{"text": "We apply these methods to produce results."}],
            "concepts": [],
        }
        ranked = rank_draft_sections(sections, draft_text, candidate_meta, extraction, k=10)
        titles = [s.title for s, _ in ranked]
        assert "References" not in titles

    def test_returns_at_most_k(self):
        from research_companion.alignment import rank_draft_sections
        sections = self._make_sections()
        draft_text = ("Introduction body\n" * 5 + "Methods body\n" * 5 +
                      "Results body\n" * 5 + "References\n" * 5)
        candidate_meta = store.PaperMetadata(
            paper_id="arxiv:9999.00002", title="Methods", authors=[], year=2024
        )
        ranked = rank_draft_sections(sections, draft_text, candidate_meta, {}, k=2)
        assert len(ranked) <= 2

    def test_top_section_has_higher_overlap(self):
        from research_companion.alignment import rank_draft_sections
        # Candidate strongly mentions "methods" which appears in "Methods" section title
        sections = [
            Section("s1", "Introduction", 1, None, 0, 50),
            Section("s2", "Methods", 1, None, 50, 100),
        ]
        draft_text = "Introduction intro intro\n" * 3 + "Methods methods methods\n" * 3
        candidate_meta = store.PaperMetadata(
            paper_id="arxiv:9999.00003", title="Methods Study", authors=[], year=2024
        )
        extraction = {"claims": [{"text": "methods methods methods"}], "concepts": []}
        ranked = rank_draft_sections(sections, draft_text, candidate_meta, extraction, k=2)
        assert len(ranked) >= 1
        # The Methods section should appear in results
        section_titles = [s.title for s, _ in ranked]
        assert "Methods" in section_titles

    def test_document_order_tiebreak(self):
        from research_companion.alignment import rank_draft_sections
        # Two sections with identical overlap — should preserve document order
        sections = [
            Section("s1", "Alpha", 1, None, 0, 50),
            Section("s2", "Alpha", 1, None, 50, 100),
        ]
        draft_text = "Alpha text here.\n" * 5 + "Alpha text here.\n" * 5
        candidate_meta = store.PaperMetadata(
            paper_id="arxiv:9999.00004", title="Alpha", authors=[], year=2024
        )
        ranked = rank_draft_sections(sections, draft_text, candidate_meta, {}, k=2)
        ids = [s.section_id for s, _ in ranked]
        assert ids.index("s1") < ids.index("s2")


# ---------------------------------------------------------------------------
# align_papers (happy path)
# ---------------------------------------------------------------------------

CANDIDATE_TEXT = (
    "Deep learning achieves state of the art performance. "
    "We demonstrate substantial improvements over baselines. "
    "Our method leverages neural network architectures effectively."
)


def _make_fake_llm(relation: str = "strengthens", evidence_quote: str = "Deep learning achieves state of the art performance."):
    """Factory for a fake LLM that returns canned alignment JSON."""
    def fake_llm(prompt: str) -> str:
        return json.dumps({
            "sections": [
                {
                    "section_id": "s1",
                    "relation": relation,
                    "relevance": 0.85,
                    "rationale": "Candidate paper provides supporting evidence.",
                    "evidence": [{"quote": evidence_quote}],
                },
                {
                    "section_id": "s2",
                    "relation": "irrelevant",
                    "relevance": 0.1,
                    "rationale": "Not relevant.",
                    "evidence": [],
                },
            ]
        })
    return fake_llm


class TestAlignPapersHappyPath:
    def test_basic_returns_payload_shape(self):
        from research_companion.alignment import align_papers
        draft_id = _make_paper("local:draft00001", "Draft Paper",
                               "Introduction text here.\n\nMethods text here.\n")
        cand_id = _make_paper("local:cand000001", "Candidate Paper", CANDIDATE_TEXT)
        _make_extraction(draft_id)
        _make_extraction(cand_id)

        result = align_papers(draft_id, cand_id, llm=_make_fake_llm(), persist=False)

        assert result["version"] == 1
        assert result["draft_paper_id"] == draft_id
        assert result["candidate_paper_id"] == cand_id
        assert "prompt_sha256" in result
        assert "computed_at" in result
        assert "score" in result
        assert "band" in result
        assert "verdict" in result
        assert "signals" in result
        assert "sections" in result

    def test_different_perspective_mapped_to_alternative(self):
        from research_companion.alignment import align_papers
        # Draft text must have real numbered headings with bodies >= 40 chars so that
        # build_and_save_sections yields both s1 and s2 (not a single fallback section).
        # That way the fake LLM's s2 entry is NOT dropped by the unknown-section-id
        # check and the mapping/filter logic is genuinely exercised.
        draft_text = (
            "1 Introduction\n"
            "This is the introduction section body with sufficient length here.\n\n"
            "2 Methods\n"
            "This is the methods section body with sufficient length text here.\n"
        )
        draft_id = _make_paper("local:draft00002", "Draft Paper", draft_text)
        cand_id = _make_paper("local:cand000002", "Candidate Paper", CANDIDATE_TEXT)
        _make_extraction(draft_id)
        _make_extraction(cand_id)

        result = align_papers(
            draft_id, cand_id,
            llm=_make_fake_llm(relation="different_perspective"),
            persist=False,
        )
        # s1: different_perspective -> mapped to "alternative" (kept)
        # s2: irrelevant -> excluded
        # So only s1 should be in sections with relation "alternative"
        section_ids = [s["section_id"] for s in result["sections"]]
        assert "s2" not in section_ids
        assert len(result["sections"]) == 1
        assert result["sections"][0]["relation"] == "alternative"

    def test_irrelevant_sections_excluded(self):
        from research_companion.alignment import align_papers
        # Draft text must have real numbered headings with bodies >= 40 chars so that
        # build_and_save_sections yields both s1 and s2 (not a single fallback section).
        # That way the fake LLM's s2 "irrelevant" entry is NOT dropped by the
        # unknown-section-id check — the irrelevant-filter logic is genuinely exercised.
        draft_text = (
            "1 Introduction\n"
            "This is the introduction section body with sufficient length here.\n\n"
            "2 Methods\n"
            "This is the methods section body with sufficient length text here.\n"
        )
        draft_id = _make_paper("local:draft00003", "Draft Paper", draft_text)
        cand_id = _make_paper("local:cand000003", "Candidate Paper", CANDIDATE_TEXT)
        _make_extraction(draft_id)
        _make_extraction(cand_id)

        result = align_papers(draft_id, cand_id, llm=_make_fake_llm(), persist=False)
        # s2 is returned as "irrelevant" by the fake LLM; it must be excluded from payload
        section_ids = [s["section_id"] for s in result["sections"]]
        assert "s2" not in section_ids
        for sec in result["sections"]:
            assert sec["relation"] != "irrelevant"

    def test_evidence_verified_exact(self):
        from research_companion.alignment import align_papers
        draft_id = _make_paper("local:draft00004", "Draft Paper",
                               "Introduction text here.\n\nMethods text here.\n")
        cand_id = _make_paper("local:cand000004", "Candidate Paper", CANDIDATE_TEXT)
        _make_extraction(draft_id)
        _make_extraction(cand_id)

        quote = "Deep learning achieves state of the art performance."
        result = align_papers(
            draft_id, cand_id,
            llm=_make_fake_llm(evidence_quote=quote),
            persist=False,
        )
        # The quote is exactly in CANDIDATE_TEXT
        ev = result["sections"][0]["evidence"][0]
        assert ev["verified"] is True
        assert ev["match"] in ("exact", "normalized")

    def test_evidence_not_verified_fabricated_quote(self):
        from research_companion.alignment import align_papers
        draft_id = _make_paper("local:draft00005", "Draft Paper",
                               "Introduction text here.\n\nMethods text here.\n")
        cand_id = _make_paper("local:cand000005", "Candidate Paper", CANDIDATE_TEXT)
        _make_extraction(draft_id)
        _make_extraction(cand_id)

        fabricated = "This text is completely fabricated and does not exist anywhere."
        result = align_papers(
            draft_id, cand_id,
            llm=_make_fake_llm(evidence_quote=fabricated),
            persist=False,
        )
        ev = result["sections"][0]["evidence"][0]
        assert ev["verified"] is False
        assert ev["match"] == "none"

    def test_zero_quotes_verified_frac_is_zero(self):
        """Zero quotes -> quote_verification = 0.0 (honesty first)."""
        from research_companion.alignment import align_papers

        def zero_quote_llm(prompt: str) -> str:
            return json.dumps({
                "sections": [
                    {
                        "section_id": "s1",
                        "relation": "strengthens",
                        "relevance": 0.9,
                        "rationale": "Good alignment.",
                        "evidence": [],  # no quotes
                    }
                ]
            })

        draft_id = _make_paper("local:draft00006", "Draft Paper",
                               "Introduction text here.\n\nMethods text here.\n")
        cand_id = _make_paper("local:cand000006", "Candidate Paper", CANDIDATE_TEXT)
        _make_extraction(draft_id)
        _make_extraction(cand_id)

        result = align_papers(draft_id, cand_id, llm=zero_quote_llm, persist=False)
        assert result["signals"]["quote_verification"] == 0.0

    def test_score_band_verdict_hand_computed(self):
        """Verify score and verdict match hand-computed values."""
        from research_companion.alignment import (
            _tokenize,
            align_papers,
            lexical_overlap,
            score_alignment,
            usefulness_verdict,
        )
        draft_text = "Introduction text here.\n\nMethods text here.\n"
        draft_id = _make_paper("local:draft00007", "Draft Paper", draft_text)
        cand_id = _make_paper("local:cand000007", "Candidate Paper", CANDIDATE_TEXT)
        _make_extraction(draft_id)
        _make_extraction(cand_id)

        quote = "Deep learning achieves state of the art performance."
        result = align_papers(
            draft_id, cand_id,
            llm=_make_fake_llm(evidence_quote=quote),
            persist=False,
        )
        # verified_frac = 1 (1 verified / 1 total), mean_relevance = 0.85
        expected_vf = 1.0
        expected_mr = 0.85
        # Compute lexical signal INDEPENDENTLY — same token sets align_papers uses:
        #   draft tokens = _tokenize(draft_text_full)
        #   cand tokens  = _tokenize(cand_text)  where cand_text = CANDIDATE_TEXT
        draft_tokens = _tokenize(draft_text)
        cand_tokens = _tokenize(CANDIDATE_TEXT)
        independently_computed_lx = lexical_overlap(draft_tokens, cand_tokens)
        expected_score, expected_band = score_alignment(expected_vf, expected_mr, independently_computed_lx)
        assert result["signals"]["lexical_overlap"] == independently_computed_lx
        assert abs(result["score"] - expected_score) < 1e-9
        assert abs(result["band"] - expected_band) < 1e-9
        assert result["verdict"] == usefulness_verdict(expected_score)

    def test_section_has_section_title(self):
        """Each section entry has a section_title field."""
        from research_companion.alignment import align_papers
        draft_id = _make_paper("local:draft00008", "Draft Paper",
                               "Introduction text here.\n\nMethods text here.\n")
        cand_id = _make_paper("local:cand000008", "Candidate Paper", CANDIDATE_TEXT)
        _make_extraction(draft_id)
        _make_extraction(cand_id)

        result = align_papers(draft_id, cand_id, llm=_make_fake_llm(), persist=False)
        for sec in result["sections"]:
            assert "section_title" in sec
            assert isinstance(sec["section_title"], str)


# ---------------------------------------------------------------------------
# align_papers error conditions
# ---------------------------------------------------------------------------

class TestAlignPapersErrors:
    def test_draft_eq_candidate_raises_alignment_error(self):
        from research_companion.alignment import AlignmentError, align_papers
        draft_id = _make_paper("local:draft00009", "Draft Paper", "Some text.")
        with pytest.raises(AlignmentError):
            align_papers(draft_id, draft_id, llm=_make_fake_llm(), persist=False)

    def test_unknown_draft_raises_value_error(self):
        from research_companion.alignment import align_papers
        cand_id = _make_paper("local:cand000009", "Candidate", "Some text.")
        with pytest.raises(ValueError):
            align_papers("local:nonexistent01", cand_id, llm=_make_fake_llm(), persist=False)

    def test_unknown_candidate_raises_value_error(self):
        from research_companion.alignment import align_papers
        draft_id = _make_paper("local:draft00010", "Draft", "Some text.")
        with pytest.raises(ValueError):
            align_papers(draft_id, "local:nonexistent02", llm=_make_fake_llm(), persist=False)

    def test_bad_llm_json_raises_alignment_error_no_persist(self):
        from research_companion.alignment import AlignmentError, align_papers
        draft_id = _make_paper("local:draft00011", "Draft", "Some text.\n\nMore text.\n")
        cand_id = _make_paper("local:cand000011", "Candidate", "Candidate text here.")
        _make_extraction(draft_id)
        _make_extraction(cand_id)

        def bad_llm(prompt: str) -> str:
            return "not json at all !!!"

        with pytest.raises(AlignmentError):
            align_papers(draft_id, cand_id, llm=bad_llm, persist=True)

        # Nothing should be persisted
        assert store.load_alignment(cand_id, draft_paper_id=draft_id) is None

    def test_missing_sections_key_in_llm_response_raises_alignment_error(self):
        from research_companion.alignment import AlignmentError, align_papers
        draft_id = _make_paper("local:draft00012", "Draft", "Some text.\n\nMore text.\n")
        cand_id = _make_paper("local:cand000012", "Candidate", "Candidate text.")
        _make_extraction(draft_id)
        _make_extraction(cand_id)

        def no_sections_llm(prompt: str) -> str:
            return json.dumps({"wrong_key": []})

        with pytest.raises(AlignmentError):
            align_papers(draft_id, cand_id, llm=no_sections_llm, persist=False)

    def test_unknown_section_ids_dropped(self):
        from research_companion.alignment import align_papers
        draft_id = _make_paper("local:draft00013", "Draft",
                               "Introduction text here.\n\nMethods text here.\n")
        cand_id = _make_paper("local:cand000013", "Candidate", CANDIDATE_TEXT)
        _make_extraction(draft_id)
        _make_extraction(cand_id)

        def unknown_id_llm(prompt: str) -> str:
            return json.dumps({
                "sections": [
                    {
                        "section_id": "s1",
                        "relation": "strengthens",
                        "relevance": 0.8,
                        "rationale": "Fine.",
                        "evidence": [],
                    },
                    {
                        "section_id": "s999",  # unknown
                        "relation": "strengthens",
                        "relevance": 0.9,
                        "rationale": "Made up.",
                        "evidence": [],
                    },
                ]
            })

        result = align_papers(draft_id, cand_id, llm=unknown_id_llm, persist=False)
        section_ids = [s["section_id"] for s in result["sections"]]
        assert "s999" not in section_ids

    def test_relevance_clamped_0_to_1(self):
        from research_companion.alignment import align_papers
        draft_id = _make_paper("local:draft00014", "Draft",
                               "Introduction text here.\n\nMethods text here.\n")
        cand_id = _make_paper("local:cand000014", "Candidate", CANDIDATE_TEXT)
        _make_extraction(draft_id)
        _make_extraction(cand_id)

        def bad_relevance_llm(prompt: str) -> str:
            return json.dumps({
                "sections": [
                    {
                        "section_id": "s1",
                        "relation": "strengthens",
                        "relevance": 5.0,  # out of range
                        "rationale": "Fine.",
                        "evidence": [],
                    },
                ]
            })

        result = align_papers(draft_id, cand_id, llm=bad_relevance_llm, persist=False)
        for sec in result["sections"]:
            assert 0.0 <= sec["relevance"] <= 1.0


# ---------------------------------------------------------------------------
# Cache behavior
# ---------------------------------------------------------------------------

class TestAlignPapersCache:
    def test_second_call_does_not_re_call_llm(self):
        from research_companion.alignment import align_papers
        draft_id = _make_paper("local:draft00015", "Draft",
                               "Introduction text here.\n\nMethods text here.\n")
        cand_id = _make_paper("local:cand000015", "Candidate", CANDIDATE_TEXT)
        _make_extraction(draft_id)
        _make_extraction(cand_id)

        call_count = [0]

        def counting_llm(prompt: str) -> str:
            call_count[0] += 1
            return json.dumps({
                "sections": [
                    {
                        "section_id": "s1",
                        "relation": "strengthens",
                        "relevance": 0.8,
                        "rationale": "Fine.",
                        "evidence": [],
                    },
                ]
            })

        r1 = align_papers(draft_id, cand_id, llm=counting_llm, persist=True)
        assert call_count[0] == 1

        r2 = align_papers(draft_id, cand_id, llm=counting_llm, persist=True)
        assert call_count[0] == 1  # NOT re-called
        assert r2["score"] == r1["score"]

    def test_force_re_calls_llm(self):
        from research_companion.alignment import align_papers
        draft_id = _make_paper("local:draft00016", "Draft",
                               "Introduction text here.\n\nMethods text here.\n")
        cand_id = _make_paper("local:cand000016", "Candidate", CANDIDATE_TEXT)
        _make_extraction(draft_id)
        _make_extraction(cand_id)

        call_count = [0]

        def counting_llm(prompt: str) -> str:
            call_count[0] += 1
            return json.dumps({
                "sections": [
                    {"section_id": "s1", "relation": "strengthens", "relevance": 0.8,
                     "rationale": "Fine.", "evidence": []},
                ]
            })

        align_papers(draft_id, cand_id, llm=counting_llm, persist=True)
        assert call_count[0] == 1

        align_papers(draft_id, cand_id, llm=counting_llm, persist=True, force=True)
        assert call_count[0] == 2

    def test_cache_invalidated_on_prompt_sha_mismatch(self):
        """A cached alignment with a different prompt_sha is ignored."""
        from research_companion.alignment import align_papers
        draft_id = _make_paper("local:draft00017", "Draft",
                               "Introduction text here.\n\nMethods text here.\n")
        cand_id = _make_paper("local:cand000017", "Candidate", CANDIDATE_TEXT)
        _make_extraction(draft_id)
        _make_extraction(cand_id)

        # Manually persist a payload with a stale prompt_sha
        stale_payload = {
            "version": 1,
            "draft_paper_id": draft_id,
            "candidate_paper_id": cand_id,
            "prompt_sha256": "stale_sha_not_current",
            "computed_at": "2025-01-01T00:00:00Z",
            "score": 0.999,
            "band": 0.05,
            "verdict": "high",
            "signals": {"quote_verification": 1.0, "llm_relevance": 1.0, "lexical_overlap": 1.0},
            "sections": [],
        }
        store.save_alignment(cand_id, stale_payload)

        call_count = [0]

        def counting_llm(prompt: str) -> str:
            call_count[0] += 1
            return json.dumps({
                "sections": [
                    {"section_id": "s1", "relation": "strengthens", "relevance": 0.7,
                     "rationale": "Fine.", "evidence": []},
                ]
            })

        result = align_papers(draft_id, cand_id, llm=counting_llm, persist=True)
        assert call_count[0] == 1  # stale cache ignored; LLM called
        assert result["prompt_sha256"] == alignment_prompt_sha256()


# ---------------------------------------------------------------------------
# Persist rules
# ---------------------------------------------------------------------------

class TestAlignPapersPersistRules:
    def test_persist_true_always_writes(self):
        from research_companion.alignment import align_papers
        draft_id = _make_paper("local:draft00018", "Draft",
                               "Introduction text here.\n\nMethods text here.\n")
        cand_id = _make_paper("local:cand000018", "Candidate", CANDIDATE_TEXT)
        _make_extraction(draft_id)
        _make_extraction(cand_id)

        align_papers(draft_id, cand_id, llm=_make_fake_llm(), persist=True)
        loaded = store.load_alignment(cand_id, draft_paper_id=draft_id)
        assert loaded is not None
        assert loaded["draft_paper_id"] == draft_id

    def test_persist_false_never_writes(self):
        from research_companion.alignment import align_papers
        draft_id = _make_paper("local:draft00019", "Draft",
                               "Introduction text here.\n\nMethods text here.\n")
        cand_id = _make_paper("local:cand000019", "Candidate", CANDIDATE_TEXT)
        _make_extraction(draft_id)
        _make_extraction(cand_id)

        align_papers(draft_id, cand_id, llm=_make_fake_llm(), persist=False)
        assert store.load_alignment(cand_id, draft_paper_id=draft_id) is None

    def test_persist_none_with_configured_draft_writes(self):
        """persist=None + candidate vs. configured draft -> writes."""
        from research_companion.alignment import align_papers
        draft_id = _make_paper("local:draft00020", "Draft",
                               "Introduction text here.\n\nMethods text here.\n")
        cand_id = _make_paper("local:cand000020", "Candidate", CANDIDATE_TEXT)
        _make_extraction(draft_id)
        _make_extraction(cand_id)
        store.set_draft_paper_id(draft_id)

        align_papers(draft_id, cand_id, llm=_make_fake_llm(), persist=None)
        assert store.load_alignment(cand_id, draft_paper_id=draft_id) is not None

    def test_persist_none_different_draft_does_not_write(self):
        """persist=None + different draft configured -> does NOT write."""
        from research_companion.alignment import align_papers
        draft_id = _make_paper("local:draft00021", "Draft",
                               "Introduction text here.\n\nMethods text here.\n")
        other_draft = _make_paper("local:draft00022", "Other Draft", "Other text.\n")
        cand_id = _make_paper("local:cand000021", "Candidate", CANDIDATE_TEXT)
        _make_extraction(draft_id)
        _make_extraction(cand_id)
        store.set_draft_paper_id(other_draft)  # different draft

        align_papers(draft_id, cand_id, llm=_make_fake_llm(), persist=None)
        # Should NOT persist (draft_id != configured draft)
        assert store.load_alignment(cand_id, draft_paper_id=draft_id) is None

    def test_persist_none_no_draft_configured_does_not_write(self):
        """persist=None + no draft configured -> does NOT write (transient)."""
        from research_companion.alignment import align_papers
        draft_id = _make_paper("local:draft00023", "Draft",
                               "Introduction text here.\n\nMethods text here.\n")
        cand_id = _make_paper("local:cand000023", "Candidate", CANDIDATE_TEXT)
        _make_extraction(draft_id)
        _make_extraction(cand_id)
        # no draft configured

        align_papers(draft_id, cand_id, llm=_make_fake_llm(), persist=None)
        assert store.load_alignment(cand_id, draft_paper_id=draft_id) is None


# ---------------------------------------------------------------------------
# CLI: set-draft subcommand
# ---------------------------------------------------------------------------

class TestCliSetDraft:
    def test_set_draft_saves_paper_id(self, capsys):
        pid = _make_paper("local:draft00030", "Draft Paper", "Draft text.")
        rc = cli.main(["set-draft", pid])
        assert rc == 0
        assert store.get_draft_paper_id() == pid
        out = capsys.readouterr().out
        assert pid in out

    def test_set_draft_unknown_paper_errors(self, capsys):
        rc = cli.main(["set-draft", "local:nonexistent99"])
        assert rc == 1
        err = capsys.readouterr().err
        assert "nonexistent" in err.lower() or "unknown" in err.lower() or "no such" in err.lower()

    def test_set_draft_clear(self, capsys):
        pid = _make_paper("local:draft00031", "Draft Paper", "Draft text.")
        store.set_draft_paper_id(pid)
        rc = cli.main(["set-draft", "--clear"])
        assert rc == 0
        assert store.get_draft_paper_id() is None

    def test_set_draft_show_when_set(self, capsys):
        pid = _make_paper("local:draft00032", "Draft Paper", "Draft text.")
        store.set_draft_paper_id(pid)
        rc = cli.main(["set-draft", "--show"])
        assert rc == 0
        out = capsys.readouterr().out
        assert pid in out

    def test_set_draft_show_when_not_set(self, capsys):
        rc = cli.main(["set-draft", "--show"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "no draft" in out.lower()


# ---------------------------------------------------------------------------
# CLI: align subcommand
# ---------------------------------------------------------------------------

# Override dict for injecting fake LLM into CLI
ALIGN_CONTEXT_OVERRIDES: dict = {}


class TestCliAlign:
    def _seed(self):
        draft_id = _make_paper("local:draft00040", "Draft Paper",
                               "Introduction text here.\n\nMethods text here.\n")
        cand_id = _make_paper("local:cand000040", "Candidate Paper", CANDIDATE_TEXT)
        _make_extraction(draft_id)
        _make_extraction(cand_id)
        return draft_id, cand_id

    def test_align_with_draft_configured_json_output(self, monkeypatch, capsys):
        draft_id, cand_id = self._seed()
        store.set_draft_paper_id(draft_id)

        monkeypatch.setattr(cli, "ALIGN_CONTEXT_OVERRIDES", {"_llm": _make_fake_llm()})
        rc = cli.main(["align", cand_id, "--json"])
        assert rc == 0
        out = capsys.readouterr().out
        payload = json.loads(out)
        assert payload["draft_paper_id"] == draft_id
        assert payload["candidate_paper_id"] == cand_id
        assert "score" in payload
        assert "verdict" in payload

    def test_align_with_against_flag(self, monkeypatch, capsys):
        draft_id, cand_id = self._seed()
        # No draft configured — must use --against

        monkeypatch.setattr(cli, "ALIGN_CONTEXT_OVERRIDES", {"_llm": _make_fake_llm()})
        rc = cli.main(["align", cand_id, "--against", draft_id, "--json"])
        assert rc == 0
        out = capsys.readouterr().out
        payload = json.loads(out)
        assert payload["draft_paper_id"] == draft_id

    def test_align_no_draft_no_against_rc1(self, capsys):
        draft_id, cand_id = self._seed()
        # No draft configured, no --against
        rc = cli.main(["align", cand_id])
        assert rc == 1
        err = capsys.readouterr().err
        assert "draft" in err.lower() or "against" in err.lower()

    def test_align_human_output_shows_verdict_score(self, monkeypatch, capsys):
        draft_id, cand_id = self._seed()
        store.set_draft_paper_id(draft_id)

        monkeypatch.setattr(cli, "ALIGN_CONTEXT_OVERRIDES", {"_llm": _make_fake_llm()})
        rc = cli.main(["align", cand_id])
        assert rc == 0
        out = capsys.readouterr().out
        # Should show verdict and score somewhere
        assert any(v in out.lower() for v in ("high", "medium", "low"))
        # score should be a float-like string somewhere
        import re
        assert re.search(r"\d+\.\d+", out) is not None

    def test_align_force_flag(self, monkeypatch, capsys):
        draft_id, cand_id = self._seed()
        store.set_draft_paper_id(draft_id)

        call_count = [0]

        def counting_llm(prompt: str) -> str:
            call_count[0] += 1
            return json.dumps({
                "sections": [
                    {"section_id": "s1", "relation": "strengthens", "relevance": 0.8,
                     "rationale": "Fine.", "evidence": []},
                ]
            })

        monkeypatch.setattr(cli, "ALIGN_CONTEXT_OVERRIDES", {"_llm": counting_llm})
        cli.main(["align", cand_id, "--json"])
        capsys.readouterr()
        assert call_count[0] == 1

        cli.main(["align", cand_id, "--json", "--force"])
        capsys.readouterr()
        assert call_count[0] == 2

    # -----------------------------------------------------------------
    # --provider: flag > RESEARCH_COMPANION_PROVIDER > "anthropic" default.
    #
    # Regression coverage for the bug where the parser default of "anthropic"
    # made args.provider never None, dead-coding RESEARCH_COMPANION_PROVIDER
    # whenever --provider was omitted. These bypass ALIGN_CONTEXT_OVERRIDES
    # (no injected "_llm") so the real _resolve_llm_for_align path runs,
    # asserting on which of extract._call_openai / extract._call_anthropic
    # actually gets invoked.
    # -----------------------------------------------------------------

    _FAKE_ALIGN_JSON = json.dumps({
        "sections": [
            {"section_id": "s1", "relation": "strengthens", "relevance": 0.8,
             "rationale": "Fine.", "evidence": []},
        ]
    })

    def test_align_no_flag_honors_env_provider(self, monkeypatch, capsys):
        draft_id, cand_id = self._seed()
        store.set_draft_paper_id(draft_id)
        monkeypatch.setenv("RESEARCH_COMPANION_PROVIDER", "openai")

        calls = []
        monkeypatch.setattr(
            extract, "_call_openai",
            lambda prompt, model=None, **kw: (
                calls.append(("openai", model)) or (self._FAKE_ALIGN_JSON, {})
            ),
        )
        monkeypatch.setattr(
            extract, "_call_anthropic",
            lambda prompt, model=None, **kw: (
                calls.append(("anthropic", model)) or (self._FAKE_ALIGN_JSON, {})
            ),
        )

        rc = cli.main(["align", cand_id, "--json"])
        assert rc == 0
        assert calls
        assert calls[0][0] == "openai"

    def test_align_explicit_flag_overrides_env_provider(self, monkeypatch, capsys):
        draft_id, cand_id = self._seed()
        store.set_draft_paper_id(draft_id)
        monkeypatch.setenv("RESEARCH_COMPANION_PROVIDER", "openai")

        calls = []
        monkeypatch.setattr(
            extract, "_call_openai",
            lambda prompt, model=None, **kw: (
                calls.append(("openai", model)) or (self._FAKE_ALIGN_JSON, {})
            ),
        )
        monkeypatch.setattr(
            extract, "_call_anthropic",
            lambda prompt, model=None, **kw: (
                calls.append(("anthropic", model)) or (self._FAKE_ALIGN_JSON, {})
            ),
        )

        rc = cli.main(["align", cand_id, "--provider", "anthropic", "--json"])
        assert rc == 0
        assert calls
        assert calls[0][0] == "anthropic"

    def test_align_no_flag_no_env_defaults_to_anthropic(self, monkeypatch, capsys):
        """No flag, no env: still defaults to anthropic (no regression).

        Note: RESEARCH_COMPANION_PROVIDER is pinned to "anthropic" suite-wide by
        conftest's _restore_os_environ (so cli.main()'s unconditional real-.env
        load can't leak the maintainer's own dev-only provider setting into
        tests); this asserts the observable default-resolution behavior rather
        than a literally-unset env var.
        """
        draft_id, cand_id = self._seed()
        store.set_draft_paper_id(draft_id)

        calls = []
        monkeypatch.setattr(
            extract, "_call_anthropic",
            lambda prompt, model=None, **kw: (
                calls.append(("anthropic", model)) or (self._FAKE_ALIGN_JSON, {})
            ),
        )

        rc = cli.main(["align", cand_id, "--json"])
        assert rc == 0
        assert calls
        assert calls[0][0] == "anthropic"
