"""Tests for the reader endpoints — GET /api/papers/{id}/text and /pdf.

Mirrors tests/test_lab_api.py: TestClient (sync) + the autouse
isolated_papergraph_dir fixture from conftest.py.
"""
from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from research_companion.agents.bus import Bus  # noqa: E402
from research_companion.lab_api import create_lab_app  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FULL_TEXT = (
    "This is the full text of the Reader Paper. "
    "It discusses knowledge graphs and retrieval methods in detail."
)


def _make_client(bus: Bus | None = None, llm=None) -> TestClient:
    if bus is None:
        bus = Bus()
    return TestClient(create_lab_app(bus, llm=llm))


def _seed_paper(paper_id: str, *, title: str = "Reader Paper",
                text: str = _FULL_TEXT, sections: list[dict] | None = None,
                pdf: bytes | None = None) -> None:
    """Seed a paper's text / metadata / sections / pdf in the store."""
    from research_companion import store

    store.save_text(paper_id, text)
    store.PaperMetadata(
        paper_id=paper_id,
        title=title,
        authors=["Author One"],
        year=2023,
        added_at="2024-01-01T00:00:00Z",
    ).save()
    if sections is not None:
        store.save_sections(paper_id, {"sections": sections})
    if pdf is not None:
        store.save_pdf(paper_id, pdf)


# ---------------------------------------------------------------------------
# GET /api/papers/{id}/text
# ---------------------------------------------------------------------------

class TestReaderText:
    def test_real_sections(self, isolated_papergraph_dir):
        paper_id = "arxiv:1234.56789"
        secs = [
            {"section_id": "s1", "title": "Introduction", "level": 1,
             "parent": None, "char_start": 0, "char_end": 43},
            {"section_id": "s2", "title": "Methods", "level": 2,
             "parent": None, "char_start": 43, "char_end": len(_FULL_TEXT)},
        ]
        _seed_paper(paper_id, sections=secs)
        c = _make_client()

        resp = c.get(f"/api/papers/{paper_id}/text")
        assert resp.status_code == 200
        data = resp.json()
        assert data["paper_id"] == paper_id
        assert data["title"] == "Reader Paper"
        assert data["full_text"] == _FULL_TEXT
        assert data["has_pdf"] is False
        assert data["quote_range"] is None
        assert len(data["sections"]) == 2
        s0 = data["sections"][0]
        assert s0 == {"section_id": "s1", "title": "Introduction", "level": 1,
                      "char_start": 0, "char_end": 43}
        assert set(data["sections"][1]) == {
            "section_id", "title", "level", "char_start", "char_end"}

    def test_no_sections_synthesizes_one(self, isolated_papergraph_dir):
        paper_id = "arxiv:9999.00000"
        _seed_paper(paper_id)  # no sections.json
        c = _make_client()

        resp = c.get(f"/api/papers/{paper_id}/text")
        assert resp.status_code == 200
        data = resp.json()
        assert data["sections"] == [{
            "section_id": "s1", "title": "Full text", "level": 1,
            "char_start": 0, "char_end": len(_FULL_TEXT)}]

    def test_empty_sections_list_synthesizes_one(self, isolated_papergraph_dir):
        paper_id = "arxiv:8888.00000"
        _seed_paper(paper_id, sections=[])  # sections.json with empty list
        c = _make_client()

        resp = c.get(f"/api/papers/{paper_id}/text")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["sections"]) == 1
        assert data["sections"][0]["title"] == "Full text"
        assert data["sections"][0]["char_end"] == len(_FULL_TEXT)

    def test_unknown_paper_returns_404(self, isolated_papergraph_dir):
        c = _make_client()
        resp = c.get("/api/papers/arxiv:does.not.exist/text")
        assert resp.status_code == 404

    def test_title_falls_back_to_paper_id(self, isolated_papergraph_dir):
        """Text present but no metadata.json — title == paper_id."""
        from research_companion import store
        paper_id = "arxiv:notitle01"
        store.save_text(paper_id, _FULL_TEXT)
        c = _make_client()

        resp = c.get(f"/api/papers/{paper_id}/text")
        assert resp.status_code == 200
        assert resp.json()["title"] == paper_id

    def test_has_pdf_true_when_pdf_saved(self, isolated_papergraph_dir, fake_pdf_bytes):
        paper_id = "arxiv:withpdf01"
        _seed_paper(paper_id, pdf=fake_pdf_bytes)
        c = _make_client()

        resp = c.get(f"/api/papers/{paper_id}/text")
        assert resp.status_code == 200
        assert resp.json()["has_pdf"] is True

    def test_quote_range_exact_substring(self, isolated_papergraph_dir):
        paper_id = "arxiv:quote0001"
        _seed_paper(paper_id)
        c = _make_client()

        q = "knowledge graphs and retrieval"
        resp = c.get(f"/api/papers/{paper_id}/text", params={"q": q})
        assert resp.status_code == 200
        data = resp.json()
        a, b = data["quote_range"]
        assert data["full_text"][a:b] == q

    def test_quote_range_whitespace_case_insensitive(self, isolated_papergraph_dir):
        paper_id = "arxiv:quote0002"
        _seed_paper(paper_id)
        c = _make_client()

        q = "KNOWLEDGE   GRAPHS AND RETRIEVAL"
        resp = c.get(f"/api/papers/{paper_id}/text", params={"q": q})
        assert resp.status_code == 200
        rng = resp.json()["quote_range"]
        assert rng is not None
        a, b = rng
        assert 0 <= a < b <= len(_FULL_TEXT)

    def test_quote_range_absent_quote_is_null(self, isolated_papergraph_dir):
        paper_id = "arxiv:quote0003"
        _seed_paper(paper_id)
        c = _make_client()

        resp = c.get(f"/api/papers/{paper_id}/text",
                     params={"q": "this phrase is absent entirely"})
        assert resp.status_code == 200
        assert resp.json()["quote_range"] is None

    def test_no_q_param_null_range(self, isolated_papergraph_dir):
        paper_id = "arxiv:quote0004"
        _seed_paper(paper_id)
        c = _make_client()

        resp = c.get(f"/api/papers/{paper_id}/text")
        assert resp.status_code == 200
        assert resp.json()["quote_range"] is None


# ---------------------------------------------------------------------------
# GET /api/papers/{id}/pdf
# ---------------------------------------------------------------------------

class TestReaderPdf:
    def test_pdf_served(self, isolated_papergraph_dir, fake_pdf_bytes):
        paper_id = "arxiv:pdf00001"
        _seed_paper(paper_id, pdf=fake_pdf_bytes)
        c = _make_client()

        resp = c.get(f"/api/papers/{paper_id}/pdf")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/pdf")
        assert resp.content.startswith(b"%PDF-")

    def test_pdf_missing_returns_404(self, isolated_papergraph_dir):
        paper_id = "arxiv:nopdf001"
        _seed_paper(paper_id)  # no pdf
        c = _make_client()

        resp = c.get(f"/api/papers/{paper_id}/pdf")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Traversal guard
# ---------------------------------------------------------------------------

class TestTraversalGuard:
    def test_text_traversal_does_not_leak(self, isolated_papergraph_dir):
        c = _make_client()
        resp = c.get("/api/papers/..%2f..%2fsecret/text")
        # Resolves through the store's _id_to_dirname -> no such paper -> 404.
        # Must never 200 with foreign content.
        assert resp.status_code != 200

    def test_pdf_traversal_does_not_leak(self, isolated_papergraph_dir):
        c = _make_client()
        resp = c.get("/api/papers/..%2f..%2fsecret/pdf")
        assert resp.status_code != 200
