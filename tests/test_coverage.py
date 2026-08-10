"""Tests for research_companion.coverage — Report Coverage / Saturation,
slice 2e-3.

Pipeline under test: _relevant_units (rank ALL units for a question via an
injectable rank_fn shaped exactly like retrieve.rank_units -- called with
k=len(units), a threshold COUNT rather than a top-k -- keep whatever
gaps._relevance_score normalizes to >= threshold) -> _section_coverage
(distinct cited (paper_id, section_id, chunk_index) units intersected with
that relevant set; a 0-denominator surfaces an honest pct 0, never a fake
100) -> score_report (pure orchestration over an already-built report;
builds the unit index once via an injectable build_index_fn; never raises;
additive; non-mutating).

HONESTY: coverage is defined relative to the search's OWN relevance set
(threshold 0.35, the same gate gaps.py/directions.py already use for
"relevant" gating) -- NEVER "% of the whole library". LLM-FREE: pure
retrieval math, no new prompt.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# _relevant_units
# ---------------------------------------------------------------------------

def _stub_rank_fn(results):
    """A rank_fn(question, q_tokens, units, *, k) stub -- shaped exactly
    like retrieve.rank_units -- that returns *results* verbatim regardless
    of its arguments."""
    def _rank(question, q_tokens, units, *, k=6):
        return results
    return _rank


def test_relevant_units_keeps_only_scores_at_or_above_threshold():
    from research_companion.coverage import _relevant_units

    units = [{"paper_id": "p1", "section_id": "s1", "chunk_index": 0}]
    rank_fn = _stub_rank_fn([
        {"unit": {"paper_id": "p1", "section_id": "s1", "chunk_index": 0},
         "score": 0.5, "bm25": 0.5, "cosine": 0.0, "mode": "hybrid"},
        {"unit": {"paper_id": "p2", "section_id": "s1", "chunk_index": 0},
         "score": 0.1, "bm25": 0.1, "cosine": 0.0, "mode": "hybrid"},
    ])
    result = _relevant_units("Q?", units, rank_fn=rank_fn, threshold=0.35)
    assert result == {("p1", "s1", 0)}


def test_relevant_units_empty_units_returns_empty_set():
    from research_companion.coverage import _relevant_units
    result = _relevant_units("Q?", [], rank_fn=_stub_rank_fn([]), threshold=0.35)
    assert result == set()


def test_relevant_units_rank_fn_raising_returns_empty_set_no_raise():
    from research_companion.coverage import _relevant_units

    def _raising_rank_fn(question, q_tokens, units, *, k=6):
        raise RuntimeError("retrieval exploded")

    units = [{"paper_id": "p1", "section_id": "s1", "chunk_index": 0}]
    result = _relevant_units("Q?", units, rank_fn=_raising_rank_fn, threshold=0.35)
    assert result == set()


def test_relevant_units_bm25_degraded_mode_normalizes_via_relevance_score():
    """A degraded (bm25-only) result's raw unbounded score is normalized via
    gaps._relevance_score (s / (s + 1)) before comparing to threshold --
    the same normalization gaps.py/directions.py already rely on so the
    threshold means the same thing regardless of hybrid/bm25 mode."""
    from research_companion.coverage import _relevant_units

    units = [{"paper_id": "p1", "section_id": "s1", "chunk_index": 0}]
    # raw bm25 score 2.0 -> normalized 2.0 / (2.0 + 1.0) = 0.667 >= 0.35
    rank_fn = _stub_rank_fn([
        {"unit": {"paper_id": "p1", "section_id": "s1", "chunk_index": 0},
         "score": 2.0, "bm25": 2.0, "cosine": 0.0, "mode": "bm25"},
    ])
    result = _relevant_units("Q?", units, rank_fn=rank_fn, threshold=0.35)
    assert result == {("p1", "s1", 0)}


def test_relevant_units_non_list_rank_fn_result_returns_empty_set():
    from research_companion.coverage import _relevant_units
    result = _relevant_units("Q?", [{"paper_id": "p1"}],
                              rank_fn=lambda q, t, u, *, k=6: "not a list", threshold=0.35)
    assert result == set()


def test_relevant_units_malformed_entries_are_skipped():
    from research_companion.coverage import _relevant_units
    rank_fn = _stub_rank_fn(["not a dict", {"score": 0.9, "mode": "hybrid"}])  # no "unit" key
    result = _relevant_units("Q?", [{"paper_id": "p1"}], rank_fn=rank_fn, threshold=0.35)
    assert result == set()


# ---------------------------------------------------------------------------
# _section_coverage
# ---------------------------------------------------------------------------

def test_section_coverage_pct_from_cited_over_relevant():
    from research_companion.coverage import _section_coverage

    relevant = {("p1", "s1", 0), ("p1", "s1", 1), ("p2", "s1", 0), ("p2", "s1", 1)}
    section = {"citations": [
        {"paper_id": "p1", "section_id": "s1", "chunk_index": 0},
        {"paper_id": "p2", "section_id": "s1", "chunk_index": 0},
    ]}
    cov = _section_coverage(section, relevant)
    assert cov == {"pct": 50, "cited": 2, "relevant_available": 4}


def test_section_coverage_zero_denominator_is_honest_not_fake_100():
    from research_companion.coverage import _section_coverage
    section = {"citations": [{"paper_id": "p1", "section_id": "s1", "chunk_index": 0}]}
    cov = _section_coverage(section, set())
    assert cov == {"pct": 0, "cited": 0, "relevant_available": 0}


def test_section_coverage_citation_not_in_relevant_set_does_not_inflate():
    from research_companion.coverage import _section_coverage
    relevant = {("p1", "s1", 0)}
    section = {"citations": [{"paper_id": "p9", "section_id": "s9", "chunk_index": 9}]}
    cov = _section_coverage(section, relevant)
    assert cov == {"pct": 0, "cited": 0, "relevant_available": 1}


def test_section_coverage_dedupes_distinct_citation_units():
    from research_companion.coverage import _section_coverage
    relevant = {("p1", "s1", 0)}
    section = {"citations": [
        {"paper_id": "p1", "section_id": "s1", "chunk_index": 0},
        {"paper_id": "p1", "section_id": "s1", "chunk_index": 0},  # duplicate
    ]}
    cov = _section_coverage(section, relevant)
    assert cov == {"pct": 100, "cited": 1, "relevant_available": 1}


def test_section_coverage_malformed_section_never_raises():
    from research_companion.coverage import _section_coverage
    assert _section_coverage(None, {("p1", "s1", 0)}) == {"pct": 0, "cited": 0, "relevant_available": 1}
    assert _section_coverage({"citations": "not a list"}, {("p1", "s1", 0)}) == {
        "pct": 0, "cited": 0, "relevant_available": 1,
    }
    assert _section_coverage({"citations": ["not a dict"]}, {("p1", "s1", 0)}) == {
        "pct": 0, "cited": 0, "relevant_available": 1,
    }
