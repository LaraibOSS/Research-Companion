"""Tests for the /api/draft/placement endpoint (citation placement check)."""
from __future__ import annotations

import pytest

from research_companion import store

_fastapi = pytest.importorskip("fastapi", reason="fastapi required for lab_api tests")
from fastapi.testclient import TestClient  # noqa: E402

from research_companion.agents.bus import Bus  # noqa: E402
from research_companion.lab_api import create_lab_app  # noqa: E402

_DRAFT_TEXT = (
    "Introduction\n"
    "We build on attention models [1] and BERT [2].\n\n"
    "Methods\n"
    "Our approach extends transformers [1].\n\n"
    "References\n"
    "[1] A. Vaswani et al. Attention is all you need. NeurIPS, 2017.\n"
    "[2] J. Devlin et al. BERT pre training of deep bidirectional transformers. 2018.\n"
    "[3] T. Brown et al. Language models are few shot learners in context. 2020.\n"
)


def _seed_draft(draft_id="local:placedraft01"):
    import hashlib
    store.PaperMetadata(paper_id=draft_id, title="Draft", authors=["Me"],
                        year=2026, added_at="2026-01-01T00:00:00Z").save()
    store.save_text(draft_id, _DRAFT_TEXT)
    store.set_draft_paper_id(draft_id)
    m_methods = _DRAFT_TEXT.index("Methods")
    m_refs = _DRAFT_TEXT.index("References")
    store.save_sections(draft_id, {
        "version": 1,
        "text_sha256": hashlib.sha256(_DRAFT_TEXT.encode()).hexdigest(),
        "method": "test",
        "sections": [
            {"section_id": "s1", "title": "Introduction", "level": 1,
             "parent": None, "char_start": 0, "char_end": m_methods},
            {"section_id": "s2", "title": "Methods", "level": 1,
             "parent": None, "char_start": m_methods, "char_end": m_refs},
            {"section_id": "s3", "title": "References", "level": 1,
             "parent": None, "char_start": m_refs, "char_end": len(_DRAFT_TEXT)},
        ],
    })
    store.PaperMetadata(paper_id="local:attention", title="Attention is all you need",
                        authors=["A"], year=2017, added_at="2026-01-01T00:00:00Z").save()
    return draft_id


def _make_client():
    bus = Bus()
    app = create_lab_app(bus)
    return app, bus, TestClient(app)


class TestGetDraftPlacement:
    def test_no_draft_empty_shape(self, isolated_papergraph_dir):
        _app, _bus, c = _make_client()
        with c:
            data = c.get("/api/draft/placement").json()
        assert data["draft_paper_id"] is None
        assert data["applicable"] is False
        assert data["placements"] == []
        assert data["counts"]["total"] == 0

    def test_computes_placements(self, isolated_papergraph_dir):
        _seed_draft()
        _app, _bus, c = _make_client()
        with c:
            data = c.get("/api/draft/placement").json()
        assert data["applicable"] is True
        ids = {pl["paper_id"] for pl in data["placements"]}
        assert "local:attention" in ids
        # attention is cited in Introduction and Methods
        att = next(pl for pl in data["placements"] if pl["paper_id"] == "local:attention")
        cited = {c["section_id"] for c in att["cited_sections"]}
        assert cited == {"s1", "s2"}
