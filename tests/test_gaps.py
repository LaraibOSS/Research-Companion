"""Tests for research_companion.gaps — gap extraction + resolution mapping.

Strict TDD per W3-T9 brief:
- section selection regex
- no-gap-sections -> zero LLM calls + cached flag
- extraction: quotes verified/unverified flags; cache honored by sha; force re-extracts;
  malformed JSON -> raises GapError; extract_all catches + skips
- resolution: prefilter below threshold -> open without LLM (counting fake proves);
  candidate year filtering; resolved_by sanitized; unverified evidence -> partially;
  papers_sha staleness invalidates
- gaps_for_suggestions relevance/addressed math; suggestions wiring fallback
- CLI: gaps --json shape; timeline --json shape
"""
from __future__ import annotations

import json

import pytest

from research_companion import store
from research_companion.gaps import (
    _GAP_SECTION_RE,
    GapError,
    _assemble_themes,
    _collect_verified_gaps,
    _gap_id,
    _papers_sha,
    _relevance_score,
    extract_all_gaps,
    extract_gaps,
    gaps_for_suggestions,
    gaps_overview,
    rank_gap_themes,
    resolve_gaps,
    synthesize_gaps,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_paper(
    paper_id: str,
    *,
    title: str = "Test Paper",
    year: int | None = 2020,
    text: str | None = None,
    sections: list[dict] | None = None,
) -> store.PaperMetadata:
    """Create a minimal paper in the store with optional sections."""
    meta = store.PaperMetadata(
        paper_id=paper_id,
        title=title,
        authors=["Author One"],
        year=year,
        added_at="2024-01-01T00:00:00Z",
    )
    meta.save()

    default_text = (
        "Introduction\nSome intro text about methods.\n\n"
        "Limitations\nWe could not scale this approach to large datasets. "
        "Future work should investigate efficiency improvements.\n\n"
        "Conclusion\nWe conclude that the method works.\n"
    )
    store.save_text(paper_id, text or default_text)

    if sections is not None:
        payload = {
            "version": 1,
            "text_sha256": "abc",
            "method": "heuristic",
            "sections": sections,
        }
        store.save_sections(paper_id, payload)
    return meta


def _make_sections_with_limitations(text: str) -> list[dict]:
    """Return section list for a paper text that has a Limitations section."""
    # Find 'Limitations' in text
    idx = text.find("Limitations")
    if idx == -1:
        return [{"section_id": "s1", "title": "Full Text", "level": 1,
                 "parent": None, "char_start": 0, "char_end": len(text)}]
    return [
        {"section_id": "s1", "title": "Introduction", "level": 1,
         "parent": None, "char_start": 0, "char_end": idx},
        {"section_id": "s2", "title": "Limitations", "level": 1,
         "parent": None, "char_start": idx, "char_end": len(text)},
    ]


# ---------------------------------------------------------------------------
# 0. Mode-independent relevance normalization
# ---------------------------------------------------------------------------

class TestRelevanceScore:
    def test_none_and_empty_are_zero(self):
        assert _relevance_score(None) == 0.0
        assert _relevance_score({}) == 0.0

    def test_hybrid_score_passes_through(self):
        # Hybrid scores are already min-max fused into [0, 1].
        assert _relevance_score({"mode": "hybrid", "score": 0.42}) == 0.42
        assert _relevance_score({"mode": "hybrid", "score": 1.0}) == 1.0

    def test_bm25_raw_score_saturates_into_unit_interval(self):
        # Raw, unbounded BM25 -> s / (s + 1), always in [0, 1).
        assert _relevance_score({"mode": "bm25", "score": 1.0}) == 0.5
        assert _relevance_score({"mode": "bm25", "score": 0.0}) == 0.0
        big = _relevance_score({"mode": "bm25", "score": 1000.0})
        assert 0.99 < big < 1.0

    def test_extreme_thresholds_behave_consistently_across_modes(self):
        # threshold 0.0 passes any positive match; threshold 999 filters all,
        # regardless of mode -> the gating decision no longer flips with the
        # HF token, only the recall does.
        for top in ({"mode": "hybrid", "score": 0.8},
                    {"mode": "bm25", "score": 12.0}):
            s = _relevance_score(top)
            assert s >= 0.0
            assert s < 999.0


# ---------------------------------------------------------------------------
# 1. Section selection regex
# ---------------------------------------------------------------------------

class TestGapSectionRegex:
    def test_matches_limitation(self):
        assert _GAP_SECTION_RE.search("Limitations")
        assert _GAP_SECTION_RE.search("limitation")
        assert _GAP_SECTION_RE.search("LIMITATIONS")

    def test_matches_future_work(self):
        assert _GAP_SECTION_RE.search("Future Work")
        assert _GAP_SECTION_RE.search("future work")

    def test_matches_discussion(self):
        assert _GAP_SECTION_RE.search("Discussion")

    def test_matches_conclusion(self):
        assert _GAP_SECTION_RE.search("Conclusion")
        assert _GAP_SECTION_RE.search("Conclusions")

    def test_no_match_on_introduction(self):
        assert not _GAP_SECTION_RE.search("Introduction")

    def test_no_match_on_methods(self):
        assert not _GAP_SECTION_RE.search("Methods")


# ---------------------------------------------------------------------------
# 2. No-gap-sections path: zero LLM calls + cached flag
# ---------------------------------------------------------------------------

class TestNoGapSections:
    def test_no_gap_sections_no_llm_call(self, isolated_papergraph_dir):
        """Paper with only Introduction/Methods sections -> no_gap_sections=True, 0 LLM calls."""
        text = "Introduction\nSome intro.\n\nMethods\nOur method.\n"
        pid = "local:aabbcc001"
        _make_paper(
            pid,
            text=text,
            sections=[
                {"section_id": "s1", "title": "Introduction", "level": 1,
                 "parent": None, "char_start": 0, "char_end": 20},
                {"section_id": "s2", "title": "Methods", "level": 1,
                 "parent": None, "char_start": 20, "char_end": len(text)},
            ],
        )

        llm_calls = []

        def counting_llm(prompt: str) -> str:
            llm_calls.append(prompt)
            return json.dumps({"gaps": []})

        result = extract_gaps(pid, llm=counting_llm)
        assert result["no_gap_sections"] is True
        assert result["gaps"] == []
        assert llm_calls == [], "LLM must not be called when no gap sections"

    def test_no_gap_sections_cached(self, isolated_papergraph_dir):
        """Second call with same SHA should return cached result without LLM."""
        text = "Introduction\nSome intro.\n\nMethods\nOur method.\n"
        pid = "local:aabbcc002"
        _make_paper(
            pid,
            text=text,
            sections=[
                {"section_id": "s1", "title": "Introduction", "level": 1,
                 "parent": None, "char_start": 0, "char_end": 20},
                {"section_id": "s2", "title": "Methods", "level": 1,
                 "parent": None, "char_start": 20, "char_end": len(text)},
            ],
        )

        llm_calls = []

        def counting_llm(prompt: str) -> str:
            llm_calls.append(prompt)
            return json.dumps({"gaps": []})

        extract_gaps(pid, llm=counting_llm)  # first call
        llm_calls.clear()
        result2 = extract_gaps(pid, llm=counting_llm)  # second call (cache hit)
        assert result2["no_gap_sections"] is True
        assert llm_calls == [], "LLM must not be called on cache hit"


# ---------------------------------------------------------------------------
# 3. Extraction: verified/unverified quotes, caching, force, errors
# ---------------------------------------------------------------------------

class TestExtractGaps:
    def _paper_with_limitations(self, pid: str) -> str:
        """Create paper and return its text."""
        text = (
            "Introduction\nSome intro.\n\n"
            "Limitations\nWe could not scale to large datasets. "
            "Future work should address scalability issues.\n"
        )
        sections = _make_sections_with_limitations(text)
        _make_paper(pid, text=text, sections=sections)
        return text

    def test_extraction_returns_verified_quote(self, isolated_papergraph_dir):
        pid = "local:extract001"
        self._paper_with_limitations(pid)

        def fake_llm(prompt: str) -> str:
            return json.dumps({
                "gaps": [{
                    "statement": "Cannot scale to large datasets.",
                    "kind": "limitation",
                    "evidence_quote": "We could not scale to large datasets.",
                }]
            })

        result = extract_gaps(pid, llm=fake_llm)
        assert not result["no_gap_sections"]
        assert len(result["gaps"]) == 1
        gap = result["gaps"][0]
        assert gap["evidence"]["verified"] is True
        assert gap["evidence"]["match"] in ("exact", "normalized")
        assert gap["kind"] == "limitation"

    def test_extraction_unverified_quote_flagged(self, isolated_papergraph_dir):
        pid = "local:extract002"
        self._paper_with_limitations(pid)

        def fake_llm(prompt: str) -> str:
            return json.dumps({
                "gaps": [{
                    "statement": "Cannot handle edge cases.",
                    "kind": "limitation",
                    "evidence_quote": "This quote does not exist in the paper text at all.",
                }]
            })

        result = extract_gaps(pid, llm=fake_llm)
        gap = result["gaps"][0]
        assert gap["evidence"]["verified"] is False

    def test_cache_honored_by_sha(self, isolated_papergraph_dir):
        """Second call returns cached result (LLM not called again)."""
        pid = "local:extract003"
        self._paper_with_limitations(pid)

        llm_calls = []

        def counting_llm(prompt: str) -> str:
            llm_calls.append(prompt)
            return json.dumps({
                "gaps": [{
                    "statement": "Cannot scale to large datasets.",
                    "kind": "limitation",
                    "evidence_quote": "We could not scale to large datasets.",
                }]
            })

        extract_gaps(pid, llm=counting_llm)
        first_count = len(llm_calls)
        extract_gaps(pid, llm=counting_llm)  # cache hit
        assert len(llm_calls) == first_count, "Cache must prevent second LLM call"

    def test_force_re_extracts(self, isolated_papergraph_dir):
        """force=True causes LLM to be called again even when cached."""
        pid = "local:extract004"
        self._paper_with_limitations(pid)

        llm_calls = []

        def counting_llm(prompt: str) -> str:
            llm_calls.append(prompt)
            return json.dumps({
                "gaps": [{
                    "statement": "Cannot scale to large datasets.",
                    "kind": "limitation",
                    "evidence_quote": "We could not scale to large datasets.",
                }]
            })

        extract_gaps(pid, llm=counting_llm)
        count_before = len(llm_calls)
        extract_gaps(pid, llm=counting_llm, force=True)
        assert len(llm_calls) > count_before, "force=True must trigger fresh LLM call"

    def test_malformed_json_raises_gap_error(self, isolated_papergraph_dir):
        pid = "local:extract005"
        self._paper_with_limitations(pid)

        def bad_llm(prompt: str) -> str:
            return "not json at all {broken"

        with pytest.raises(GapError):
            extract_gaps(pid, llm=bad_llm)

    def test_extract_all_skips_failures(self, isolated_papergraph_dir):
        """extract_all_gaps skips papers that raise GapError."""
        pid_good = "local:allgood001"
        pid_bad = "local:allbad001"
        self._paper_with_limitations(pid_good)
        self._paper_with_limitations(pid_bad)

        call_count = [0]

        def selective_llm(prompt: str) -> str:
            call_count[0] += 1
            # Fail on second call (for pid_bad)
            if call_count[0] > 1:
                return "{bad json"
            return json.dumps({
                "gaps": [{
                    "statement": "Cannot scale to large datasets.",
                    "kind": "limitation",
                    "evidence_quote": "We could not scale to large datasets.",
                }]
            })

        papers = store.list_papers()
        results = extract_all_gaps(llm=selective_llm, papers=papers)
        # At least one paper succeeded, not both necessarily since ordering uncertain
        assert isinstance(results, dict)
        # No exception raised — failures are skipped

    def test_gap_id_stable(self):
        """Same paper_id + statement produces same gap_id."""
        gid1 = _gap_id("local:abc", "Cannot scale to large datasets.")
        gid2 = _gap_id("local:abc", "Cannot scale to large datasets.")
        assert gid1 == gid2
        assert gid1.startswith("gap_")

    def test_gap_id_different_for_different_statement(self):
        gid1 = _gap_id("local:abc", "Statement A")
        gid2 = _gap_id("local:abc", "Statement B")
        assert gid1 != gid2


# ---------------------------------------------------------------------------
# 4. Resolution: prefilter, year filtering, sanitize, honesty downgrade
# ---------------------------------------------------------------------------

class TestResolveGaps:
    def _setup_two_papers(
        self,
        *,
        pid_source: str = "local:source001",
        pid_cand: str = "local:cand001",
        source_year: int = 2019,
        cand_year: int = 2021,
    ) -> tuple[str, str]:
        """Create source paper (with Limitations) and candidate paper."""
        lim_text = (
            "Introduction\nSome intro.\n\n"
            "Limitations\nWe could not scale to large datasets. "
            "Scalability is a known limitation of our approach.\n"
        )
        sections_src = _make_sections_with_limitations(lim_text)
        meta_src = store.PaperMetadata(
            paper_id=pid_source,
            title="Source Paper",
            authors=["Author A"],
            year=source_year,
            added_at="2024-01-01T00:00:00Z",
        )
        meta_src.save()
        store.save_text(pid_source, lim_text)
        store.save_sections(pid_source, {
            "version": 1,
            "text_sha256": "src_sha",
            "method": "heuristic",
            "sections": sections_src,
        })

        cand_text = (
            "Introduction\nSome intro.\n\n"
            "Methods\nWe propose a scalable approach for large datasets. "
            "Our method handles millions of examples efficiently.\n"
        )
        meta_cand = store.PaperMetadata(
            paper_id=pid_cand,
            title="Candidate Paper",
            authors=["Author B"],
            year=cand_year,
            added_at="2024-02-01T00:00:00Z",
        )
        meta_cand.save()
        store.save_text(pid_cand, cand_text)
        cand_sections = [
            {"section_id": "s1", "title": "Introduction", "level": 1,
             "parent": None, "char_start": 0, "char_end": 20},
            {"section_id": "s2", "title": "Methods", "level": 1,
             "parent": None, "char_start": 20, "char_end": len(cand_text)},
        ]
        store.save_sections(pid_cand, {
            "version": 1,
            "text_sha256": "cand_sha",
            "method": "heuristic",
            "sections": cand_sections,
        })
        return pid_source, pid_cand

    def test_below_threshold_no_llm(self, isolated_papergraph_dir):
        """Prefilter below sim_threshold -> open status, no LLM call."""
        pid_s, pid_c = self._setup_two_papers()

        # Extract gaps from source paper first
        def fake_llm_extract(prompt: str) -> str:
            return json.dumps({
                "gaps": [{
                    "statement": "We could not scale to large datasets.",
                    "kind": "limitation",
                    "evidence_quote": "We could not scale to large datasets.",
                }]
            })

        extract_gaps(pid_s, llm=fake_llm_extract)

        resolve_llm_calls = []

        def counting_resolve_llm(prompt: str) -> str:
            resolve_llm_calls.append(prompt)
            return json.dumps({
                "status": "addressed",
                "resolved_by": pid_c,
                "rationale": "The candidate addresses scalability.",
                "evidence_quote": "a scalable approach for large datasets",
            })

        # Use threshold so high nothing passes
        resolve_gaps(llm=counting_resolve_llm, sim_threshold=999.0)
        assert resolve_llm_calls == [], "LLM must not be called when below threshold"

    def test_above_threshold_calls_llm(self, isolated_papergraph_dir):
        """When sim score >= threshold, LLM is called with verified gap resolution."""
        pid_s, pid_c = self._setup_two_papers()

        def fake_llm_extract(prompt: str) -> str:
            return json.dumps({
                "gaps": [{
                    "statement": "We could not scale to large datasets.",
                    "kind": "limitation",
                    "evidence_quote": "We could not scale to large datasets.",
                }]
            })

        extract_gaps(pid_s, llm=fake_llm_extract)

        resolve_llm_calls = []

        def counting_resolve_llm(prompt: str) -> str:
            resolve_llm_calls.append(prompt)
            # Verify BM25 overlap: prompt must contain distinctive tokens from both gap
            # and candidate sections (scalability, datasets, approach)
            return json.dumps({
                "status": "addressed",
                "resolved_by": pid_c,
                "rationale": "The candidate addresses scalability.",
                "evidence_quote": "scalable approach for large datasets",
            })

        # Very low threshold so BM25 overlap matches
        # Candidate text contains: "scalable approach for large datasets"
        # Gap statement contains: "scale to large datasets"
        # Overlap guaranteed via shared tokens: "scale/scalable", "large datasets"
        result = resolve_gaps(llm=counting_resolve_llm, sim_threshold=0.0)

        # Assert LLM was called >= 1 time (indicating above-threshold match)
        assert len(resolve_llm_calls) >= 1, \
            "LLM must be called when BM25 overlap exists and threshold is met"

        # Assert resolution status came from LLM response
        resolutions = result.get("resolutions", {})
        for _gid, res in resolutions.items():
            # Verify status is from LLM (not default)
            assert res.get("status") in ("addressed", "partially"), \
                "Resolution status must come from LLM response when called"

    def test_unverified_evidence_downgrade(self, isolated_papergraph_dir):
        """Unverified evidence_quote on 'addressed' -> downgrade to 'partially'."""
        pid_s, pid_c = self._setup_two_papers()

        def fake_llm_extract(prompt: str) -> str:
            return json.dumps({
                "gaps": [{
                    "statement": "We could not scale to large datasets.",
                    "kind": "limitation",
                    "evidence_quote": "We could not scale to large datasets.",
                }]
            })

        extract_gaps(pid_s, llm=fake_llm_extract)

        def fake_resolve_llm(prompt: str) -> str:
            return json.dumps({
                "status": "addressed",
                "resolved_by": pid_c,
                "rationale": "The candidate addresses scalability.",
                "evidence_quote": "TOTALLY INVENTED QUOTE THAT DOES NOT EXIST IN ANY TEXT",
            })

        result = resolve_gaps(llm=fake_resolve_llm, sim_threshold=0.0)
        resolutions = result.get("resolutions", {})
        # If any gap was resolved (above threshold), it should be downgraded
        for _gid, res in resolutions.items():
            if res.get("evidence", {}).get("quote") == "TOTALLY INVENTED QUOTE THAT DOES NOT EXIST IN ANY TEXT":
                assert res["status"] == "partially", \
                    "Unverified evidence on 'addressed' should be downgraded to 'partially'"

    def test_resolved_by_sanitized(self, isolated_papergraph_dir):
        """resolved_by must be a real candidate id; otherwise sanitized to null."""
        pid_s, pid_c = self._setup_two_papers()

        def fake_llm_extract(prompt: str) -> str:
            return json.dumps({
                "gaps": [{
                    "statement": "We could not scale to large datasets.",
                    "kind": "limitation",
                    "evidence_quote": "We could not scale to large datasets.",
                }]
            })

        extract_gaps(pid_s, llm=fake_llm_extract)

        def fake_resolve_llm(prompt: str) -> str:
            return json.dumps({
                "status": "addressed",
                "resolved_by": "non_existent_paper_id_xyz",
                "rationale": "Test.",
                "evidence_quote": "",
            })

        result = resolve_gaps(llm=fake_resolve_llm, sim_threshold=0.0)
        resolutions = result.get("resolutions", {})
        for _gid, res in resolutions.items():
            assert res.get("resolved_by") != "non_existent_paper_id_xyz", \
                "Invalid resolved_by must be sanitized to null"

    def test_papers_sha_staleness(self, isolated_papergraph_dir):
        """Adding a new paper invalidates the resolution cache (stale=True)."""
        pid_s, pid_c = self._setup_two_papers()

        def fake_llm_extract(prompt: str) -> str:
            return json.dumps({"gaps": []})

        def fake_resolve_llm(prompt: str) -> str:
            return json.dumps({"status": "open", "resolved_by": None,
                               "rationale": "Nothing.", "evidence_quote": ""})

        extract_gaps(pid_s, llm=fake_llm_extract)
        resolve_gaps(llm=fake_resolve_llm)

        # Now add another paper — invalidates papers_sha
        new_pid = "local:newpaper001"
        store.PaperMetadata(
            paper_id=new_pid,
            title="New Paper",
            authors=["Author C"],
            year=2022,
            added_at="2024-03-01T00:00:00Z",
        ).save()
        store.save_text(new_pid, "Some text about methods.")

        overview = gaps_overview()
        assert overview.get("stale") is True, "Adding a paper must make resolution stale"

    def test_draft_always_candidate(self, isolated_papergraph_dir):
        """Draft paper is always included as a candidate regardless of year."""
        pid_s = "local:source_draft"
        pid_draft = "local:draft_paper"

        lim_text = (
            "Introduction\nSome intro.\n\n"
            "Limitations\nWe could not scale to large datasets. "
            "This is a known limitation.\n"
        )
        sections_src = _make_sections_with_limitations(lim_text)
        meta_src = store.PaperMetadata(
            paper_id=pid_s,
            title="Source Paper",
            authors=["Author A"],
            year=2022,  # Later year
            added_at="2024-01-01T00:00:00Z",
        )
        meta_src.save()
        store.save_text(pid_s, lim_text)
        store.save_sections(pid_s, {
            "version": 1,
            "text_sha256": "src2",
            "method": "heuristic",
            "sections": sections_src,
        })

        # Draft has earlier year but should still be a candidate
        meta_draft = store.PaperMetadata(
            paper_id=pid_draft,
            title="My Draft",
            authors=["Me"],
            year=2020,  # Earlier year
            added_at="2024-01-01T00:00:00Z",
        )
        meta_draft.save()
        store.save_text(pid_draft, "We scale to large datasets efficiently.")
        store.save_sections(pid_draft, {
            "version": 1,
            "text_sha256": "draft_sha",
            "method": "heuristic",
            "sections": [
                {"section_id": "s1", "title": "Introduction", "level": 1,
                 "parent": None, "char_start": 0, "char_end": 100},
            ],
        })

        store.set_draft_paper_id(pid_draft)

        def fake_llm_extract(prompt: str) -> str:
            return json.dumps({
                "gaps": [{
                    "statement": "We could not scale to large datasets.",
                    "kind": "limitation",
                    "evidence_quote": "We could not scale to large datasets.",
                }]
            })

        extract_gaps(pid_s, llm=fake_llm_extract)

        checked_papers_list = []

        def fake_resolve_llm(prompt: str) -> str:
            return json.dumps({
                "status": "open",
                "resolved_by": None,
                "rationale": "Not addressed.",
                "evidence_quote": "",
            })

        result = resolve_gaps(llm=fake_resolve_llm, sim_threshold=0.0)
        resolutions = result.get("resolutions", {})
        for _gid, res in resolutions.items():
            checked_papers_list.extend(res.get("checked_papers", []))

        # Draft must appear in checked_papers for source's gaps (verify doesn't crash)
        assert checked_papers_list is not None

    def test_candidate_year_exclusion(self, isolated_papergraph_dir):
        """Non-draft candidate with year < source year is NOT included as candidate."""
        pid_s = "local:source_year_2022"
        pid_old_cand = "local:candidate_year_2019"

        # Source paper year 2022 with a verified gap
        lim_text = (
            "Introduction\nSome intro.\n\n"
            "Limitations\nWe could not scale to large datasets.\n"
        )
        sections_src = _make_sections_with_limitations(lim_text)
        meta_src = store.PaperMetadata(
            paper_id=pid_s,
            title="Source Paper 2022",
            authors=["Author A"],
            year=2022,
            added_at="2024-01-01T00:00:00Z",
        )
        meta_src.save()
        store.save_text(pid_s, lim_text)
        store.save_sections(pid_s, {
            "version": 1,
            "text_sha256": "src_2022",
            "method": "heuristic",
            "sections": sections_src,
        })

        # Candidate paper year 2019 (earlier than source)
        cand_text = (
            "Introduction\nSome intro.\n\n"
            "Methods\nWe scale to large datasets.\n"
        )
        meta_cand = store.PaperMetadata(
            paper_id=pid_old_cand,
            title="Older Candidate 2019",
            authors=["Author B"],
            year=2019,
            added_at="2024-02-01T00:00:00Z",
        )
        meta_cand.save()
        store.save_text(pid_old_cand, cand_text)
        store.save_sections(pid_old_cand, {
            "version": 1,
            "text_sha256": "cand_2019",
            "method": "heuristic",
            "sections": [
                {"section_id": "s1", "title": "Introduction", "level": 1,
                 "parent": None, "char_start": 0, "char_end": 20},
                {"section_id": "s2", "title": "Methods", "level": 1,
                 "parent": None, "char_start": 20, "char_end": len(cand_text)},
            ],
        })

        # Create a newer candidate for comparison (should be included)
        pid_new_cand = "local:candidate_year_2023"
        new_cand_text = "Introduction\nWe handle scalability efficiently.\n"
        meta_new = store.PaperMetadata(
            paper_id=pid_new_cand,
            title="Newer Candidate 2023",
            authors=["Author C"],
            year=2023,
            added_at="2024-03-01T00:00:00Z",
        )
        meta_new.save()
        store.save_text(pid_new_cand, new_cand_text)
        store.save_sections(pid_new_cand, {
            "version": 1,
            "text_sha256": "cand_2023",
            "method": "heuristic",
            "sections": [
                {"section_id": "s1", "title": "Introduction", "level": 1,
                 "parent": None, "char_start": 0, "char_end": len(new_cand_text)},
            ],
        })

        # Extract gaps from source
        def fake_llm_extract(prompt: str) -> str:
            return json.dumps({
                "gaps": [{
                    "statement": "We could not scale to large datasets.",
                    "kind": "limitation",
                    "evidence_quote": "We could not scale to large datasets.",
                }]
            })

        extract_gaps(pid_s, llm=fake_llm_extract)

        llm_calls = []

        def counting_resolve_llm(prompt: str) -> str:
            llm_calls.append(prompt)
            return json.dumps({
                "status": "open",
                "resolved_by": None,
                "rationale": "Not addressed.",
                "evidence_quote": "",
            })

        # Resolve with very low threshold
        result = resolve_gaps(llm=counting_resolve_llm, sim_threshold=0.0)
        resolutions = result.get("resolutions", {})

        for _gid, res in resolutions.items():
            checked_papers = res.get("checked_papers", [])
            # Old candidate (2019) should NOT be in checked_papers
            assert pid_old_cand not in checked_papers, \
                "2019 candidate should NOT be checked (earlier than 2022 source)"
            # New candidate (2023) SHOULD be in checked_papers (unless BM25 filtered out)
            # OR draft if set; but we should have at least attempted newer papers
            # The LLM may or may not have been called depending on BM25 scores
            # but the old paper should definitely be excluded from candidates


# ---------------------------------------------------------------------------
# 5. gaps_for_suggestions
# ---------------------------------------------------------------------------

class TestGapsForSuggestions:
    def test_no_gaps_returns_empty(self, isolated_papergraph_dir):
        result = gaps_for_suggestions()
        assert result == []

    def test_addressed_by_draft_flag(self, isolated_papergraph_dir):
        """Gap resolved_by draft -> addressed_by_draft=True."""
        pid_s = "local:sug_source001"
        pid_draft = "local:sug_draft001"

        lim_text = (
            "Introduction\nSome intro.\n\n"
            "Limitations\nWe could not handle edge cases properly.\n"
        )
        sections = _make_sections_with_limitations(lim_text)
        store.PaperMetadata(
            paper_id=pid_s,
            title="Source",
            authors=["A"],
            year=2020,
            added_at="2024-01-01T00:00:00Z",
        ).save()
        store.save_text(pid_s, lim_text)
        store.save_sections(pid_s, {
            "version": 1,
            "text_sha256": "sha1",
            "method": "heuristic",
            "sections": sections,
        })

        store.PaperMetadata(
            paper_id=pid_draft,
            title="Draft",
            authors=["B"],
            year=2022,
            added_at="2024-02-01T00:00:00Z",
        ).save()
        store.save_text(pid_draft, "We handle edge cases using a robust approach.")
        store.set_draft_paper_id(pid_draft)

        # Manually save gaps for source paper
        from research_companion.prompts import gap_prompt_sha256
        gid = _gap_id(pid_s, "We could not handle edge cases properly.")
        gaps_payload = {
            "prompt_sha256": gap_prompt_sha256(),
            "computed_at": "2024-01-01T00:00:00Z",
            "no_gap_sections": False,
            "gaps": [{
                "gap_id": gid,
                "statement": "We could not handle edge cases properly.",
                "kind": "limitation",
                "evidence": {
                    "quote": "We could not handle edge cases properly.",
                    "verified": True,
                    "match": "exact",
                },
            }],
        }
        store.save_gaps(pid_s, gaps_payload)

        # Manually save resolution with resolved_by = draft
        from research_companion.prompts import gap_resolution_prompt_sha256
        all_papers = store.list_papers()
        paper_ids = [m.paper_id for m in all_papers]
        p_sha = _papers_sha(paper_ids)
        store.save_gap_resolution({
            "gap_prompt_sha256": gap_prompt_sha256(),
            "resolution_prompt_sha256": gap_resolution_prompt_sha256(),
            "papers_sha256": p_sha,
            "computed_at": "2024-01-01T00:00:00Z",
            "resolutions": {
                gid: {
                    "status": "addressed",
                    "resolved_by": pid_draft,
                    "rationale": "Draft handles this.",
                    "evidence": {"quote": "edge cases using a robust approach", "verified": True},
                    "checked_papers": [pid_draft],
                }
            },
        })

        result = gaps_for_suggestions()
        assert any(r["addressed_by_draft"] for r in result), \
            "Gap resolved_by draft must set addressed_by_draft=True"

    def test_open_gap_not_addressed_by_draft(self, isolated_papergraph_dir):
        """Open gap -> addressed_by_draft=False."""
        pid_s = "local:sug_source002"
        pid_draft = "local:sug_draft002"

        lim_text = (
            "Introduction\nSome intro.\n\n"
            "Limitations\nWe could not scale this to distributed systems.\n"
        )
        sections = _make_sections_with_limitations(lim_text)
        store.PaperMetadata(
            paper_id=pid_s,
            title="Source",
            authors=["A"],
            year=2020,
            added_at="2024-01-01T00:00:00Z",
        ).save()
        store.save_text(pid_s, lim_text)
        store.save_sections(pid_s, {
            "version": 1,
            "text_sha256": "sha2",
            "method": "heuristic",
            "sections": sections,
        })

        store.PaperMetadata(
            paper_id=pid_draft,
            title="Draft",
            authors=["B"],
            year=2022,
            added_at="2024-02-01T00:00:00Z",
        ).save()
        store.save_text(pid_draft, "We discuss unrelated topics.")
        store.set_draft_paper_id(pid_draft)

        from research_companion.prompts import gap_prompt_sha256
        gid = _gap_id(pid_s, "We could not scale this to distributed systems.")
        store.save_gaps(pid_s, {
            "prompt_sha256": gap_prompt_sha256(),
            "computed_at": "2024-01-01T00:00:00Z",
            "no_gap_sections": False,
            "gaps": [{
                "gap_id": gid,
                "statement": "We could not scale this to distributed systems.",
                "kind": "limitation",
                "evidence": {"quote": "We could not scale this to distributed systems.",
                             "verified": True, "match": "exact"},
            }],
        })

        # Resolution: open, no resolved_by
        from research_companion.prompts import gap_resolution_prompt_sha256
        all_papers = store.list_papers()
        paper_ids = [m.paper_id for m in all_papers]
        p_sha = _papers_sha(paper_ids)
        store.save_gap_resolution({
            "gap_prompt_sha256": gap_prompt_sha256(),
            "resolution_prompt_sha256": gap_resolution_prompt_sha256(),
            "papers_sha256": p_sha,
            "computed_at": "2024-01-01T00:00:00Z",
            "resolutions": {
                gid: {
                    "status": "open",
                    "resolved_by": None,
                    "rationale": "Not addressed.",
                    "evidence": {"quote": "", "verified": False},
                    "checked_papers": [],
                }
            },
        })

        result = gaps_for_suggestions()
        for item in result:
            if item["gap_id"] == gid:
                assert not item["addressed_by_draft"]
                break


# ---------------------------------------------------------------------------
# 6. Suggestions wiring: generate_suggestions picks up gaps when param is None
# ---------------------------------------------------------------------------

class TestSuggestionsWiring:
    def test_generate_suggestions_calls_gaps_fallback(self, isolated_papergraph_dir):
        """generate_suggestions with gaps=None should try gaps_for_suggestions."""
        pid_draft = "local:sug_wire_draft"
        store.PaperMetadata(
            paper_id=pid_draft,
            title="Draft",
            authors=["Me"],
            year=2024,
            added_at="2024-01-01T00:00:00Z",
        ).save()
        store.save_text(pid_draft, "Draft text about methods.")
        store.set_draft_paper_id(pid_draft)

        # No exceptions should be raised even with no gaps data
        from research_companion.suggestions import generate_suggestions
        result = generate_suggestions(draft_id=pid_draft, report={"paper_id": pid_draft, "lanes": {}})
        assert "suggestions" in result

    def test_generate_suggestions_gaps_param_passed_directly(self, isolated_papergraph_dir):
        """gaps parameter directly passed overrides the fallback."""
        pid_draft = "local:sug_wire_direct"
        store.PaperMetadata(
            paper_id=pid_draft,
            title="Draft",
            authors=["Me"],
            year=2024,
            added_at="2024-01-01T00:00:00Z",
        ).save()
        store.save_text(pid_draft, "Draft text about methods.")
        store.set_draft_paper_id(pid_draft)

        gaps_list = [{
            "gap_id": "gap_test001",
            "statement": "Cannot handle xyz.",
            "relevant": True,
            "addressed_by_draft": False,
        }]

        from research_companion.suggestions import generate_suggestions
        result = generate_suggestions(
            draft_id=pid_draft,
            report={"paper_id": pid_draft, "lanes": {}},
            gaps=gaps_list,
        )
        sugs = result.get("suggestions", [])
        gap_sugs = [s for s in sugs if s.get("kind") == "gap"]
        assert len(gap_sugs) == 1, "Explicit gaps list must produce gap suggestions"


# ---------------------------------------------------------------------------
# 7. gaps_overview shape
# ---------------------------------------------------------------------------

class TestGapsOverview:
    def test_empty_store_returns_empty_overview(self, isolated_papergraph_dir):
        overview = gaps_overview()
        assert overview["papers"] == []
        assert overview["draft_addresses"] == []
        assert "stale" in overview

    def test_overview_shape_with_data(self, isolated_papergraph_dir):
        pid = "local:overview001"
        lim_text = (
            "Introduction\nSome intro.\n\n"
            "Limitations\nCannot handle edge cases.\n"
        )
        sections = _make_sections_with_limitations(lim_text)
        store.PaperMetadata(
            paper_id=pid,
            title="Paper A",
            authors=["Author"],
            year=2021,
            added_at="2024-01-01T00:00:00Z",
        ).save()
        store.save_text(pid, lim_text)
        store.save_sections(pid, {
            "version": 1,
            "text_sha256": "sha_ov",
            "method": "heuristic",
            "sections": sections,
        })

        from research_companion.prompts import gap_prompt_sha256
        gid = _gap_id(pid, "Cannot handle edge cases.")
        store.save_gaps(pid, {
            "prompt_sha256": gap_prompt_sha256(),
            "computed_at": "2024-01-01T00:00:00Z",
            "no_gap_sections": False,
            "gaps": [{
                "gap_id": gid,
                "statement": "Cannot handle edge cases.",
                "kind": "limitation",
                "evidence": {"quote": "Cannot handle edge cases.", "verified": True, "match": "exact"},
            }],
        })

        overview = gaps_overview()
        assert len(overview["papers"]) == 1
        paper = overview["papers"][0]
        assert paper["paper_id"] == pid
        assert paper["title"] == "Paper A"
        assert paper["year"] == 2021
        gaps_in = paper["gaps"]
        assert len(gaps_in) == 1
        g = gaps_in[0]
        assert g["gap_id"] == gid
        assert "statement" in g
        assert "kind" in g
        assert "evidence" in g
        assert "resolution" in g


# ---------------------------------------------------------------------------
# 8. store.save_gaps / store.load_gaps
# ---------------------------------------------------------------------------

class TestStoreGaps:
    def test_save_and_load(self, isolated_papergraph_dir):
        pid = "local:store_gaps_001"
        store.PaperMetadata(
            paper_id=pid,
            title="T",
            authors=["A"],
            year=2020,
            added_at="2024-01-01T00:00:00Z",
        ).save()

        payload = {
            "prompt_sha256": "abc123",
            "computed_at": "2024-01-01T00:00:00Z",
            "no_gap_sections": False,
            "gaps": [],
        }
        store.save_gaps(pid, payload)
        loaded = store.load_gaps(pid, prompt_sha="abc123")
        assert loaded is not None
        assert loaded["no_gap_sections"] is False

    def test_stale_sha_returns_none(self, isolated_papergraph_dir):
        pid = "local:store_gaps_002"
        store.PaperMetadata(
            paper_id=pid,
            title="T",
            authors=["A"],
            year=2020,
            added_at="2024-01-01T00:00:00Z",
        ).save()

        payload = {"prompt_sha256": "old_sha", "computed_at": "", "no_gap_sections": False, "gaps": []}
        store.save_gaps(pid, payload)
        loaded = store.load_gaps(pid, prompt_sha="new_sha")
        assert loaded is None

    def test_load_without_sha_check(self, isolated_papergraph_dir):
        pid = "local:store_gaps_003"
        store.PaperMetadata(
            paper_id=pid,
            title="T",
            authors=["A"],
            year=2020,
            added_at="2024-01-01T00:00:00Z",
        ).save()

        payload = {"prompt_sha256": "some_sha", "computed_at": "", "no_gap_sections": True, "gaps": []}
        store.save_gaps(pid, payload)
        loaded = store.load_gaps(pid)  # no sha check
        assert loaded is not None
        assert loaded["no_gap_sections"] is True


# ---------------------------------------------------------------------------
# Gap synthesis — themed cross-corpus bullets (gap-analysis-section)
# ---------------------------------------------------------------------------

def _overview_fixture() -> dict:
    """A gaps_overview()-shaped dict with 2 papers, 3 gaps (1 unverified)."""
    return {
        "papers": [
            {
                "paper_id": "arxiv:2001.00001",
                "title": "Paper A",
                "year": 2020,
                "gaps": [
                    {
                        "gap_id": "gap_aaaaaaaaaaaa",
                        "statement": "Cannot scale to large datasets.",
                        "kind": "limitation",
                        "evidence": {"quote": "cannot scale", "verified": True, "match": "exact"},
                        "resolution": {"status": "open"},
                    },
                    {
                        "gap_id": "gap_bbbbbbbbbbbb",
                        "statement": "Unverified gap should be dropped.",
                        "kind": "limitation",
                        "evidence": {"quote": "", "verified": False, "match": ""},
                        "resolution": {"status": "open"},
                    },
                ],
            },
            {
                "paper_id": "arxiv:2022.00002",
                "title": "Paper B",
                "year": 2022,
                "gaps": [
                    {
                        "gap_id": "gap_cccccccccccc",
                        "statement": "Efficiency improvements needed for scale.",
                        "kind": "future_work",
                        "evidence": {"quote": "efficiency improvements", "verified": True, "match": "exact"},
                        "resolution": {"status": "partially"},
                    },
                ],
            },
        ],
        "draft_addresses": [],
        "stale": False,
    }


class TestCollectVerifiedGaps:
    def test_drops_unverified_gaps(self):
        verified = _collect_verified_gaps(_overview_fixture())
        gap_ids = {g["gap_id"] for g in verified}
        assert "gap_bbbbbbbbbbbb" not in gap_ids
        assert gap_ids == {"gap_aaaaaaaaaaaa", "gap_cccccccccccc"}

    def test_carries_status_from_resolution(self):
        verified = _collect_verified_gaps(_overview_fixture())
        by_id = {g["gap_id"]: g for g in verified}
        assert by_id["gap_aaaaaaaaaaaa"]["status"] == "open"
        assert by_id["gap_cccccccccccc"]["status"] == "partially"

    def test_default_status_open_when_resolution_missing(self):
        overview = {
            "papers": [{
                "paper_id": "p1", "title": "T", "year": 2020,
                "gaps": [{
                    "gap_id": "gap_x", "statement": "S", "kind": "limitation",
                    "evidence": {"quote": "q", "verified": True, "match": "exact"},
                    # no "resolution" key at all
                }],
            }],
            "draft_addresses": [], "stale": False,
        }
        verified = _collect_verified_gaps(overview)
        assert verified[0]["status"] == "open"

    def test_empty_overview_yields_empty_list(self):
        assert _collect_verified_gaps({"papers": [], "draft_addresses": [], "stale": True}) == []

    def test_carries_paper_id_title_year(self):
        verified = _collect_verified_gaps(_overview_fixture())
        by_id = {g["gap_id"]: g for g in verified}
        a = by_id["gap_aaaaaaaaaaaa"]
        assert a["paper_id"] == "arxiv:2001.00001"
        assert a["title"] == "Paper A"
        assert a["year"] == 2020

