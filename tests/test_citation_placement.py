"""Tests for research_companion.citation_placement — the draft-quality check
that flags whether cited papers sit in the section where they are most relevant.
Offline throughout (no network, no LLM). Strength scoring is untouched."""
from __future__ import annotations

from research_companion import citation_placement as cp
from research_companion import store

# ---------------------------------------------------------------------------
# Pure helpers: marker expansion
# ---------------------------------------------------------------------------

class TestExpandMarker:
    def test_single(self):
        assert cp._expand_marker("3") == [3]

    def test_comma_list(self):
        assert cp._expand_marker("3, 4, 7") == [3, 4, 7]

    def test_hyphen_range(self):
        assert cp._expand_marker("3-5") == [3, 4, 5]

    def test_endash_range(self):
        assert cp._expand_marker("3–5") == [3, 4, 5]

    def test_mixed(self):
        assert cp._expand_marker("1, 3-5, 9") == [1, 3, 4, 5, 9]

    def test_garbage_is_empty(self):
        assert cp._expand_marker("abc") == []

    def test_insane_range_dropped(self):
        assert cp._expand_marker("1-9999") == []


class TestBibliographyIsNumbered:
    def test_bracketed(self):
        block = "[1] First entry.\n[2] Second entry.\n[3] Third entry.\n"
        assert cp._bibliography_is_numbered(block) is True

    def test_dotted(self):
        block = "1. First entry here.\n2. Second entry here.\n3. Third entry here.\n"
        assert cp._bibliography_is_numbered(block) is True

    def test_author_year_not_numbered(self):
        block = ("Alpha Author. A title here. 2019.\n\n"
                 "Beta Author. Another title. 2020.\n\n"
                 "Gamma Author. A third title. 2021.\n")
        assert cp._bibliography_is_numbered(block) is False


class TestRefsCharStart:
    def test_finds_last_refs_section(self):
        payload = {"sections": [
            {"section_id": "s1", "title": "Introduction", "char_start": 0, "char_end": 50},
            {"section_id": "s2", "title": "References", "char_start": 50, "char_end": 120},
        ]}
        assert cp._refs_char_start(payload) == 50

    def test_none_when_no_refs(self):
        payload = {"sections": [
            {"section_id": "s1", "title": "Introduction", "char_start": 0, "char_end": 50},
        ]}
        assert cp._refs_char_start(payload) is None

    def test_none_payload(self):
        assert cp._refs_char_start(None) is None


# ---------------------------------------------------------------------------
# Fixtures for the integration path
# ---------------------------------------------------------------------------

_DRAFT_ID = "local:draft01"

# Body cites [1] (Introduction + Methods), [2] (Introduction), [3] (Methods).
_DRAFT_TEXT = (
    "Introduction\n"
    "We build on attention models [1] and BERT [2].\n\n"
    "Methods\n"
    "Our approach extends transformers [1] and prior work [3].\n\n"
    "References\n"
    "[1] A. Vaswani et al. Attention is all you need. NeurIPS, 2017.\n"
    "[2] J. Devlin et al. BERT pre training of deep bidirectional transformers. 2018.\n"
    "[3] T. Brown et al. Language models are few shot learners in context. 2020.\n"
)


def _mk_paper(paper_id: str, title: str) -> None:
    store.PaperMetadata(paper_id=paper_id, title=title, authors=["A"],
                        year=2020, added_at="2026-01-01T00:00:00Z").save()


def _save_sections_for(text: str) -> None:
    """Persist a 3-section tree (Introduction / Methods / References) tiling text."""
    m_methods = text.index("Methods")
    m_refs = text.index("References")
    import hashlib
    payload = {
        "version": 1,
        "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "method": "test",
        "sections": [
            {"section_id": "s1", "title": "Introduction", "level": 1,
             "parent": None, "char_start": 0, "char_end": m_methods},
            {"section_id": "s2", "title": "Methods", "level": 1,
             "parent": None, "char_start": m_methods, "char_end": m_refs},
            {"section_id": "s3", "title": "References", "level": 1,
             "parent": None, "char_start": m_refs, "char_end": len(text)},
        ],
    }
    store.save_sections(_DRAFT_ID, payload)


def _save_alignment(candidate_id: str, sections: list[dict]) -> None:
    store.save_alignment(candidate_id, {
        "version": 1,
        "draft_paper_id": _DRAFT_ID,
        "candidate_paper_id": candidate_id,
        "score": 0.7,
        "band": 0.1,
        "verdict": "high",
        "sections": sections,
    })


def _seed_numbered_draft() -> None:
    _mk_paper(_DRAFT_ID, "My Draft")
    store.save_text(_DRAFT_ID, _DRAFT_TEXT)
    store.set_draft_paper_id(_DRAFT_ID)
    _save_sections_for(_DRAFT_TEXT)
    # Library papers matched by title containment against the bibliography entries.
    _mk_paper("local:attention", "Attention is all you need")
    _mk_paper("local:bert", "BERT pre training of deep bidirectional transformers")
    _mk_paper("local:brown", "Language models are few shot learners in context")


# ---------------------------------------------------------------------------
# compute_placement — integration
# ---------------------------------------------------------------------------

class TestComputePlacement:
    def _by_id(self, payload):
        return {pl["paper_id"]: pl for pl in payload["placements"]}

    def test_well_placed(self, isolated_papergraph_dir):
        _seed_numbered_draft()
        # Attention is genuinely relevant to Methods (s2), where it is cited.
        _save_alignment("local:attention", [
            {"section_id": "s2", "section_title": "Methods", "relation": "strengthens",
             "relevance": 0.9, "rationale": "", "evidence": []},
        ])
        payload = cp.compute_placement(_DRAFT_ID)
        assert payload["applicable"] is True
        pl = self._by_id(payload)["local:attention"]
        assert pl["status"] == "well_placed"
        cited_ids = {c["section_id"] for c in pl["cited_sections"]}
        assert cited_ids == {"s1", "s2"}

    def test_misplaced(self, isolated_papergraph_dir):
        _seed_numbered_draft()
        # BERT is cited only in Introduction (s1) but most relevant to Methods (s2).
        _save_alignment("local:bert", [
            {"section_id": "s2", "section_title": "Methods", "relation": "strengthens",
             "relevance": 0.8, "rationale": "", "evidence": []},
        ])
        payload = cp.compute_placement(_DRAFT_ID)
        pl = self._by_id(payload)["local:bert"]
        assert pl["status"] == "misplaced"
        assert pl["best_relevant_section"]["section_id"] == "s2"
        assert "Methods" in pl["detail"]

    def test_unknown_when_no_alignment(self, isolated_papergraph_dir):
        _seed_numbered_draft()
        # Brown ([3]) is cited but has no alignment record.
        payload = cp.compute_placement(_DRAFT_ID)
        pl = self._by_id(payload)["local:brown"]
        assert pl["status"] == "unknown"

    def test_counts_and_ordering(self, isolated_papergraph_dir):
        _seed_numbered_draft()
        _save_alignment("local:attention", [
            {"section_id": "s2", "section_title": "Methods", "relation": "strengthens",
             "relevance": 0.9, "rationale": "", "evidence": []},
        ])
        _save_alignment("local:bert", [
            {"section_id": "s2", "section_title": "Methods", "relation": "strengthens",
             "relevance": 0.8, "rationale": "", "evidence": []},
        ])
        payload = cp.compute_placement(_DRAFT_ID)
        assert payload["counts"] == {"total": 3, "well_placed": 1,
                                     "misplaced": 1, "unknown": 1}
        # Misplaced first (most actionable).
        assert payload["placements"][0]["status"] == "misplaced"

    def test_persisted_and_loadable(self, isolated_papergraph_dir):
        _seed_numbered_draft()
        cp.compute_placement(_DRAFT_ID)
        loaded = cp.load_placement()
        assert loaded is not None
        assert loaded["draft_paper_id"] == _DRAFT_ID
        assert cp.is_stale(loaded, _DRAFT_ID) is False


class TestNotApplicable:
    def test_non_numbered_bibliography(self, isolated_papergraph_dir):
        author_year = (
            "Introduction\nWe cite Smith (2019) and Jones (2020).\n\n"
            "References\n"
            "Alpha Author. A first title long enough here. 2019.\n\n"
            "Beta Author. A second title long enough here. 2020.\n\n"
            "Gamma Author. A third title long enough here. 2021.\n"
        )
        _mk_paper(_DRAFT_ID, "My Draft")
        store.save_text(_DRAFT_ID, author_year)
        store.set_draft_paper_id(_DRAFT_ID)
        # No sections saved: find_references_block falls back to the raw
        # "References" heading, so the block is still located.
        payload = cp.compute_placement(_DRAFT_ID)
        assert payload["applicable"] is False
        assert "not numbered" in payload["reason"].lower()
        assert payload["placements"] == []

    def test_no_bibliography_at_all(self, isolated_papergraph_dir):
        _mk_paper(_DRAFT_ID, "My Draft")
        store.save_text(_DRAFT_ID, "Introduction\nJust prose, no citations here.\n")
        store.set_draft_paper_id(_DRAFT_ID)
        payload = cp.compute_placement(_DRAFT_ID)
        assert payload["applicable"] is False
        assert payload["placements"] == []

    def test_no_text(self, isolated_papergraph_dir):
        _mk_paper(_DRAFT_ID, "My Draft")
        store.set_draft_paper_id(_DRAFT_ID)
        payload = cp.compute_placement(_DRAFT_ID)
        assert payload["applicable"] is False
