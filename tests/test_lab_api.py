"""Tests for research_companion.lab_api — Lab REST + SSE server.

All tests use fastapi.testclient.TestClient (sync) and a tmp isolated store
(the autouse isolated_papergraph_dir fixture from conftest.py handles that).

Pattern mirrors tests/test_dashboard.py.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from research_companion.agents.bus import Bus  # noqa: E402
from research_companion.agents.events import (  # noqa: E402
    GraphDelta,
    JobDone,
    PaperAdded,
)
from research_companion.lab_api import create_lab_app  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_llm(prompt: str) -> str:
    """Minimal fake LLM that returns valid alignment JSON for a single section."""
    return json.dumps({
        "sections": [
            {
                "section_id": "s1",
                "relation": "strengthens",
                "relevance": 0.8,
                "rationale": "Highly relevant",
                "evidence": [],
            }
        ]
    })


def _fake_qa_llm(prompt: str) -> str:
    """Fake LLM for QA: returns answer with [S1] citation tag."""
    return "[S1] This is a test answer about research."


def _fake_compare_llm(prompt: str) -> str:
    """Fake LLM for compare: returns a summary sentence."""
    return "Paper A and Paper B share methods."


def _make_paper(tmp_store: Path, paper_id: str, title: str = "Test Paper",
                authors: list[str] | None = None, year: int = 2023,
                write_extraction: bool = True) -> None:
    """Create a minimal paper in the store for testing."""
    from research_companion import store
    from research_companion.prompts import extraction_prompt_sha256

    meta = store.PaperMetadata(
        paper_id=paper_id,
        title=title,
        authors=authors or ["Author One"],
        year=year,
        added_at="2024-01-01T00:00:00Z",
    )
    meta.save()

    # Write a minimal text file
    store.save_text(paper_id, f"This is the full text of {title}. " * 10)

    if write_extraction:
        extraction = {
            "concepts": [{"name": "Knowledge Graph", "definition": "A graph"}],
            "methods": [{"name": "BM25", "description": "Retrieval"}],
            "datasets": [],
            "claims": [],
            "results": [],
            "related_work": [],
        }
        store.save_extraction(paper_id, extraction, prompt_sha=extraction_prompt_sha256())


def _make_client(bus: Bus | None = None, llm=None) -> TestClient:
    if bus is None:
        bus = Bus()
    app = create_lab_app(bus, llm=llm)
    return TestClient(app)


# ---------------------------------------------------------------------------
# GET / (index)
# ---------------------------------------------------------------------------

class TestIndex:
    def test_serves_html(self, isolated_papergraph_dir):
        c = _make_client()
        resp = c.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "Research Lab" in resp.text

    def test_serves_existing_index_html(self, isolated_papergraph_dir, tmp_path):
        """When lab/static/index.html exists, its content is served."""
        # We can't easily override the static path in tests, but we verify
        # the placeholder is returned when the file doesn't exist.
        c = _make_client()
        resp = c.get("/")
        assert resp.status_code == 200
        assert "<title>" in resp.text.lower() or "research lab" in resp.text.lower()


# ---------------------------------------------------------------------------
# GET /static/*
# ---------------------------------------------------------------------------

class TestStaticMount:
    def test_static_mounted(self, isolated_papergraph_dir):
        """Static mount exists — returns 404 or 200 for missing files, not 500."""
        c = _make_client()
        resp = c.get("/static/nonexistent.js")
        assert resp.status_code in (404, 200)

    def test_static_serves_file(self, isolated_papergraph_dir):
        """A file placed in lab/static/ is served."""
        import research_companion.lab_api as _la_mod
        static_dir = Path(_la_mod.__file__).parent / "lab" / "static"
        test_file = static_dir / "test_asset.txt"
        test_file.write_text("hello static", encoding="utf-8")
        try:
            c = _make_client()
            resp = c.get("/static/test_asset.txt")
            assert resp.status_code == 200
            assert "hello static" in resp.text
        finally:
            test_file.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# GET /api/lab
# ---------------------------------------------------------------------------

class TestGetLab:
    def test_empty_store(self, isolated_papergraph_dir):
        c = _make_client()
        resp = c.get("/api/lab")
        assert resp.status_code == 200
        data = resp.json()
        assert "draft_id" in data
        assert data["paper_count"] == 0
        assert data["node_count"] == 0
        assert data["edge_count"] == 0
        assert data["active_jobs"] == []

    def test_with_papers(self, isolated_papergraph_dir):
        _make_paper(isolated_papergraph_dir, "arxiv:1234.56789", "Test Paper A")
        c = _make_client()
        resp = c.get("/api/lab")
        assert resp.status_code == 200
        data = resp.json()
        assert data["paper_count"] == 1


# ---------------------------------------------------------------------------
# GET /api/papers
# ---------------------------------------------------------------------------

class TestGetPapers:
    def test_empty_store(self, isolated_papergraph_dir):
        c = _make_client()
        resp = c.get("/api/papers")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_paper_shape(self, isolated_papergraph_dir):
        _make_paper(isolated_papergraph_dir, "arxiv:1111.22222", "My Paper")
        c = _make_client()
        resp = c.get("/api/papers")
        assert resp.status_code == 200
        papers = resp.json()
        assert len(papers) == 1
        p = papers[0]
        assert p["paper_id"] == "arxiv:1111.22222"
        assert p["title"] == "My Paper"
        assert "authors" in p
        assert "year" in p
        assert p["status"] in ("done", "failed", "pending")
        assert p["is_draft"] is False
        assert "stance_counts" in p
        sc = p["stance_counts"]
        assert "strengthens" in sc
        assert "challenges" in sc
        assert "alternative" in sc
        assert "added_at" in p

    def test_status_done_when_extraction_cached(self, isolated_papergraph_dir):
        _make_paper(isolated_papergraph_dir, "arxiv:1111.22222", "My Paper",
                    write_extraction=True)
        c = _make_client()
        papers = c.get("/api/papers").json()
        assert papers[0]["status"] == "done"

    def test_status_pending_when_no_extraction(self, isolated_papergraph_dir):
        _make_paper(isolated_papergraph_dir, "arxiv:1111.22222", "My Paper",
                    write_extraction=False)
        c = _make_client()
        papers = c.get("/api/papers").json()
        assert papers[0]["status"] == "pending"

    def test_status_failed_when_failure_registered(self, isolated_papergraph_dir):
        from research_companion import store
        _make_paper(isolated_papergraph_dir, "arxiv:1111.22222", "My Paper",
                    write_extraction=False)
        store.record_failure("arxiv:1111.22222", {"stage": "extract", "error": "oops"})
        c = _make_client()
        papers = c.get("/api/papers").json()
        assert papers[0]["status"] == "failed"
        assert papers[0]["failure_reason"] is not None

    def test_is_draft_flag(self, isolated_papergraph_dir):
        from research_companion import store
        _make_paper(isolated_papergraph_dir, "arxiv:1111.22222", "My Paper")
        store.set_draft_paper_id("arxiv:1111.22222")
        c = _make_client()
        papers = c.get("/api/papers").json()
        assert papers[0]["is_draft"] is True

    def test_strength_from_store(self, isolated_papergraph_dir):
        from research_companion import store
        _make_paper(isolated_papergraph_dir, "arxiv:1111.22222", "My Paper")
        store.save_strength("arxiv:1111.22222", {
            "score": 0.75, "band": "strong", "color": "#3fb950"
        })
        c = _make_client()
        papers = c.get("/api/papers").json()
        assert papers[0]["strength"] is not None
        assert papers[0]["strength"]["score"] == 0.75

    def test_stance_counts_with_alignment(self, isolated_papergraph_dir):
        from research_companion import store
        draft_id = "arxiv:draft001"
        cand_id = "arxiv:cand001"
        _make_paper(isolated_papergraph_dir, draft_id, "Draft Paper")
        _make_paper(isolated_papergraph_dir, cand_id, "Candidate Paper")
        store.set_draft_paper_id(draft_id)
        store.save_alignment(cand_id, {
            "draft_paper_id": draft_id,
            "sections": [
                {"section_id": "s1", "relation": "strengthens", "section_title": "Intro",
                 "relevance": 0.8, "rationale": "good", "evidence": []},
                {"section_id": "s2", "relation": "challenges", "section_title": "Method",
                 "relevance": 0.6, "rationale": "ok", "evidence": []},
            ]
        })
        c = _make_client()
        papers = c.get("/api/papers").json()
        cand = next(p for p in papers if p["paper_id"] == cand_id)
        assert cand["stance_counts"]["strengthens"] == 1
        assert cand["stance_counts"]["challenges"] == 1
        assert cand["stance_counts"]["alternative"] == 0


# ---------------------------------------------------------------------------
# GET /api/draft and POST /api/draft
# ---------------------------------------------------------------------------

class TestDraftEndpoints:
    def test_get_draft_none(self, isolated_papergraph_dir):
        c = _make_client()
        resp = c.get("/api/draft")
        assert resp.status_code == 200
        assert resp.json()["draft_paper_id"] is None

    def test_set_draft(self, isolated_papergraph_dir):
        _make_paper(isolated_papergraph_dir, "arxiv:1111.22222", "My Paper")
        c = _make_client()
        resp = c.post("/api/draft", json={"paper_id": "arxiv:1111.22222"})
        assert resp.status_code == 200
        assert resp.json()["draft_paper_id"] == "arxiv:1111.22222"

    def test_set_draft_unknown_returns_404(self, isolated_papergraph_dir):
        c = _make_client()
        resp = c.post("/api/draft", json={"paper_id": "arxiv:unknown_x99"})
        assert resp.status_code == 404

    def test_clear_draft(self, isolated_papergraph_dir):
        from research_companion import store
        _make_paper(isolated_papergraph_dir, "arxiv:1111.22222", "My Paper")
        store.set_draft_paper_id("arxiv:1111.22222")
        c = _make_client()
        resp = c.post("/api/draft", json={"paper_id": None})
        assert resp.status_code == 200
        assert resp.json()["draft_paper_id"] is None


# ---------------------------------------------------------------------------
# GET /api/sections
# ---------------------------------------------------------------------------

class TestSections:
    def test_no_draft_returns_empty(self, isolated_papergraph_dir):
        c = _make_client()
        resp = c.get("/api/sections")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_with_draft_and_no_sections(self, isolated_papergraph_dir):
        from research_companion import store
        _make_paper(isolated_papergraph_dir, "arxiv:1111.22222", "My Paper")
        store.set_draft_paper_id("arxiv:1111.22222")
        c = _make_client()
        resp = c.get("/api/sections")
        assert resp.status_code == 200
        # No sections.json — may be [] or minimal
        assert isinstance(resp.json(), list)

    def test_with_draft_and_sections(self, isolated_papergraph_dir):
        from research_companion import store
        paper_id = "arxiv:1111.22222"
        _make_paper(isolated_papergraph_dir, paper_id, "My Paper")
        store.set_draft_paper_id(paper_id)
        store.save_sections(paper_id, {
            "sections": [
                {"section_id": "s1", "title": "Introduction", "level": 1,
                 "parent": None, "char_start": 0, "char_end": 100},
                {"section_id": "s2", "title": "Methods", "level": 1,
                 "parent": None, "char_start": 100, "char_end": 200},
            ]
        })
        c = _make_client()
        resp = c.get("/api/sections")
        assert resp.status_code == 200
        sections = resp.json()
        assert len(sections) >= 1
        s = sections[0]
        assert "section_id" in s
        assert "title" in s
        assert "level" in s
        assert "node_count" in s


# ---------------------------------------------------------------------------
# GET /api/graph
# ---------------------------------------------------------------------------

class TestGraph:
    def test_empty_graph(self, isolated_papergraph_dir):
        c = _make_client()
        resp = c.get("/api/graph")
        assert resp.status_code == 200
        data = resp.json()
        assert "seq" in data
        assert "nodes" in data
        assert "edges" in data
        assert data["nodes"] == []
        assert data["edges"] == []

    def test_graph_with_paper(self, isolated_papergraph_dir):
        from research_companion import graph as _g
        _make_paper(isolated_papergraph_dir, "arxiv:1111.22222", "My Paper")
        G = _g.build_graph()
        _g.save_graph(G)
        c = _make_client()
        resp = c.get("/api/graph")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["nodes"]) > 0
        node = data["nodes"][0]
        assert "id" in node
        assert "kind" in node
        assert "label" in node
        assert "sections" in node
        assert "attrs" in node

    def test_graph_section_filter_no_draft_returns_400(self, isolated_papergraph_dir):
        c = _make_client()
        resp = c.get("/api/graph?section=s1")
        assert resp.status_code == 400

    def test_graph_section_filter_with_draft(self, isolated_papergraph_dir):
        from research_companion import graph as _g
        from research_companion import store
        paper_id = "arxiv:1111.22222"
        _make_paper(isolated_papergraph_dir, paper_id, "My Paper")
        store.set_draft_paper_id(paper_id)
        G = _g.build_graph()
        _g.save_graph(G)
        c = _make_client()
        resp = c.get("/api/graph?section=s1")
        # Should return 200 or 400 (no matching section is ok)
        assert resp.status_code in (200, 400)

    def test_graph_node_strength_attr(self, isolated_papergraph_dir):
        from research_companion import graph as _g
        from research_companion import store
        paper_id = "arxiv:1111.22222"
        _make_paper(isolated_papergraph_dir, paper_id, "My Paper")
        store.save_strength(paper_id, {"score": 0.8, "band": "strong", "color": "#3fb950"})
        G = _g.build_graph()
        _g.save_graph(G)
        c = _make_client()
        resp = c.get("/api/graph")
        assert resp.status_code == 200
        nodes = resp.json()["nodes"]
        paper_node = next((n for n in nodes if n["id"] == paper_id), None)
        assert paper_node is not None
        # strength may be present or None depending on graph attrs
        assert "strength" in paper_node


# ---------------------------------------------------------------------------
# GET /api/draft/alignment
# ---------------------------------------------------------------------------

class TestDraftAlignment:
    def test_no_draft_returns_empty(self, isolated_papergraph_dir):
        c = _make_client()
        resp = c.get("/api/draft/alignment")
        assert resp.status_code == 200
        data = resp.json()
        assert data["draft_id"] is None
        assert data["sections"] == []

    def test_aggregated_from_two_papers(self, isolated_papergraph_dir):
        from research_companion import store
        draft_id = "arxiv:draft001"
        cand1_id = "arxiv:cand001"
        cand2_id = "arxiv:cand002"
        for pid, title in [
            (draft_id, "Draft"), (cand1_id, "Candidate 1"), (cand2_id, "Candidate 2")
        ]:
            _make_paper(isolated_papergraph_dir, pid, title)
        store.set_draft_paper_id(draft_id)
        # Save alignment for both candidates
        for cand_id, relation in [(cand1_id, "strengthens"), (cand2_id, "challenges")]:
            store.save_alignment(cand_id, {
                "draft_paper_id": draft_id,
                "sections": [
                    {
                        "section_id": "s1",
                        "section_title": "Introduction",
                        "relation": relation,
                        "relevance": 0.7,
                        "rationale": "Relevant",
                        "evidence": [],
                    }
                ],
                "score": 0.6,
                "verdict": "medium",
            })
        c = _make_client()
        resp = c.get("/api/draft/alignment")
        assert resp.status_code == 200
        data = resp.json()
        assert data["draft_id"] == draft_id
        sections = data["sections"]
        assert len(sections) >= 1
        # Each section has alignments list
        s = sections[0]
        assert "section_id" in s
        assert "title" in s
        assert "alignments" in s
        alignments = s["alignments"]
        assert len(alignments) >= 1
        a = alignments[0]
        assert "paper_id" in a
        assert "paper_title" in a
        assert "relation" in a


# ---------------------------------------------------------------------------
# GET /api/papers/{id}/alignment
# ---------------------------------------------------------------------------

class TestPaperAlignment:
    def test_no_alignment_returns_404(self, isolated_papergraph_dir):
        _make_paper(isolated_papergraph_dir, "arxiv:1111.22222", "My Paper")
        c = _make_client()
        resp = c.get("/api/papers/arxiv:1111.22222/alignment")
        assert resp.status_code == 404

    def test_returns_alignment(self, isolated_papergraph_dir):
        from research_companion import store
        paper_id = "arxiv:1111.22222"
        draft_id = "arxiv:draft001"
        _make_paper(isolated_papergraph_dir, paper_id, "My Paper")
        store.set_draft_paper_id(draft_id)
        store.save_alignment(paper_id, {
            "draft_paper_id": draft_id,
            "sections": [],
            "score": 0.5,
        })
        c = _make_client()
        resp = c.get(f"/api/papers/{paper_id}/alignment")
        assert resp.status_code == 200
        data = resp.json()
        assert data["score"] == 0.5


# ---------------------------------------------------------------------------
# GET /api/failures
# ---------------------------------------------------------------------------

class TestFailures:
    def test_empty(self, isolated_papergraph_dir):
        c = _make_client()
        resp = c.get("/api/failures")
        assert resp.status_code == 200
        assert resp.json() == {}

    def test_with_failures(self, isolated_papergraph_dir):
        from research_companion import store
        store.record_failure("some/path.pdf", {"stage": "extract", "error": "boom"})
        c = _make_client()
        resp = c.get("/api/failures")
        assert resp.status_code == 200
        data = resp.json()
        assert "some/path.pdf" in data


# ---------------------------------------------------------------------------
# DELETE /api/papers/{id}
# ---------------------------------------------------------------------------

class TestDeletePaper:
    def test_delete_existing(self, isolated_papergraph_dir):
        _make_paper(isolated_papergraph_dir, "arxiv:1111.22222", "My Paper")
        c = _make_client()
        resp = c.delete("/api/papers/arxiv:1111.22222")
        assert resp.status_code == 200
        assert resp.json()["removed"] is True

    def test_delete_unknown_returns_404(self, isolated_papergraph_dir):
        c = _make_client()
        resp = c.delete("/api/papers/arxiv:nonexistent")
        assert resp.status_code == 404

    def test_delete_draft_paper_clears_draft(self, isolated_papergraph_dir):
        from research_companion import store
        _make_paper(isolated_papergraph_dir, "arxiv:1111.22222", "Draft Paper")
        store.set_draft_paper_id("arxiv:1111.22222")
        c = _make_client()
        resp = c.delete("/api/papers/arxiv:1111.22222")
        assert resp.status_code == 200
        data = resp.json()
        assert data["removed"] is True
        assert data["draft_cleared"] is True
        assert c.get("/api/draft").json() == {"draft_paper_id": None}

    def test_delete_non_draft_paper_keeps_draft(self, isolated_papergraph_dir):
        from research_companion import store
        _make_paper(isolated_papergraph_dir, "arxiv:draft001", "Draft Paper")
        _make_paper(isolated_papergraph_dir, "arxiv:other001", "Other Paper")
        store.set_draft_paper_id("arxiv:draft001")
        c = _make_client()
        resp = c.delete("/api/papers/arxiv:other001")
        assert resp.status_code == 200
        data = resp.json()
        assert data["removed"] is True
        assert data["draft_cleared"] is False
        assert c.get("/api/draft").json() == {"draft_paper_id": "arxiv:draft001"}


# ---------------------------------------------------------------------------
# PATCH /api/papers/{id} — manual title/authors/year edit
# ---------------------------------------------------------------------------

class TestPatchPaper:
    _SHAPE = {"paper_id", "title", "authors", "year", "status", "strength",
              "is_draft", "stance_counts", "added_at", "failure_reason"}

    def test_patch_title(self, isolated_papergraph_dir):
        _make_paper(isolated_papergraph_dir, "local:abc", "Old", year=2020)
        c = _make_client()
        resp = c.patch("/api/papers/local:abc", json={"title": "New Title"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["title"] == "New Title"
        assert body["paper_id"] == "local:abc"
        # Returns the same per-paper dict shape as GET /api/papers.
        assert set(body) >= self._SHAPE

    def test_patch_authors(self, isolated_papergraph_dir):
        _make_paper(isolated_papergraph_dir, "local:abc", "P", authors=["X"])
        c = _make_client()
        resp = c.patch("/api/papers/local:abc",
                       json={"authors": ["  Ann  ", "", "Bob"]})
        assert resp.status_code == 200
        assert resp.json()["authors"] == ["Ann", "Bob"]

    def test_patch_authors_empty_clears(self, isolated_papergraph_dir):
        _make_paper(isolated_papergraph_dir, "local:abc", "P", authors=["X"])
        c = _make_client()
        resp = c.patch("/api/papers/local:abc", json={"authors": []})
        assert resp.status_code == 200
        assert resp.json()["authors"] == []

    def test_patch_year(self, isolated_papergraph_dir):
        _make_paper(isolated_papergraph_dir, "local:abc", "P", year=2020)
        c = _make_client()
        resp = c.patch("/api/papers/local:abc", json={"year": 1999})
        assert resp.status_code == 200
        assert resp.json()["year"] == 1999

    def test_patch_year_null_clears(self, isolated_papergraph_dir):
        _make_paper(isolated_papergraph_dir, "local:abc", "P", year=2020)
        c = _make_client()
        resp = c.patch("/api/papers/local:abc", json={"year": None})
        assert resp.status_code == 200
        assert resp.json()["year"] is None

    def test_patch_combined(self, isolated_papergraph_dir):
        _make_paper(isolated_papergraph_dir, "local:abc", "Old",
                    authors=["X"], year=2020)
        c = _make_client()
        resp = c.patch("/api/papers/local:abc",
                       json={"title": "T2", "authors": ["Y"], "year": 2001})
        assert resp.status_code == 200
        body = resp.json()
        assert body["title"] == "T2"
        assert body["authors"] == ["Y"]
        assert body["year"] == 2001

    def test_patch_unknown_returns_404(self, isolated_papergraph_dir):
        c = _make_client()
        resp = c.patch("/api/papers/local:missing", json={"title": "X"})
        assert resp.status_code == 404

    def test_patch_year_out_of_range_returns_422(self, isolated_papergraph_dir):
        _make_paper(isolated_papergraph_dir, "local:abc", "P")
        c = _make_client()
        resp = c.patch("/api/papers/local:abc", json={"year": 1200})
        assert resp.status_code == 422

    def test_patch_reflected_in_get_papers(self, isolated_papergraph_dir):
        _make_paper(isolated_papergraph_dir, "local:abc", "Old", year=2020)
        c = _make_client()
        c.patch("/api/papers/local:abc", json={"title": "Fresh", "year": 2011})
        papers = c.get("/api/papers").json()
        row = next(p for p in papers if p["paper_id"] == "local:abc")
        assert row["title"] == "Fresh"
        assert row["year"] == 2011


# ---------------------------------------------------------------------------
# POST /api/ingest
# ---------------------------------------------------------------------------

class TestIngest:
    def test_bad_folder_returns_400(self, isolated_papergraph_dir):
        c = _make_client()
        resp = c.post("/api/ingest", json={"folder": "/no/such/folder/xyz"})
        assert resp.status_code == 400

    def test_empty_folder_accepted(self, isolated_papergraph_dir, tmp_path):
        folder = tmp_path / "pdfs"
        folder.mkdir()
        c = _make_client()
        resp = c.post("/api/ingest", json={"folder": str(folder)})
        assert resp.status_code == 202
        data = resp.json()
        assert "job_id" in data
        assert "discovered" in data
        assert data["discovered"] == 0

    def test_second_concurrent_ingest_returns_409(self, isolated_papergraph_dir, tmp_path):
        """Second POST /api/ingest while one is running -> 409."""
        folder = tmp_path / "pdfs"
        folder.mkdir()
        # Create a fake PDF
        (folder / "test.pdf").write_bytes(b"%PDF-1.4 fake")

        block_event = asyncio.Event()

        async def blocking_ingest(folder, *, bus, **kwargs):
            await block_event.wait()

        app = create_lab_app(Bus())
        app.state.ingest_override = blocking_ingest

        with TestClient(app) as c:
            # First POST — starts a background task (never completes in test)
            # We need to simulate an active job
            # Inject the running job directly (kind="ingest" so the guard fires)
            app.state.jobs = {"job-1": {"status": "running", "kind": "ingest"}}
            resp = c.post("/api/ingest", json={"folder": str(folder)})
            # Should get 409 because job-1 is running
            assert resp.status_code == 409

    def test_ingest_job_status(self, isolated_papergraph_dir, tmp_path):
        folder = tmp_path / "pdfs"
        folder.mkdir()

        async def fast_ingest(folder, *, bus, **kwargs):
            pass

        app = create_lab_app(Bus())
        app.state.ingest_override = fast_ingest

        with TestClient(app) as c:
            resp = c.post("/api/ingest", json={"folder": str(folder)})
            assert resp.status_code == 202
            job_id = resp.json()["job_id"]
            # Poll job
            job_resp = c.get(f"/api/jobs/{job_id}")
            assert job_resp.status_code == 200
            data = job_resp.json()
            assert data["status"] in ("running", "done", "failed")


# ---------------------------------------------------------------------------
# GET /api/jobs/{id}
# ---------------------------------------------------------------------------

class TestJobs:
    def test_unknown_job_returns_404(self, isolated_papergraph_dir):
        c = _make_client()
        resp = c.get("/api/jobs/job-9999")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/align
# ---------------------------------------------------------------------------

class TestAlign:
    def test_align_returns_payload(self, isolated_papergraph_dir):
        from research_companion import store
        draft_id = "arxiv:draft001"
        cand_id = "arxiv:cand001"
        _make_paper(isolated_papergraph_dir, draft_id, "Draft Paper")
        _make_paper(isolated_papergraph_dir, cand_id, "Candidate Paper")
        store.set_draft_paper_id(draft_id)
        store.save_sections(draft_id, {
            "sections": [{"section_id": "s1", "title": "Introduction", "level": 1,
                          "parent": None, "char_start": 0, "char_end": 50}]
        })
        c = _make_client(llm=_fake_llm)
        resp = c.post("/api/align", json={"paper_id": cand_id})
        assert resp.status_code == 200
        data = resp.json()
        assert "score" in data or "sections" in data

    def test_align_unknown_paper_returns_404(self, isolated_papergraph_dir):
        c = _make_client(llm=_fake_llm)
        resp = c.post("/api/align", json={"paper_id": "arxiv:unknownxyz"})
        assert resp.status_code == 404

    def test_align_no_draft_and_no_against_returns_400(self, isolated_papergraph_dir):
        _make_paper(isolated_papergraph_dir, "arxiv:cand001", "Candidate")
        c = _make_client(llm=_fake_llm)
        resp = c.post("/api/align", json={"paper_id": "arxiv:cand001"})
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# POST /api/ask
# ---------------------------------------------------------------------------

class TestAsk:
    def test_ask_returns_answer_shape(self, isolated_papergraph_dir):
        _make_paper(isolated_papergraph_dir, "arxiv:1111.22222", "My Paper")
        c = _make_client(llm=_fake_qa_llm)
        resp = c.post("/api/ask", json={"question": "What is this paper about?"})
        assert resp.status_code == 200
        data = resp.json()
        assert "answer" in data
        assert "citations" in data
        assert "unverified_quotes" in data
        assert "grounding" in data
        assert "paper_ids" in data["grounding"]

    def test_citations_have_correct_shape(self, isolated_papergraph_dir):
        _make_paper(isolated_papergraph_dir, "arxiv:1111.22222", "My Paper")
        c = _make_client(llm=_fake_qa_llm)
        resp = c.post("/api/ask", json={"question": "Tell me about methods."})
        assert resp.status_code == 200
        data = resp.json()
        for cit in data["citations"]:
            assert "n" in cit
            assert "paper_id" in cit
            assert "title" in cit
            assert "section_id" in cit
            assert "section_title" in cit
            assert "cited" in cit

    def test_citations_include_char_offsets(self, isolated_papergraph_dir):
        """Each /api/ask citation carries the absolute source offsets so the
        reader can highlight the exact span (Phase 3 Task B)."""
        from research_companion import store
        paper_id = "arxiv:1111.22222"
        _make_paper(isolated_papergraph_dir, paper_id, "My Paper")
        c = _make_client(llm=_fake_qa_llm)
        resp = c.post("/api/ask", json={"question": "What is this paper about?"})
        assert resp.status_code == 200
        citations = resp.json()["citations"]
        assert citations, "expected at least one citation for a seeded paper"
        for cit in citations:
            assert "char_start" in cit
            assert "char_end" in cit
            assert "chunk_index" in cit
            assert isinstance(cit["char_start"], int)
            assert isinstance(cit["char_end"], int)
            assert isinstance(cit["chunk_index"], int)
        # Cross-check the values equal the retrieved source offsets: the seeded
        # paper has no sections.json, so its whole text is one Full-Text chunk
        # at [0, len(text)).
        text = store.load_text(paper_id)
        first = citations[0]
        assert first["char_start"] == 0
        assert first["char_end"] == len(text)
        assert first["chunk_index"] == 0


# ---------------------------------------------------------------------------
# POST /api/compare
# ---------------------------------------------------------------------------

class TestCompare:
    def test_compare_happy(self, isolated_papergraph_dir):
        _make_paper(isolated_papergraph_dir, "arxiv:1111.22222", "Paper A")
        _make_paper(isolated_papergraph_dir, "arxiv:2222.33333", "Paper B")
        c = _make_client(llm=_fake_compare_llm)
        resp = c.post("/api/compare",
                      json={"paper_a": "arxiv:1111.22222", "paper_b": "arxiv:2222.33333"})
        assert resp.status_code == 200
        data = resp.json()
        assert "shared" in data
        assert "only_a" in data
        assert "only_b" in data

    def test_compare_same_id_returns_400(self, isolated_papergraph_dir):
        _make_paper(isolated_papergraph_dir, "arxiv:1111.22222", "Paper A")
        c = _make_client(llm=_fake_compare_llm)
        resp = c.post("/api/compare",
                      json={"paper_a": "arxiv:1111.22222", "paper_b": "arxiv:1111.22222"})
        assert resp.status_code == 400

    def test_compare_unknown_paper_returns_404(self, isolated_papergraph_dir):
        _make_paper(isolated_papergraph_dir, "arxiv:1111.22222", "Paper A")
        c = _make_client(llm=_fake_compare_llm)
        resp = c.post("/api/compare",
                      json={"paper_a": "arxiv:1111.22222", "paper_b": "arxiv:unknown_p"})
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/papers (add paper)
# ---------------------------------------------------------------------------

def _make_pipeline_spying_fakes(store_paper: bool = True):
    """Return injectable pipeline seams that record call counts.

    Returns (fake_meta, fake_add_paper_fn, stage_counts_dict, seam_overrides_dict)
    where stage_counts_dict maps stage name -> call count (checked by tests) and
    seam_overrides_dict is ready to be assigned to app.state.pipeline_overrides.

    If store_paper is True, fake_add_paper_fn also saves metadata and stub text
    to the store so that ingest_one's get_paper_text won't fail.
    """
    from research_companion import store as _store
    from research_companion.sections import Section
    from research_companion.store import PaperMetadata

    paper_id = "local:pipe_test_abc"

    fake_meta = PaperMetadata(
        paper_id=paper_id,
        title="Pipeline Test Paper",
        authors=["Test Author"],
        added_at="2024-01-01T00:00:00Z",
    )

    if store_paper:
        fake_meta.save()
        _store.save_text(paper_id, "This is the text. Introduction Methods Results. " * 6)

    counts: dict[str, int] = {
        "extractor": 0,
        "sectioner": 0,
        "aligner": 0,
        "strengther": 0,
    }

    def fake_sectioner(pid, **kwargs):
        counts["sectioner"] += 1
        return [
            Section(section_id="s1", title="Introduction", level=1,
                    parent=None, char_start=0, char_end=50),
        ]

    def fake_extractor(meta, *, provider="anthropic", model=None, force=False):
        counts["extractor"] += 1
        return (
            {
                "concepts": [{"name": "KG", "section": "s1"}],
                "methods": [],
                "datasets": [],
                "claims": [],
                "results": [],
                "related_work": [],
            },
            {"input_tokens": 1, "output_tokens": 1, "cached": False},
        )

    def fake_strengther(pid, **kwargs):
        counts["strengther"] += 1
        return {"score": 0.5, "band": "moderate", "color": "#aaa"}

    seam_overrides = {
        "extractor": fake_extractor,
        "sectioner": fake_sectioner,
        "aligner": None,   # skip alignment
        "strengther": fake_strengther,
    }

    return fake_meta, counts, seam_overrides


class TestAddPaper:
    def test_invalid_target_returns_400(self, isolated_papergraph_dir):
        c = _make_client()
        resp = c.post("/api/papers", json={"target": ""})
        assert resp.status_code == 400

    def test_missing_target_returns_400(self, isolated_papergraph_dir):
        c = _make_client()
        resp = c.post("/api/papers", json={})
        assert resp.status_code == 400

    def test_valid_target_returns_202(self, isolated_papergraph_dir, tmp_path):
        fake_pdf = tmp_path / "test.pdf"
        fake_pdf.write_bytes(
            b"%PDF-1.4\n"
            b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
            b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
            b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n"
            b"trailer<</Size 4/Root 1 0 R>>\n"
            b"startxref\n0\n%%EOF\n"
        )

        async def fake_add_paper_task(target, bus):
            pass

        app = create_lab_app(Bus())
        app.state.add_paper_override = fake_add_paper_task

        with TestClient(app) as c:
            resp = c.post("/api/papers", json={"target": str(fake_pdf)})
            assert resp.status_code == 202
            assert "job_id" in resp.json()

    def test_pipeline_stages_run_via_seams(self, isolated_papergraph_dir, tmp_path):
        """When add_paper_override is NOT set, pipeline_overrides stage fakes are invoked."""
        from unittest.mock import patch


        fake_meta, counts, seam_overrides = _make_pipeline_spying_fakes(store_paper=True)

        # Patch fetch.add_paper to return our controlled meta
        def fake_add_paper(target):
            return fake_meta

        bus = Bus()
        app = create_lab_app(bus)
        app.state.pipeline_overrides = seam_overrides

        with patch("research_companion.fetch.add_paper", fake_add_paper), TestClient(app) as c:
            resp = c.post("/api/papers", json={"target": "local:pipe_test_abc"})
            assert resp.status_code == 202
            job_id = resp.json()["job_id"]

            # Poll until job completes (TestClient runs background tasks)
            import time
            for _ in range(50):
                job = c.get(f"/api/jobs/{job_id}").json()
                if job["status"] != "running":
                    break
                time.sleep(0.05)

            assert job["status"] == "done", f"job failed: {job}"

        # Verify pipeline seams were invoked
        assert counts["sectioner"] >= 1, "sectioner stage was not called"
        assert counts["extractor"] >= 1, "extractor stage was not called"
        assert counts["strengther"] >= 1, "strengther stage was not called"

        # Verify PaperAdded and SectionTreeBuilt events were published
        kinds = [type(e).__name__ for e in bus.history]
        assert "PaperAdded" in kinds
        assert "SectionTreeBuilt" in kinds
        assert "GraphDelta" in kinds
        assert "StrengthUpdated" in kinds
        assert "JobDone" in kinds

    def test_add_ingest_jobs_do_not_block_each_other(self, isolated_papergraph_dir, tmp_path):
        """Concurrent add/retry jobs must NOT trigger the 409 guard (only ingest jobs do)."""
        folder = tmp_path / "pdfs"
        folder.mkdir()
        (folder / "test.pdf").write_bytes(b"%PDF-1.4 fake")

        app = create_lab_app(Bus())
        # Inject a running add job (not an ingest job)
        app.state.jobs = {"job-1": {"status": "running", "kind": "add"}}

        async def fast_ingest(folder, *, bus, **kwargs):
            pass

        app.state.ingest_override = fast_ingest

        with TestClient(app) as c:
            resp = c.post("/api/ingest", json={"folder": str(folder)})
            # add jobs must NOT block ingest
            assert resp.status_code == 202


# ---------------------------------------------------------------------------
# POST /api/papers/{id}/retry
# ---------------------------------------------------------------------------

class TestRetryPaper:
    def test_retry_unknown_returns_404(self, isolated_papergraph_dir):
        c = _make_client()
        resp = c.post("/api/papers/arxiv:unknown_zz/retry")
        assert resp.status_code == 404

    def test_retry_known_failure_returns_202(self, isolated_papergraph_dir):
        from research_companion import store
        store.record_failure("some/path.pdf", {"stage": "extract", "error": "boom",
                                               "paper_id": "arxiv:1111.22222"})

        async def fast_retry(path, paper_id, bus):
            pass

        app = create_lab_app(Bus())
        app.state.retry_override = fast_retry

        with TestClient(app) as c:
            resp = c.post("/api/papers/arxiv:1111.22222/retry")
            assert resp.status_code == 202
            assert "job_id" in resp.json()

    def test_retry_add_failure_preserves_failure_entry(self, isolated_papergraph_dir):
        """When the add step in retry raises, the failure entry is NOT cleared."""
        from unittest.mock import patch

        from research_companion import store

        path_key = "local:fail_paper"
        store.record_failure(path_key, {"stage": "extract", "error": "old error",
                                        "paper_id": path_key})

        def raising_add_local_pdf(path):
            raise RuntimeError("add failed in retry")

        bus = Bus()
        app = create_lab_app(bus)

        with patch("research_companion.fetch.add_local_pdf", raising_add_local_pdf), TestClient(app) as c:
            resp = c.post(f"/api/papers/{path_key}/retry")
            assert resp.status_code == 202
            job_id = resp.json()["job_id"]

            import time
            job = None
            for _ in range(100):
                job = c.get(f"/api/jobs/{job_id}").json()
                if job["status"] != "running":
                    break
                time.sleep(0.05)
            assert job["status"] == "failed", f"expected failed, got: {job}"

        # Failure entry must still be present (not silently cleared)
        failures = store.list_failures()
        assert path_key in failures, "failure entry was incorrectly cleared after retry failure"

    def test_retry_pipeline_stages_run_on_success(self, isolated_papergraph_dir):
        """When retry succeeds, pipeline stage seams are invoked and failure is cleared."""
        from unittest.mock import patch

        from research_companion import store

        path_key = "some/paper.pdf"
        paper_id_val = "local:retry_success_test"
        store.record_failure(path_key, {"stage": "extract", "error": "old error",
                                        "paper_id": paper_id_val})

        fake_meta, counts, seam_overrides = _make_pipeline_spying_fakes(store_paper=True)
        # Override the paper_id to match
        from research_companion import store as _store
        from research_companion.store import PaperMetadata
        real_meta = PaperMetadata(
            paper_id=paper_id_val,
            title="Retry Success Paper",
            authors=["Auth"],
            added_at="2024-01-01T00:00:00Z",
        )
        real_meta.save()
        _store.save_text(paper_id_val, "Introduction Methods Results. " * 10)

        def fake_add_local_pdf(path):
            return real_meta

        bus = Bus()
        app = create_lab_app(bus)
        app.state.pipeline_overrides = seam_overrides

        with patch("research_companion.fetch.add_local_pdf", fake_add_local_pdf), TestClient(app) as c:
            resp = c.post(f"/api/papers/{paper_id_val}/retry")
            assert resp.status_code == 202
            job_id = resp.json()["job_id"]

            import time
            for _ in range(50):
                job = c.get(f"/api/jobs/{job_id}").json()
                if job["status"] != "running":
                    break
                time.sleep(0.05)

            assert job["status"] == "done", f"expected done, got: {job}"

        # Pipeline stages must have run
        assert counts["sectioner"] >= 1, "sectioner stage was not called"
        assert counts["extractor"] >= 1, "extractor stage was not called"
        assert counts["strengther"] >= 1, "strengther stage was not called"

        # Failure entry must be cleared on success
        failures = store.list_failures()
        assert path_key not in failures, "failure entry was not cleared after successful retry"


# ---------------------------------------------------------------------------
# GET /api/events (SSE)
# ---------------------------------------------------------------------------

class TestSSE:
    """Tests for the SSE endpoint.

    Uses TestClient with app.state._sse_done = True so the generator terminates
    after replaying history — mirrors the test_dashboard.py done-state pattern.
    """

    def _make_sse_client(self, bus: Bus, pre_events=None):
        """Create a TestClient whose SSE endpoint terminates after history replay."""
        if pre_events:
            for event in pre_events:
                asyncio.run(bus.publish(event))
        app = create_lab_app(bus)
        app.state._sse_done = True  # terminate after history replay (test mode)
        return TestClient(app), app

    def test_events_replay_pre_connect_events_with_original_seq(
        self, isolated_papergraph_dir
    ):
        """Pre-connect events are replayed with their original seq numbers."""
        bus = Bus()
        c, app = self._make_sse_client(bus, [
            PaperAdded(paper_id="pre1", title="Pre-connect"),
            GraphDelta(paper_id="pre1"),
        ])

        # Stream terminates after replaying 2 pre-connect events
        with c.stream("GET", "/api/events") as resp:
            body = "".join(resp.iter_text())

        assert "seq" in body
        assert "paper_added" in body
        # Replayed events get seq 1, 2
        data = [line for line in body.split("\n") if line.startswith("data:")]
        assert len(data) >= 2
        evt1 = json.loads(data[0][len("data: "):])
        assert evt1["seq"] == 1

    def test_events_stream_seq_increments(self, isolated_papergraph_dir):
        """Events get monotonically increasing seq values."""
        bus = Bus()
        c, app = self._make_sse_client(bus, [
            PaperAdded(paper_id="p1", title="T1"),
            JobDone(job="test"),
        ])

        with c.stream("GET", "/api/events") as resp:
            body = "".join(resp.iter_text())

        data_lines = [line for line in body.split("\n") if line.startswith("data:")]
        assert len(data_lines) >= 2
        events = [json.loads(line[len("data: "):].strip()) for line in data_lines]
        seqs = [e["seq"] for e in events]
        assert all(isinstance(s, int) and s > 0 for s in seqs)
        assert seqs == sorted(seqs)

    def test_events_endpoint_reachable(self, isolated_papergraph_dir):
        """SSE endpoint responds with 200 and event-stream content type."""
        bus = Bus()
        c, app = self._make_sse_client(bus, [JobDone(job="test")])

        with c.stream("GET", "/api/events") as resp:
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers.get("content-type", "")
            body = "".join(resp.iter_text())

        assert "job_done" in body

    def test_seq_recorder_concurrent_consumers_see_identical_seqs(
        self, isolated_papergraph_dir
    ):
        """Two independent SSE reads over the same pre-published events see identical
        seq numbers for the same event.  This verifies that seq is assigned once (in
        _SeqRecorder) and not computed independently per-generator.
        """

        bus = Bus()
        events = [
            PaperAdded(paper_id="p1", title="T1"),
            GraphDelta(paper_id="p1"),
            JobDone(job="test"),
        ]
        for ev in events:
            asyncio.run(bus.publish(ev))

        # Both clients replay the same pre-connect snapshot
        app1 = create_lab_app(bus)
        app1.state._sse_done = True
        app2 = create_lab_app(bus)
        app2.state._sse_done = True

        def _read_seqs(app):
            with TestClient(app) as c, c.stream("GET", "/api/events") as resp:
                body = "".join(resp.iter_text())
            data_lines = [line for line in body.split("\n") if line.startswith("data:")]
            return [json.loads(line[len("data: "):].strip())["seq"] for line in data_lines]

        seqs1 = _read_seqs(app1)
        seqs2 = _read_seqs(app2)

        # Both streams must contain the same number of events
        assert len(seqs1) == len(seqs2), (
            f"stream 1 has {len(seqs1)} events, stream 2 has {len(seqs2)}"
        )
        # Each seq must match — same event, same seq number
        for i, (s1, s2) in enumerate(zip(seqs1, seqs2, strict=False)):
            assert s1 == s2, (
                f"event {i}: stream 1 seq={s1}, stream 2 seq={s2} — "
                "seq numbers diverged between concurrent clients"
            )

    def test_seq_recorder_assigns_seq_monotonically(self, isolated_papergraph_dir):
        """_SeqRecorder assigns strictly increasing seq values to consecutive events."""
        from research_companion.lab_api import _SeqRecorder

        bus = Bus()
        recorder = _SeqRecorder(bus)
        events_to_publish = [
            PaperAdded(paper_id="r1", title="T1"),
            GraphDelta(paper_id="r1"),
            JobDone(job="seq-test"),
        ]
        for ev in events_to_publish:
            asyncio.run(bus.publish(ev))
            # Simulate drain manually (no running event loop)
            recorder._assign(ev)

        records = recorder.snapshot()
        # Pre-history events may already be there; check the new ones are monotone
        seqs = [s for s, _ in records]
        assert seqs == sorted(seqs)
        assert len(seqs) == len(set(seqs)), "seq values must be unique"


# ---------------------------------------------------------------------------
# Module import without fastapi (basic lazy-import check)
# ---------------------------------------------------------------------------

class TestModuleImport:
    def test_lab_api_module_can_be_imported(self):
        """lab_api module imports without errors (fastapi is available in test env)."""
        import research_companion.lab_api as la
        assert hasattr(la, "create_lab_app")
        assert hasattr(la, "serve_lab")

    def test_serve_lab_open_browser_wiring(self, isolated_papergraph_dir, monkeypatch):
        """serve_lab(open_browser=True) must reach uvicorn.run without crashing —
        router.on_startup is a list, not a decorator (regression)."""
        import uvicorn

        import research_companion.lab_api as la

        ran = {}
        monkeypatch.setattr(uvicorn, "run", lambda app, **kw: ran.update(app=app, **kw))
        la.serve_lab(port=9999, open_browser=True)
        assert ran["port"] == 9999
        assert len(ran["app"].router.on_startup) >= 1


# ---------------------------------------------------------------------------
# GET /api/settings  +  PUT /api/settings
# ---------------------------------------------------------------------------

class TestSettingsEndpoints:
    """Tests for GET/PUT /api/settings — masked keys, validation, security."""

    def _clean_env(self, monkeypatch):
        """Remove all secret env vars and provider/model vars."""
        from research_companion.settings import SECRET_KEYS
        for env_var in SECRET_KEYS.values():
            monkeypatch.delenv(env_var, raising=False)
        for ev in ("RESEARCH_COMPANION_PROVIDER", "RESEARCH_COMPANION_MODEL"):
            monkeypatch.delenv(ev, raising=False)

    def test_get_settings_shape(self, isolated_papergraph_dir, monkeypatch):
        """GET /api/settings returns the expected shape with keys block."""
        self._clean_env(monkeypatch)
        c = _make_client()
        resp = c.get("/api/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert "provider" in data
        assert "theme" in data
        assert "keys" in data
        for name in ("anthropic_api_key", "openai_api_key", "hf_token"):
            assert name in data["keys"]
            assert "set" in data["keys"][name]
            assert "masked" in data["keys"][name]

    def test_get_settings_defaults(self, isolated_papergraph_dir, monkeypatch):
        """GET /api/settings returns DEFAULTS when no config saved."""
        self._clean_env(monkeypatch)
        c = _make_client()
        resp = c.get("/api/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert data["provider"] == "anthropic"
        assert data["theme"] == "dark"
        assert data["k_sections"] == 6
        assert data["char_budget"] == 8000

    def test_get_settings_keys_unset_when_no_env(self, isolated_papergraph_dir, monkeypatch):
        """Keys show set:false and masked:null when env vars are absent."""
        self._clean_env(monkeypatch)
        c = _make_client()
        resp = c.get("/api/settings")
        data = resp.json()
        for name in ("anthropic_api_key", "openai_api_key", "hf_token"):
            assert data["keys"][name]["set"] is False
            assert data["keys"][name]["masked"] is None

    def test_put_settings_updates_theme(self, isolated_papergraph_dir, monkeypatch):
        """PUT /api/settings with theme updates returns updated settings."""
        self._clean_env(monkeypatch)
        c = _make_client()
        resp = c.put("/api/settings", json={"theme": "light"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["theme"] == "light"

    def test_put_settings_partial_success(self, isolated_papergraph_dir, monkeypatch):
        """PUT /api/settings with multiple valid fields updates all."""
        self._clean_env(monkeypatch)
        c = _make_client()
        resp = c.put("/api/settings", json={"theme": "light", "k_sections": 10})
        assert resp.status_code == 200
        data = resp.json()
        assert data["theme"] == "light"
        assert data["k_sections"] == 10

    def test_put_settings_bad_provider_returns_400(self, isolated_papergraph_dir, monkeypatch):
        """PUT /api/settings with invalid provider returns 400."""
        self._clean_env(monkeypatch)
        c = _make_client()
        resp = c.put("/api/settings", json={"provider": "mistral"})
        assert resp.status_code == 400
        assert "provider" in resp.json()["detail"].lower()

    def test_put_settings_bad_theme_returns_400(self, isolated_papergraph_dir, monkeypatch):
        """PUT /api/settings with invalid theme returns 400."""
        self._clean_env(monkeypatch)
        c = _make_client()
        resp = c.put("/api/settings", json={"theme": "pink"})
        assert resp.status_code == 400

    def test_put_settings_key_then_get_shows_set_true_and_masked(
        self, isolated_papergraph_dir, monkeypatch, tmp_path
    ):
        """PUT key -> GET shows set:true + masked value; raw value never in response."""
        self._clean_env(monkeypatch)
        # Temporarily point env_file_path to tmp_path for this test via env override
        c = _make_client()
        raw_key = "sk-ant-api-test-12345678abcd"
        resp = c.put("/api/settings", json={"keys": {"anthropic_api_key": raw_key}})
        assert resp.status_code == 200
        data = resp.json()
        key_info = data["keys"]["anthropic_api_key"]
        assert key_info["set"] is True
        assert key_info["masked"] is not None
        # The raw value must NOT appear anywhere in the response body
        assert raw_key not in resp.text

    def test_put_settings_key_masked_shows_last_4(
        self, isolated_papergraph_dir, monkeypatch
    ):
        """Masked key ends with last 4 chars of the value."""
        self._clean_env(monkeypatch)
        c = _make_client()
        raw_key = "sk-ant-api-test-12345678abcd"
        resp = c.put("/api/settings", json={"keys": {"anthropic_api_key": raw_key}})
        data = resp.json()
        masked = data["keys"]["anthropic_api_key"]["masked"]
        assert masked.endswith("abcd")
        assert masked.startswith("****")

    def test_put_settings_empty_key_returns_400(self, isolated_papergraph_dir, monkeypatch):
        """PUT with empty string key value returns 400 (must send null to delete)."""
        self._clean_env(monkeypatch)
        c = _make_client()
        resp = c.put("/api/settings", json={"keys": {"anthropic_api_key": ""}})
        assert resp.status_code == 400

    def test_put_settings_key_null_deletes(self, isolated_papergraph_dir, monkeypatch):
        """PUT keys.name=null removes the key from env and returns set:false."""
        self._clean_env(monkeypatch)
        # First set a key
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-12345678")
        c = _make_client()
        resp = c.put("/api/settings", json={"keys": {"anthropic_api_key": None}})
        assert resp.status_code == 200
        data = resp.json()
        assert data["keys"]["anthropic_api_key"]["set"] is False

    def test_raw_secret_never_echoed_in_response(self, isolated_papergraph_dir, monkeypatch):
        """The raw secret value is never present anywhere in GET or PUT responses."""
        self._clean_env(monkeypatch)
        raw = "super-secret-api-key-99999"
        monkeypatch.setenv("ANTHROPIC_API_KEY", raw)
        c = _make_client()

        get_resp = c.get("/api/settings")
        assert raw not in get_resp.text

        put_resp = c.put("/api/settings", json={"theme": "light"})
        assert raw not in put_resp.text


# ---------------------------------------------------------------------------
# W3-T6: GET /api/suggestions
# ---------------------------------------------------------------------------

class TestGetSuggestions:
    def test_no_draft_returns_empty(self, isolated_papergraph_dir):
        c = _make_client()
        resp = c.get("/api/suggestions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["suggestions"] == []

    def test_draft_with_no_saved_suggestions_returns_empty(self, isolated_papergraph_dir):
        from research_companion import store
        _make_paper(isolated_papergraph_dir, "local:draft0001", "Draft Paper")
        store.set_draft_paper_id("local:draft0001")
        c = _make_client()
        resp = c.get("/api/suggestions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["suggestions"] == []

    def test_returns_saved_suggestions(self, isolated_papergraph_dir):
        from research_companion import store
        from research_companion.suggestions import generate_suggestions
        _make_paper(isolated_papergraph_dir, "local:draft0001", "Draft Paper")
        store.set_draft_paper_id("local:draft0001")
        report = {
            "paper_id": "local:draft0001",
            "title": "Draft Paper",
            "lanes": {
                "citation": {
                    "ok": True,
                    "error": "",
                    "data": {
                        "counts": {"verified": 0, "unverified": 1, "suspect": 0},
                        "references": [{"title": "A Ref", "status": "unverified"}],
                    },
                }
            },
            "generated_by": "research-companion",
        }
        generate_suggestions(draft_id="local:draft0001", report=report, alignments=[])
        c = _make_client()
        resp = c.get("/api/suggestions")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["suggestions"]) >= 1

    def test_status_filter_open(self, isolated_papergraph_dir):
        from research_companion import store
        from research_companion.suggestions import (
            dismiss_suggestion,
            generate_suggestions,
        )
        _make_paper(isolated_papergraph_dir, "local:draft0001", "Draft Paper")
        store.set_draft_paper_id("local:draft0001")
        report = {
            "paper_id": "local:draft0001",
            "title": "Draft Paper",
            "lanes": {
                "citation": {
                    "ok": True,
                    "error": "",
                    "data": {
                        "counts": {"verified": 0, "unverified": 2, "suspect": 0},
                        "references": [
                            {"title": "Ref A", "status": "unverified"},
                            {"title": "Ref B", "status": "unverified"},
                        ],
                    },
                }
            },
            "generated_by": "research-companion",
        }
        result = generate_suggestions(draft_id="local:draft0001", report=report, alignments=[])
        # Dismiss one
        sug_id = result["suggestions"][0]["id"]
        dismiss_suggestion(sug_id)
        c = _make_client()
        resp = c.get("/api/suggestions?status=open")
        assert resp.status_code == 200
        data = resp.json()
        assert all(s["status"] == "open" for s in data["suggestions"])
        # Dismissed one should not be included
        assert all(s["id"] != sug_id for s in data["suggestions"])

    def test_counts_present_in_response(self, isolated_papergraph_dir):
        """GET /api/suggestions always includes counts with open/addressed/dismissed keys."""
        from research_companion import store
        from research_companion.suggestions import generate_suggestions
        _make_paper(isolated_papergraph_dir, "local:draft0001", "Draft Paper")
        store.set_draft_paper_id("local:draft0001")
        report = {
            "paper_id": "local:draft0001",
            "title": "Draft Paper",
            "lanes": {
                "citation": {
                    "ok": True,
                    "error": "",
                    "data": {
                        "counts": {"verified": 0, "unverified": 1, "suspect": 0},
                        "references": [{"title": "Count Ref", "status": "unverified"}],
                    },
                }
            },
            "generated_by": "research-companion",
        }
        generate_suggestions(draft_id="local:draft0001", report=report, alignments=[])
        c = _make_client()
        resp = c.get("/api/suggestions")
        assert resp.status_code == 200
        data = resp.json()
        assert "counts" in data, f"missing 'counts' in response: {list(data.keys())}"
        counts = data["counts"]
        assert "open" in counts
        assert "addressed" in counts
        assert "dismissed" in counts

    def test_counts_reflect_all_suggestions_even_with_filter(self, isolated_papergraph_dir):
        """counts must reflect ALL suggestions regardless of ?status filter."""
        from research_companion import store
        from research_companion.suggestions import dismiss_suggestion, generate_suggestions
        _make_paper(isolated_papergraph_dir, "local:draft0001", "Draft Paper")
        store.set_draft_paper_id("local:draft0001")
        report = {
            "paper_id": "local:draft0001",
            "title": "Draft Paper",
            "lanes": {
                "citation": {
                    "ok": True,
                    "error": "",
                    "data": {
                        "counts": {"verified": 0, "unverified": 2, "suspect": 0},
                        "references": [
                            {"title": "CA Ref", "status": "unverified"},
                            {"title": "CB Ref", "status": "unverified"},
                        ],
                    },
                }
            },
            "generated_by": "research-companion",
        }
        result = generate_suggestions(draft_id="local:draft0001", report=report, alignments=[])
        sug_id = result["suggestions"][0]["id"]
        dismiss_suggestion(sug_id)
        c = _make_client()
        resp = c.get("/api/suggestions?status=open")
        assert resp.status_code == 200
        data = resp.json()
        assert "counts" in data
        counts = data["counts"]
        # Even though we're filtering for open only, counts must reflect total
        assert counts["dismissed"] == 1, f"expected dismissed=1, got {counts}"
        assert counts["open"] == 1, f"expected open=1, got {counts}"

    def test_counts_present_when_no_draft(self, isolated_papergraph_dir):
        """counts must be present even when no draft is configured."""
        c = _make_client()
        resp = c.get("/api/suggestions")
        assert resp.status_code == 200
        data = resp.json()
        assert "counts" in data


# ---------------------------------------------------------------------------
# W3-T6: POST /api/suggestions/regenerate
# ---------------------------------------------------------------------------

class TestRegenerateSuggestions:
    def _report(self, paper_id: str = "local:draft0001") -> dict:
        return {
            "paper_id": paper_id,
            "title": "Draft Paper",
            "lanes": {
                "citation": {
                    "ok": True,
                    "error": "",
                    "data": {
                        "counts": {"verified": 0, "unverified": 1, "suspect": 0},
                        "references": [{"title": "New Ref", "status": "unverified"}],
                    },
                }
            },
            "generated_by": "research-companion",
        }

    def test_no_draft_returns_400(self, isolated_papergraph_dir):
        c = _make_client()
        resp = c.post("/api/suggestions/regenerate", json={})
        assert resp.status_code == 400

    def test_no_saved_report_succeeds_with_empty_suggestions(self, isolated_papergraph_dir):
        """No review report is NOT an error: alignment/gap rules may still apply;
        with no artifacts at all the result is an honest empty payload."""
        from research_companion import store
        _make_paper(isolated_papergraph_dir, "local:draft0001", "Draft Paper")
        store.set_draft_paper_id("local:draft0001")
        c = _make_client()
        resp = c.post("/api/suggestions/regenerate", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["counts"] == {"open": 0, "addressed": 0, "dismissed": 0}
        assert data["suggestions"] == []

    def test_regenerate_with_report_returns_suggestions(self, isolated_papergraph_dir):
        from research_companion import store
        _make_paper(isolated_papergraph_dir, "local:draft0001", "Draft Paper")
        store.set_draft_paper_id("local:draft0001")
        store.save_review_report("local:draft0001", self._report())
        c = _make_client()
        resp = c.post("/api/suggestions/regenerate", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert "suggestions" in data
        assert len(data["suggestions"]) >= 1

    def test_regenerate_include_llm_false_no_structure(self, isolated_papergraph_dir):
        """include_llm=False (default) — no structure suggestions even with LLM wired."""
        from research_companion import store
        _make_paper(isolated_papergraph_dir, "local:draft0001", "Draft Paper")
        store.set_draft_paper_id("local:draft0001")
        store.save_review_report("local:draft0001", self._report())
        c = _make_client()
        resp = c.post("/api/suggestions/regenerate", json={"include_llm": False})
        assert resp.status_code == 200
        data = resp.json()
        assert all(s["kind"] != "structure" for s in data["suggestions"])

    def test_regenerate_publishes_suggestions_updated_event(self, isolated_papergraph_dir):
        """POST /api/suggestions/regenerate must publish SuggestionsUpdated to the bus."""
        from research_companion import store
        _make_paper(isolated_papergraph_dir, "local:draft0001", "Draft Paper")
        store.set_draft_paper_id("local:draft0001")
        store.save_review_report("local:draft0001", self._report())

        bus = Bus()
        app = create_lab_app(bus)
        with TestClient(app) as c:
            resp = c.post("/api/suggestions/regenerate", json={})
        assert resp.status_code == 200

        event_kinds = [type(e).__name__ for e in bus.history]
        assert "SuggestionsUpdated" in event_kinds, (
            f"SuggestionsUpdated not published. Events: {event_kinds}"
        )

    def test_regenerate_include_llm_true_with_none_llm_calls_resolve_llm(
        self, isolated_papergraph_dir, monkeypatch
    ):
        """When include_llm=True and app.state.llm is None, _resolve_llm is attempted."""
        from research_companion import store

        _make_paper(isolated_papergraph_dir, "local:draft0001", "Draft Paper")
        store.set_draft_paper_id("local:draft0001")
        store.save_review_report("local:draft0001", self._report())

        resolve_called = [False]

        def fake_resolve_llm(*, json_mode=True):
            resolve_called[0] = True
            # Return a simple fake LLM
            def fake_llm(prompt: str) -> str:
                import json as _json
                return _json.dumps({"suggestions": []})
            return fake_llm

        import research_companion.lab_api as _la
        monkeypatch.setattr(_la, "_resolve_llm", fake_resolve_llm)

        # Build app with llm=None
        bus = Bus()
        app = create_lab_app(bus, llm=None)
        with TestClient(app) as c:
            resp = c.post("/api/suggestions/regenerate", json={"include_llm": True})
        assert resp.status_code == 200
        assert resolve_called[0], "_resolve_llm was not called when include_llm=True and llm=None"


# ---------------------------------------------------------------------------
# W3-T6: POST /api/suggestions/{id}/dismiss
# ---------------------------------------------------------------------------

class TestDismissSuggestion:
    def test_dismiss_returns_dismissed_suggestion(self, isolated_papergraph_dir):
        from research_companion import store
        from research_companion.suggestions import generate_suggestions
        _make_paper(isolated_papergraph_dir, "local:draft0001", "Draft Paper")
        store.set_draft_paper_id("local:draft0001")
        report = {
            "paper_id": "local:draft0001",
            "title": "Draft Paper",
            "lanes": {
                "citation": {
                    "ok": True,
                    "error": "",
                    "data": {
                        "counts": {"verified": 0, "unverified": 1, "suspect": 0},
                        "references": [{"title": "Dismiss Me", "status": "unverified"}],
                    },
                }
            },
            "generated_by": "research-companion",
        }
        result = generate_suggestions(draft_id="local:draft0001", report=report, alignments=[])
        sug_id = result["suggestions"][0]["id"]
        c = _make_client()
        resp = c.post(f"/api/suggestions/{sug_id}/dismiss")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == sug_id
        assert data["status"] == "dismissed"

    def test_dismiss_unknown_id_returns_404(self, isolated_papergraph_dir):
        c = _make_client()
        resp = c.post("/api/suggestions/sug_nonexistent0000/dismiss")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# W3-T6: POST /api/align hook publishes SuggestionsUpdated
# ---------------------------------------------------------------------------

class TestAlignSuggestionsHook:
    def _make_sections(self, paper_id: str, isolated_papergraph_dir) -> None:
        from research_companion import store
        sections_payload = {
            "paper_id": paper_id,
            "text_sha256": "abc123",
            "sections": [
                {"section_id": "s1", "title": "Introduction", "index": 0, "level": 1,
                 "text": "Introduction text."},
            ],
        }
        store.save_sections(paper_id, sections_payload)

    def test_align_hook_publishes_suggestions_updated_event(self, isolated_papergraph_dir):
        from research_companion import store
        from research_companion.suggestions import generate_suggestions

        draft_id = "local:draft0001"
        cand_id = "local:cand0001"
        _make_paper(isolated_papergraph_dir, draft_id, "Draft Paper")
        _make_paper(isolated_papergraph_dir, cand_id, "Candidate Paper")
        store.set_draft_paper_id(draft_id)
        self._make_sections(draft_id, isolated_papergraph_dir)
        self._make_sections(cand_id, isolated_papergraph_dir)

        # Pre-generate some suggestions so hook has something to count
        report = {
            "paper_id": draft_id,
            "title": "Draft Paper",
            "lanes": {
                "citation": {
                    "ok": True,
                    "error": "",
                    "data": {
                        "counts": {"verified": 0, "unverified": 1, "suspect": 0},
                        "references": [{"title": "Pre-align Ref", "status": "unverified"}],
                    },
                }
            },
            "generated_by": "research-companion",
        }
        store.save_review_report(draft_id, report)
        generate_suggestions(draft_id=draft_id, report=report, alignments=[])

        # Build + save a fake alignment so POST /api/align can read it (force=False
        # returns cached; we inject a fake LLM that returns valid JSON).
        fake_align_result = {
            "version": 1,
            "draft_paper_id": draft_id,
            "candidate_paper_id": cand_id,
            "prompt_sha256": "fake123",
            "computed_at": "2026-07-06T00:00:00Z",
            "score": 0.6,
            "band": 0.1,
            "verdict": "medium",
            "signals": {"quote_verification": 0.5, "llm_relevance": 0.6, "lexical_overlap": 0.4},
            "sections": [
                {"section_id": "s1", "section_title": "Introduction",
                 "relation": "strengthens", "relevance": 0.8,
                 "rationale": "Relevant.", "evidence": []}
            ],
        }
        store.save_alignment(cand_id, fake_align_result)

        def _fake_align_llm(prompt: str) -> str:
            return json.dumps({
                "sections": [
                    {"section_id": "s1", "relation": "strengthens",
                     "relevance": 0.8, "rationale": "Good.", "evidence": []}
                ]
            })

        bus = Bus()
        c = _make_client(bus=bus, llm=_fake_align_llm)
        resp = c.post("/api/align", json={"paper_id": cand_id, "against": draft_id})
        assert resp.status_code == 200

        # Give the background hook a moment to publish (align is sync in TestClient,
        # but the hook is wrapped in try/except — we check the bus history for the event)
        import time
        time.sleep(0.1)

        event_kinds = []
        loop = asyncio.new_event_loop()
        try:
            snapshot = list(bus.history)
            event_kinds = [type(e).__name__ for e in snapshot]
        finally:
            loop.close()

        assert "SuggestionsUpdated" in event_kinds, (
            f"SuggestionsUpdated not published. Events: {event_kinds}"
        )


# ---------------------------------------------------------------------------
# W3-T7: serialize_graph — get_graph output unchanged
# ---------------------------------------------------------------------------

class TestSerializeGraphViaGetGraph:
    """serialize_graph is exercised indirectly via GET /api/graph; existing
    TestGraph tests gate correctness.  These tests confirm shape keys are
    stable after the refactor."""

    def test_graph_keys_present_after_refactor(self, isolated_papergraph_dir):
        from research_companion import graph as _g
        _make_paper(isolated_papergraph_dir, "arxiv:sg001", "SG Paper")
        G = _g.build_graph()
        _g.save_graph(G)
        c = _make_client()
        resp = c.get("/api/graph")
        assert resp.status_code == 200
        data = resp.json()
        assert "seq" in data
        assert "nodes" in data
        assert "edges" in data

    def test_node_keys_stable(self, isolated_papergraph_dir):
        from research_companion import graph as _g
        _make_paper(isolated_papergraph_dir, "arxiv:sg001", "SG Paper")
        G = _g.build_graph()
        _g.save_graph(G)
        c = _make_client()
        data = c.get("/api/graph").json()
        for node in data["nodes"]:
            assert "id" in node
            assert "kind" in node
            assert "label" in node
            assert "sections" in node
            assert "strength" in node
            assert "attrs" in node

    def test_edge_keys_stable(self, isolated_papergraph_dir):
        from research_companion import graph as _g
        _make_paper(isolated_papergraph_dir, "arxiv:sg001", "SG Paper A")
        _make_paper(isolated_papergraph_dir, "arxiv:sg002", "SG Paper B")
        G = _g.build_graph()
        _g.save_graph(G)
        c = _make_client()
        data = c.get("/api/graph").json()
        for edge in data["edges"]:
            assert "from" in edge
            assert "to" in edge
            assert "relation" in edge
            assert "weight" in edge


# ---------------------------------------------------------------------------
# W3-T7: GET /api/views — CRUD happy paths
# ---------------------------------------------------------------------------

class TestViewsCRUD:
    def _create_view(self, c, name="My View", node_ids=None) -> dict:
        body = {
            "name": name,
            "source": {"type": "ask", "query": "test"},
            "node_ids": node_ids or ["n1", "n2"],
            "pinned": False,
        }
        resp = c.post("/api/views", json=body)
        assert resp.status_code == 201
        return resp.json()

    def test_list_views_empty(self, isolated_papergraph_dir):
        c = _make_client()
        resp = c.get("/api/views")
        assert resp.status_code == 200
        assert resp.json() == {"views": []}

    def test_create_view_happy(self, isolated_papergraph_dir):
        c = _make_client()
        view = self._create_view(c)
        assert "view_id" in view
        assert view["name"] == "My View"
        assert view["pinned"] is False
        assert "node_ids" in view
        assert "source" in view

    def test_list_views_after_create(self, isolated_papergraph_dir):
        c = _make_client()
        self._create_view(c, name="View A")
        self._create_view(c, name="View B")
        resp = c.get("/api/views")
        assert resp.status_code == 200
        views = resp.json()["views"]
        assert len(views) == 2

    def test_create_view_bad_source_type_returns_400(self, isolated_papergraph_dir):
        c = _make_client()
        body = {
            "name": "Bad",
            "source": {"type": "invalid_type"},
            "node_ids": ["n1"],
        }
        resp = c.post("/api/views", json=body)
        assert resp.status_code == 400

    def test_create_view_empty_name_returns_400(self, isolated_papergraph_dir):
        c = _make_client()
        body = {
            "name": "",
            "source": {"type": "ask"},
            "node_ids": ["n1"],
        }
        resp = c.post("/api/views", json=body)
        assert resp.status_code == 400

    def test_create_view_empty_node_ids_returns_400(self, isolated_papergraph_dir):
        c = _make_client()
        body = {
            "name": "Valid",
            "source": {"type": "ask"},
            "node_ids": [],
        }
        resp = c.post("/api/views", json=body)
        assert resp.status_code == 400

    def test_patch_view_rename(self, isolated_papergraph_dir):
        c = _make_client()
        view = self._create_view(c)
        view_id = view["view_id"]
        resp = c.patch(f"/api/views/{view_id}", json={"name": "Renamed"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "Renamed"

    def test_patch_view_pin(self, isolated_papergraph_dir):
        c = _make_client()
        view = self._create_view(c)
        view_id = view["view_id"]
        resp = c.patch(f"/api/views/{view_id}", json={"pinned": True})
        assert resp.status_code == 200
        assert resp.json()["pinned"] is True

    def test_patch_view_unknown_returns_404(self, isolated_papergraph_dir):
        c = _make_client()
        resp = c.patch("/api/views/view_nonexistent", json={"name": "X"})
        assert resp.status_code == 404

    def test_patch_view_empty_name_returns_400(self, isolated_papergraph_dir):
        c = _make_client()
        view = self._create_view(c)
        resp = c.patch(f"/api/views/{view['view_id']}", json={"name": ""})
        assert resp.status_code == 400

    def test_delete_view_happy(self, isolated_papergraph_dir):
        c = _make_client()
        view = self._create_view(c)
        view_id = view["view_id"]
        resp = c.delete(f"/api/views/{view_id}")
        assert resp.status_code == 200
        assert resp.json()["removed"] is True

    def test_delete_view_unknown_returns_404(self, isolated_papergraph_dir):
        c = _make_client()
        resp = c.delete("/api/views/view_nonexistent")
        assert resp.status_code == 404

    def test_get_view_graph_unknown_returns_404(self, isolated_papergraph_dir):
        c = _make_client()
        resp = c.get("/api/views/view_nonexistent/graph")
        assert resp.status_code == 404

    def test_get_view_graph_returns_shape(self, isolated_papergraph_dir):
        from research_companion import graph as _g
        _make_paper(isolated_papergraph_dir, "arxiv:vg001", "VG Paper")
        G = _g.build_graph()
        _g.save_graph(G)
        # Get node IDs from the graph
        node_ids = list(G.nodes())[:2] if len(G.nodes()) >= 1 else ["arxiv:vg001"]

        c = _make_client()
        body = {
            "name": "VG View",
            "source": {"type": "manual"},
            "node_ids": node_ids,
        }
        view_resp = c.post("/api/views", json=body)
        assert view_resp.status_code == 201
        view_id = view_resp.json()["view_id"]

        resp = c.get(f"/api/views/{view_id}/graph")
        assert resp.status_code == 200
        data = resp.json()
        assert "nodes" in data
        assert "edges" in data
        assert "view" in data
        assert "missing_node_ids" in data

    def test_view_graph_and_api_graph_node_key_sets_match(self, isolated_papergraph_dir):
        """Node dicts from /api/views/{id}/graph and /api/graph share the same key set."""
        from research_companion import graph as _g
        _make_paper(isolated_papergraph_dir, "arxiv:kg001", "KG Paper")
        G = _g.build_graph()
        _g.save_graph(G)
        node_ids = list(G.nodes())

        c = _make_client()
        # Create view with all nodes
        body = {
            "name": "KG View",
            "source": {"type": "manual"},
            "node_ids": node_ids,
        }
        view_resp = c.post("/api/views", json=body)
        view_id = view_resp.json()["view_id"]

        view_graph_resp = c.get(f"/api/views/{view_id}/graph")
        api_graph_resp = c.get("/api/graph")

        view_nodes = view_graph_resp.json()["nodes"]
        api_nodes = api_graph_resp.json()["nodes"]

        # Both have at least one node and their key sets must match
        if view_nodes and api_nodes:
            assert set(view_nodes[0].keys()) == set(api_nodes[0].keys()), (
                f"key sets differ: view={set(view_nodes[0].keys())}, "
                f"api={set(api_nodes[0].keys())}"
            )

    def test_view_graph_and_api_graph_edge_key_sets_match(self, isolated_papergraph_dir):
        """Edge dicts from /api/views/{id}/graph and /api/graph share the same key set."""
        from research_companion import graph as _g
        _make_paper(isolated_papergraph_dir, "arxiv:ke001", "KE Paper A")
        _make_paper(isolated_papergraph_dir, "arxiv:ke002", "KE Paper B")
        G = _g.build_graph()
        _g.save_graph(G)
        node_ids = list(G.nodes())

        c = _make_client()
        body = {
            "name": "KE View",
            "source": {"type": "manual"},
            "node_ids": node_ids,
        }
        view_resp = c.post("/api/views", json=body)
        view_id = view_resp.json()["view_id"]

        view_graph_resp = c.get(f"/api/views/{view_id}/graph")
        api_graph_resp = c.get("/api/graph")

        view_edges = view_graph_resp.json()["edges"]
        api_edges = api_graph_resp.json()["edges"]

        if view_edges and api_edges:
            assert set(view_edges[0].keys()) == set(api_edges[0].keys()), (
                f"edge key sets differ: view={set(view_edges[0].keys())}, "
                f"api={set(api_edges[0].keys())}"
            )


# ---------------------------------------------------------------------------
# W3-T7: GET /api/temporal
# ---------------------------------------------------------------------------

class TestTemporal:
    def _make_graph_with_papers(self, papergraph_dir, paper_data: list[dict]) -> None:
        """Create papers + a graph containing concept nodes linked to them."""
        from research_companion import graph as _g

        for pd in paper_data:
            _make_paper(papergraph_dir, pd["paper_id"], pd["title"],
                        year=pd["year"], write_extraction=True)

        G = _g.build_graph()
        _g.save_graph(G)

    def test_temporal_shape_keys(self, isolated_papergraph_dir):
        self._make_graph_with_papers(isolated_papergraph_dir, [
            {"paper_id": "arxiv:t001", "title": "Paper 2020", "year": 2020},
            {"paper_id": "arxiv:t002", "title": "Paper 2021", "year": 2021},
        ])
        c = _make_client()
        resp = c.get("/api/temporal")
        assert resp.status_code == 200
        data = resp.json()
        assert "years" in data
        assert "papers_per_year" in data
        assert "tracks" in data
        assert "skipped_papers_without_year" in data
        assert "truncated_tracks" in data

    def test_temporal_two_papers(self, isolated_papergraph_dir):
        self._make_graph_with_papers(isolated_papergraph_dir, [
            {"paper_id": "arxiv:t003", "title": "Paper 2022", "year": 2022},
            {"paper_id": "arxiv:t004", "title": "Paper 2023", "year": 2023},
        ])
        c = _make_client()
        resp = c.get("/api/temporal")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["years"], list)
        assert isinstance(data["papers_per_year"], list)
        assert isinstance(data["tracks"], list)
        assert isinstance(data["skipped_papers_without_year"], int)
        assert isinstance(data["truncated_tracks"], int)
        # Both papers have years so none should be skipped
        assert data["skipped_papers_without_year"] == 0

    def test_temporal_papers_per_year_structure(self, isolated_papergraph_dir):
        self._make_graph_with_papers(isolated_papergraph_dir, [
            {"paper_id": "arxiv:t005", "title": "Paper A", "year": 2019},
        ])
        c = _make_client()
        resp = c.get("/api/temporal")
        data = resp.json()
        for entry in data["papers_per_year"]:
            assert "year" in entry
            assert "count" in entry


# ---------------------------------------------------------------------------
# W3-T7: GET /api/search
# ---------------------------------------------------------------------------

class TestSearch:
    def test_search_missing_q_returns_400(self, isolated_papergraph_dir):
        c = _make_client()
        resp = c.get("/api/search")
        assert resp.status_code == 400

    def test_search_empty_q_returns_400(self, isolated_papergraph_dir):
        c = _make_client()
        resp = c.get("/api/search?q=")
        assert resp.status_code == 400

    def test_search_result_shape(self, isolated_papergraph_dir):
        _make_paper(isolated_papergraph_dir, "arxiv:s001", "Knowledge Graph Paper")
        c = _make_client()
        resp = c.get("/api/search?q=knowledge+graph")
        assert resp.status_code == 200
        data = resp.json()
        assert "query" in data
        assert "mode" in data
        assert "results" in data
        assert data["query"] == "knowledge graph"

    def test_search_result_item_shape(self, isolated_papergraph_dir):
        _make_paper(isolated_papergraph_dir, "arxiv:s002", "BM25 Retrieval Methods")
        c = _make_client()
        resp = c.get("/api/search?q=retrieval")
        assert resp.status_code == 200
        results = resp.json()["results"]
        for item in results:
            assert "paper_id" in item
            assert "paper_title" in item
            assert "section_id" in item
            assert "section_title" in item
            assert "score" in item
            assert "bm25" in item
            assert "cosine" in item
            assert "snippet" in item

    def test_search_k_honored(self, isolated_papergraph_dir):
        for i in range(5):
            _make_paper(isolated_papergraph_dir, f"arxiv:sk00{i}", f"Paper {i} Knowledge Graph BM25")
        c = _make_client()
        resp = c.get("/api/search?q=knowledge+graph&k=2")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) <= 2

    def test_search_bm25_mode(self, isolated_papergraph_dir):
        _make_paper(isolated_papergraph_dir, "arxiv:sb001", "BM25 Retrieval")
        c = _make_client()
        resp = c.get("/api/search?q=bm25")
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] in ("bm25", "hybrid")

    def test_search_snippet_max_200(self, isolated_papergraph_dir):
        _make_paper(isolated_papergraph_dir, "arxiv:ss001", "Long Snippet Paper")
        c = _make_client()
        resp = c.get("/api/search?q=snippet")
        assert resp.status_code == 200
        results = resp.json()["results"]
        for item in results:
            assert len(item["snippet"]) <= 200


# ---------------------------------------------------------------------------
# W3-T7: POST /api/ask — grounding node_ids
# ---------------------------------------------------------------------------

class TestAskGroundingNodeIds:
    def test_ask_grounding_has_node_ids(self, isolated_papergraph_dir):
        _make_paper(isolated_papergraph_dir, "arxiv:1111.22222", "My Paper")
        c = _make_client(llm=_fake_qa_llm)
        resp = c.post("/api/ask", json={"question": "What is this paper about?"})
        assert resp.status_code == 200
        data = resp.json()
        assert "grounding" in data
        grounding = data["grounding"]
        assert "node_ids" in grounding, "grounding.node_ids must be present"
        assert isinstance(grounding["node_ids"], list), "node_ids must be a list"

    def test_ask_grounding_paper_ids_still_present(self, isolated_papergraph_dir):
        """Ensure paper_ids is still in grounding (backward compat)."""
        _make_paper(isolated_papergraph_dir, "arxiv:1111.22222", "My Paper")
        c = _make_client(llm=_fake_qa_llm)
        resp = c.post("/api/ask", json={"question": "Tell me about methods."})
        assert resp.status_code == 200
        grounding = resp.json()["grounding"]
        assert "paper_ids" in grounding
        assert "node_ids" in grounding


# ---------------------------------------------------------------------------
# W3-T8: GET /api/journey
# ---------------------------------------------------------------------------

class TestJourneyEndpoint:
    def test_get_journey_shape(self, isolated_papergraph_dir):
        """GET /api/journey returns required shape keys."""
        c = _make_client()
        resp = c.get("/api/journey")
        assert resp.status_code == 200
        data = resp.json()
        assert "versions" in data
        assert "events" in data
        assert "counts_over_time" in data
        assert "current" in data
        assert "open" in data["current"]
        assert "addressed" in data["current"]
        assert "dismissed" in data["current"]

    def test_get_journey_empty_on_fresh_store(self, isolated_papergraph_dir):
        """No versions recorded yet."""
        c = _make_client()
        resp = c.get("/api/journey")
        assert resp.status_code == 200
        data = resp.json()
        assert data["versions"] == []
        assert data["counts_over_time"] == []

    def test_post_draft_records_version_and_publishes_event(self, isolated_papergraph_dir):
        """POST /api/draft with a new paper_id records a version and publishes DraftVersionAdded."""
        _make_paper(isolated_papergraph_dir, "local:jtest001", "Journey Test Paper")

        bus = Bus()
        app = create_lab_app(bus)

        import time
        with TestClient(app) as c:
            resp = c.post("/api/draft", json={"paper_id": "local:jtest001"})
            assert resp.status_code == 200

            # Allow background task to complete
            for _ in range(30):
                event_kinds = [type(e).__name__ for e in bus.history]
                if "DraftVersionAdded" in event_kinds:
                    break
                time.sleep(0.05)

        event_kinds = [type(e).__name__ for e in bus.history]
        assert "DraftVersionAdded" in event_kinds, (
            f"DraftVersionAdded not published. Events: {event_kinds}"
        )

        # Check journey recorded the version
        from research_companion.journey import load_journey
        j = load_journey()
        assert len(j["draft_versions"]) == 1
        assert j["draft_versions"][0]["paper_id"] == "local:jtest001"

    def test_post_draft_same_paper_no_duplicate_event(self, isolated_papergraph_dir):
        """Setting the same paper_id twice does NOT record a second version."""
        _make_paper(isolated_papergraph_dir, "local:jtest002", "Journey Test Paper 2")

        import time
        bus = Bus()
        app = create_lab_app(bus)
        with TestClient(app) as c:
            c.post("/api/draft", json={"paper_id": "local:jtest002"})
            time.sleep(0.1)
            c.post("/api/draft", json={"paper_id": "local:jtest002"})
            time.sleep(0.1)

        from research_companion.journey import load_journey
        j = load_journey()
        # Only one version recorded
        assert len(j["draft_versions"]) == 1

    def test_journey_events_newest_first(self, isolated_papergraph_dir):
        """Events in GET /api/journey response are returned newest first."""
        _make_paper(isolated_papergraph_dir, "local:jtest003", "Journey Paper 3")
        _make_paper(isolated_papergraph_dir, "local:jtest004", "Journey Paper 4")

        import time
        bus = Bus()
        app = create_lab_app(bus)
        with TestClient(app) as c:
            c.post("/api/draft", json={"paper_id": "local:jtest003"})
            time.sleep(0.05)
            c.post("/api/draft", json={"paper_id": "local:jtest004"})
            time.sleep(0.05)
            resp = c.get("/api/journey")

        assert resp.status_code == 200
        events = resp.json()["events"]
        if len(events) >= 2:
            assert events[0]["at"] >= events[1]["at"]


# ---------------------------------------------------------------------------
# POST /api/converse + GET /api/conversations/{id}
# ---------------------------------------------------------------------------

def _fake_converse_llm(prompt: str) -> str:
    """Fake LLM for converse tests: returns a prose answer with no citations."""
    return "The analysis artifact looks reasonable. No issues found [S1]."


class TestConverseEndpoint:
    def _seed_review(self, isolated_papergraph_dir, paper_id: str = "arxiv:conv001") -> str:
        from research_companion import store
        _make_paper(isolated_papergraph_dir, paper_id, "Converse Paper")
        store.save_review_report(paper_id, {
            "lanes": {"structure": {"ok": True, "items": []}}
        })
        return paper_id

    def test_happy_path_returns_answer(self, isolated_papergraph_dir):
        paper_id = self._seed_review(isolated_papergraph_dir)
        c = _make_client(llm=_fake_converse_llm)
        resp = c.post("/api/converse", json={
            "context": {"type": "review", "id": paper_id},
            "message": "What does the review say?",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "answer" in data
        assert "citations" in data
        assert "unverified_quotes" in data
        assert "conversation_id" in data
        assert data["conversation_id"].startswith("conv_")

    def test_empty_message_returns_400(self, isolated_papergraph_dir):
        paper_id = self._seed_review(isolated_papergraph_dir)
        c = _make_client(llm=_fake_converse_llm)
        resp = c.post("/api/converse", json={
            "context": {"type": "review", "id": paper_id},
            "message": "",
        })
        assert resp.status_code == 400

    def test_no_context_type_returns_400(self, isolated_papergraph_dir):
        c = _make_client(llm=_fake_converse_llm)
        resp = c.post("/api/converse", json={
            "context": {},
            "message": "hello",
        })
        assert resp.status_code == 400

    def test_unknown_context_type_returns_400(self, isolated_papergraph_dir):
        c = _make_client(llm=_fake_converse_llm)
        resp = c.post("/api/converse", json={
            "context": {"type": "bogus"},
            "message": "hello",
        })
        assert resp.status_code == 400

    def test_missing_review_report_falls_back_to_overview(self, isolated_papergraph_dir):
        # "review" is the default companion context: a missing report degrades to a
        # project overview instead of 404 so the chat always works out of the box.
        c = _make_client(llm=_fake_converse_llm)
        resp = c.post("/api/converse", json={
            "context": {"type": "review", "id": "arxiv:nonexistent9999"},
            "message": "What does the review say?",
        })
        assert resp.status_code == 200
        assert resp.json()["answer"]

    def test_missing_alignment_returns_404(self, isolated_papergraph_dir):
        # Explicit-artifact contexts still 404 when the artifact is absent.
        c = _make_client(llm=_fake_converse_llm)
        resp = c.post("/api/converse", json={
            "context": {"type": "alignment", "id": "arxiv:nonexistent9999"},
            "message": "How does this align?",
        })
        assert resp.status_code == 404

    def test_conversation_id_reuse(self, isolated_papergraph_dir):
        paper_id = self._seed_review(isolated_papergraph_dir)
        c = _make_client(llm=_fake_converse_llm)

        resp1 = c.post("/api/converse", json={
            "context": {"type": "review", "id": paper_id},
            "message": "First question.",
        })
        assert resp1.status_code == 200
        conv_id = resp1.json()["conversation_id"]

        resp2 = c.post("/api/converse", json={
            "context": {"type": "review", "id": paper_id},
            "message": "Follow-up question.",
            "conversation_id": conv_id,
        })
        assert resp2.status_code == 200
        assert resp2.json()["conversation_id"] == conv_id

    def test_citations_shape(self, isolated_papergraph_dir):
        paper_id = self._seed_review(isolated_papergraph_dir)
        c = _make_client(llm=_fake_converse_llm)
        resp = c.post("/api/converse", json={
            "context": {"type": "review", "id": paper_id},
            "message": "Explain the review.",
        })
        assert resp.status_code == 200
        citations = resp.json()["citations"]
        # Each citation should have the expected fields
        for cit in citations:
            assert "n" in cit
            assert "paper_id" in cit
            assert "title" in cit
            assert "section_id" in cit
            assert "section_title" in cit
            assert "cited" in cit

    def test_citations_include_char_offsets(self, isolated_papergraph_dir):
        """Converse citations mirror /api/ask: they carry absolute source
        offsets for exact-span reader highlighting (Phase 3 Task B)."""
        from research_companion import store
        paper_id = self._seed_review(isolated_papergraph_dir)
        c = _make_client(llm=_fake_converse_llm)
        resp = c.post("/api/converse", json={
            "context": {"type": "review", "id": paper_id},
            "message": "What is this paper about?",
        })
        assert resp.status_code == 200
        citations = resp.json()["citations"]
        assert citations, "expected at least one retrieved source"
        for cit in citations:
            assert "char_start" in cit
            assert "char_end" in cit
            assert "chunk_index" in cit
            assert isinstance(cit["char_start"], int)
            assert isinstance(cit["char_end"], int)
            assert isinstance(cit["chunk_index"], int)
        text = store.load_text(paper_id)
        first = citations[0]
        assert first["char_start"] == 0
        assert first["char_end"] == len(text)
        assert first["chunk_index"] == 0

    def test_app_state_llm_used(self, isolated_papergraph_dir):
        """When app.state.llm is set, converse endpoint uses it."""
        paper_id = self._seed_review(isolated_papergraph_dir)
        calls = []

        def tracking_llm(prompt: str) -> str:
            calls.append(prompt)
            return "Tracked answer."

        c = _make_client(llm=tracking_llm)
        resp = c.post("/api/converse", json={
            "context": {"type": "review", "id": paper_id},
            "message": "track this call",
        })
        assert resp.status_code == 200
        assert len(calls) >= 1
        assert resp.json()["answer"] == "Tracked answer."


class TestGetConversationEndpoint:
    def _seed_and_converse(self, isolated_papergraph_dir) -> str:
        """Create a paper + review and run one converse turn; return conversation_id."""
        from research_companion import store
        paper_id = "arxiv:gc001"
        _make_paper(isolated_papergraph_dir, paper_id, "GC Paper")
        store.save_review_report(paper_id, {
            "lanes": {"structure": {"ok": True, "items": []}}
        })
        c = _make_client(llm=_fake_converse_llm)
        resp = c.post("/api/converse", json={
            "context": {"type": "review", "id": paper_id},
            "message": "seed question",
        })
        return resp.json()["conversation_id"]

    def test_get_known_conversation(self, isolated_papergraph_dir):
        conv_id = self._seed_and_converse(isolated_papergraph_dir)
        c = _make_client(llm=_fake_converse_llm)
        resp = c.get(f"/api/conversations/{conv_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert "meta" in data
        assert "turns" in data
        assert len(data["turns"]) == 2  # user + assistant

    def test_get_unknown_conversation_returns_404(self, isolated_papergraph_dir):
        c = _make_client()
        resp = c.get("/api/conversations/conv_doesnotexist9999")
        assert resp.status_code == 404

    def test_conversation_meta_shape(self, isolated_papergraph_dir):
        conv_id = self._seed_and_converse(isolated_papergraph_dir)
        c = _make_client(llm=_fake_converse_llm)
        resp = c.get(f"/api/conversations/{conv_id}")
        assert resp.status_code == 200
        meta = resp.json()["meta"]
        assert meta["conversation_id"] == conv_id
        assert "context" in meta
        assert "created_at" in meta
        assert "prompt_sha256" in meta


class TestDeleteConversationEndpoint:
    def _seed_and_converse(self, isolated_papergraph_dir) -> str:
        """Create a paper + review and run one converse turn; return conversation_id."""
        from research_companion import store
        paper_id = "arxiv:dc001"
        _make_paper(isolated_papergraph_dir, paper_id, "DC Paper")
        store.save_review_report(paper_id, {
            "lanes": {"structure": {"ok": True, "items": []}}
        })
        c = _make_client(llm=_fake_converse_llm)
        resp = c.post("/api/converse", json={
            "context": {"type": "review", "id": paper_id},
            "message": "seed question",
        })
        return resp.json()["conversation_id"]

    def test_delete_known_conversation(self, isolated_papergraph_dir):
        conv_id = self._seed_and_converse(isolated_papergraph_dir)
        c = _make_client()
        resp = c.delete(f"/api/conversations/{conv_id}")
        assert resp.status_code == 200
        assert resp.json() == {"removed": True}
        assert c.get(f"/api/conversations/{conv_id}").status_code == 404

    def test_delete_unknown_conversation_returns_404(self, isolated_papergraph_dir):
        c = _make_client()
        resp = c.delete("/api/conversations/conv_doesnotexist9999")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/gaps + POST /api/gaps/refresh  (W3-T9)
# ---------------------------------------------------------------------------

class TestGapsEndpoints:
    def test_get_gaps_empty_store(self, isolated_papergraph_dir):
        """GET /api/gaps with empty store returns valid shape."""
        c = _make_client()
        resp = c.get("/api/gaps")
        assert resp.status_code == 200
        data = resp.json()
        assert "papers" in data
        assert "draft_addresses" in data
        assert "stale" in data
        assert data["papers"] == []
        assert data["draft_addresses"] == []

    def test_get_gaps_stale_flag(self, isolated_papergraph_dir):
        """GET /api/gaps stale=True when no resolution file exists."""
        _make_paper(isolated_papergraph_dir, "arxiv:gaps_001", "Gap Paper")
        c = _make_client()
        resp = c.get("/api/gaps")
        assert resp.status_code == 200
        data = resp.json()
        assert "stale" in data

    def test_get_gaps_with_preloaded_data(self, isolated_papergraph_dir):
        """GET /api/gaps returns paper with gaps when data is preloaded."""
        from research_companion import store
        from research_companion.gaps import _gap_id
        from research_companion.prompts import gap_prompt_sha256

        pid = "local:gaps_api_001"
        _make_paper(isolated_papergraph_dir, pid, "API Gaps Paper", year=2021)

        gid = _gap_id(pid, "Cannot scale to large datasets.")
        store.save_gaps(pid, {
            "prompt_sha256": gap_prompt_sha256(),
            "computed_at": "2024-01-01T00:00:00Z",
            "no_gap_sections": False,
            "gaps": [{
                "gap_id": gid,
                "statement": "Cannot scale to large datasets.",
                "kind": "limitation",
                "evidence": {"quote": "Cannot scale to large datasets.",
                             "verified": True, "match": "exact"},
            }],
        })

        c = _make_client()
        resp = c.get("/api/gaps")
        assert resp.status_code == 200
        data = resp.json()
        papers = data["papers"]
        assert len(papers) >= 1
        paper = next((p for p in papers if p["paper_id"] == pid), None)
        assert paper is not None
        assert len(paper["gaps"]) == 1
        g = paper["gaps"][0]
        assert g["gap_id"] == gid
        assert "resolution" in g

    def test_post_gaps_refresh_returns_202_with_job_id(self, isolated_papergraph_dir):
        """POST /api/gaps/refresh returns 202 with job_id."""
        def _noop_llm(prompt: str) -> str:
            return json.dumps({"gaps": []})

        c = _make_client(llm=_noop_llm)
        resp = c.post("/api/gaps/refresh")
        assert resp.status_code == 202
        data = resp.json()
        assert "job_id" in data

    def test_post_gaps_refresh_publishes_gaps_updated_event(self, isolated_papergraph_dir):
        """POST /api/gaps/refresh eventually publishes a GapsUpdated event."""
        import time

        from research_companion.agents.events import GapsUpdated

        bus = Bus()

        def _noop_llm(prompt: str) -> str:
            return json.dumps({"gaps": []})

        app = create_lab_app(bus, llm=_noop_llm)
        app.state._sse_done = True  # for test mode

        with TestClient(app) as c:
            c.post("/api/gaps/refresh")
            # Give the background task time to complete
            time.sleep(0.5)

        # Check bus history for GapsUpdated
        gaps_events = [e for e in bus.history if isinstance(e, GapsUpdated)]
        assert len(gaps_events) >= 1

    def test_post_gaps_refresh_job_tracked(self, isolated_papergraph_dir):
        """POST /api/gaps/refresh creates a job tracked via /api/jobs/{id}."""
        import time

        def _noop_llm(prompt: str) -> str:
            return json.dumps({"gaps": []})

        bus = Bus()
        app = create_lab_app(bus, llm=_noop_llm)

        with TestClient(app) as c:
            resp = c.post("/api/gaps/refresh")
            assert resp.status_code == 202
            job_id = resp.json()["job_id"]
            # Poll for job completion
            for _ in range(20):
                job_resp = c.get(f"/api/jobs/{job_id}")
                if job_resp.json()["status"] in ("done", "failed"):
                    break
                time.sleep(0.1)
            job_data = c.get(f"/api/jobs/{job_id}").json()
            assert job_data["kind"] == "gaps"


class TestRegenerateWithoutReviewReport:
    """W3 wrap-up fix: alignment-only suggestions must work without a review report."""

    def test_regenerate_succeeds_with_alignments_but_no_report(self):
        from research_companion import store

        client = _make_client()

        # Draft + one aligned candidate, NO review report persisted
        meta = store.PaperMetadata(paper_id="local:draftnr", title="Draft NR",
                                   authors=["A"], year=2026)
        meta.save()
        store.set_draft_paper_id("local:draftnr")
        cand = store.PaperMetadata(paper_id="arxiv:9999.00001", title="Challenger",
                                   authors=["B"], year=2025)
        cand.save()
        store.save_alignment("arxiv:9999.00001", {
            "version": 1, "draft_paper_id": "local:draftnr",
            "candidate_paper_id": "arxiv:9999.00001",
            "prompt_sha256": "x", "computed_at": "2026-07-07T00:00:00Z",
            "score": 0.8, "band": 0.1, "verdict": "high",
            "signals": {"quote_verification": 1.0, "llm_relevance": 0.8,
                        "lexical_overlap": 0.5},
            "sections": [{"section_id": "s2", "section_title": "Method",
                          "relation": "challenges", "relevance": 0.8,
                          "rationale": "r",
                          "evidence": [{"quote": "q", "verified": True,
                                        "match": "exact"}]}],
        })

        resp = client.post("/api/suggestions/regenerate", json={})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["counts"]["open"] >= 1
        kinds = {s["kind"] for s in data["suggestions"]}
        assert "evidence" in kinds  # the challenges-derived suggestion


# ---------------------------------------------------------------------------
# POST /api/papers/upload — raw-body PDF upload (v0.3.1)
# ---------------------------------------------------------------------------

_UPLOAD_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n"
    b"trailer<</Size 4/Root 1 0 R>>\nstartxref\n0\n%%EOF\n"
)


class TestUploadPaper:
    """Raw-body upload: the browser file-picker/drag-drop path."""

    def _client(self):
        async def _noop_upload(meta, bus):
            pass

        app = create_lab_app(Bus())
        app.state.upload_override = _noop_upload
        return app, TestClient(app)

    def _post(self, c, *, filename="my draft.pdf", set_draft=False, body=_UPLOAD_PDF):
        qs = f"?filename={filename}&set_draft={'true' if set_draft else 'false'}"
        return c.post(f"/api/papers/upload{qs}", content=body,
                      headers={"Content-Type": "application/pdf"})

    def test_upload_returns_202_and_paper_appears(self, isolated_papergraph_dir):
        app, c = self._client()
        with c:
            resp = self._post(c, filename="my%20draft.pdf")
            assert resp.status_code == 202
            data = resp.json()
            assert data["paper_id"].startswith("local:")
            assert data["duplicate"] is False
            assert data["job_id"]

            papers = c.get("/api/papers").json()
            mine = next(p for p in papers if p["paper_id"] == data["paper_id"])
            assert "draft" in mine["title"].lower() or mine["title"]

    def test_upload_title_from_filename(self, isolated_papergraph_dir):
        from research_companion.store import PaperMetadata
        app, c = self._client()
        with c:
            resp = self._post(c, filename="My Great Paper.pdf")
            meta = PaperMetadata.load(resp.json()["paper_id"])
            assert meta.title == "My Great Paper"
            assert meta.source_url == "upload://My Great Paper.pdf"

    def test_upload_set_draft_true_sets_draft(self, isolated_papergraph_dir):
        app, c = self._client()
        with c:
            resp = self._post(c, set_draft=True)
            assert resp.json()["draft_set"] is True
            pid = resp.json()["paper_id"]
            assert c.get("/api/draft").json()["draft_paper_id"] == pid
            papers = c.get("/api/papers").json()
            assert next(p for p in papers if p["paper_id"] == pid)["is_draft"] is True

    def test_upload_set_draft_records_journey_version(self, isolated_papergraph_dir):
        from research_companion.journey import load_journey
        app, c = self._client()
        with c:
            resp = self._post(c, set_draft=True)
            versions = load_journey()["draft_versions"]
            assert versions and versions[-1]["paper_id"] == resp.json()["paper_id"]

    def test_upload_set_draft_false_leaves_draft_unchanged(self, isolated_papergraph_dir):
        app, c = self._client()
        with c:
            _make_paper(isolated_papergraph_dir, "arxiv:up_keep01", title="Existing Draft")
            c.post("/api/draft", json={"paper_id": "arxiv:up_keep01"})
            self._post(c, set_draft=False)
            assert c.get("/api/draft").json()["draft_paper_id"] == "arxiv:up_keep01"

    def test_upload_rejects_non_pdf_400(self, isolated_papergraph_dir):
        app, c = self._client()
        with c:
            resp = self._post(c, body=b"hello world, not a pdf at all")
            assert resp.status_code == 400
            assert "PDF" in resp.json()["detail"]

    def test_upload_rejects_empty_400(self, isolated_papergraph_dir):
        app, c = self._client()
        with c:
            resp = self._post(c, body=b"")
            assert resp.status_code == 400

    def test_upload_rejects_oversize_413(self, isolated_papergraph_dir, monkeypatch):
        import research_companion.lab_api as la
        monkeypatch.setattr(la, "_MAX_UPLOAD_BYTES", 1024)
        app, c = self._client()
        with c:
            resp = self._post(c, body=b"%PDF-1.4" + b"x" * 2048)
            assert resp.status_code == 413

    def test_upload_duplicate_returns_200_with_existing_id(self, isolated_papergraph_dir):
        app, c = self._client()
        with c:
            first = self._post(c).json()
            resp = self._post(c)
            assert resp.status_code == 200
            data = resp.json()
            assert data["duplicate"] is True
            assert data["paper_id"] == first["paper_id"]
            assert data["job_id"] is None

    def test_upload_duplicate_with_set_draft_still_sets_draft(self, isolated_papergraph_dir):
        app, c = self._client()
        with c:
            first = self._post(c).json()
            resp = self._post(c, set_draft=True)
            assert resp.status_code == 200
            assert resp.json()["draft_set"] is True
            assert c.get("/api/draft").json()["draft_paper_id"] == first["paper_id"]

    def test_upload_pipeline_stages_run_via_seams(self, isolated_papergraph_dir):
        from research_companion import store as _store

        bus = Bus()
        app = create_lab_app(bus)
        _fake_meta, counts, seam_overrides = _make_pipeline_spying_fakes(store_paper=False)
        app.state.pipeline_overrides = seam_overrides
        # Pre-seed text for the sha-derived id so get_paper_text succeeds
        expected_id = _store.make_local_id(_UPLOAD_PDF)
        _store.save_text(expected_id, "Uploaded text. Introduction Methods Results. " * 6)

        with TestClient(app) as c:
            resp = self._post(c, filename="pipeline.pdf")
            assert resp.status_code == 202
            job_id = resp.json()["job_id"]

            import time as _time
            deadline = _time.time() + 10
            while _time.time() < deadline:
                job = c.get(f"/api/jobs/{job_id}").json()
                if job["status"] in ("done", "failed"):
                    break
                _time.sleep(0.05)
            assert job["status"] == "done", job
            assert counts["extractor"] == 1
            assert counts["sectioner"] == 1

        kinds = [type(e).__name__ for e in bus.history]
        assert "PaperAdded" in kinds
        assert "JobDone" in kinds


class TestPipelineProviderFromSettings:
    """REGRESSION: the extraction pipeline resolved its provider from a raw
    env var (defaulting to anthropic) while /api/settings resolved it from
    the saved settings — so a server started without the env var extracted
    with the WRONG provider and failed auth, while the Settings page showed
    the right one. The pipeline must use the same resolution as settings."""

    def test_pipeline_provider_matches_saved_settings(self, isolated_papergraph_dir, monkeypatch):
        import research_companion.lab_api as la
        from research_companion.settings import update_settings

        monkeypatch.delenv("RESEARCH_COMPANION_PROVIDER", raising=False)
        monkeypatch.delenv("RESEARCH_COMPANION_MODEL", raising=False)
        update_settings({"provider": "openai"})
        # update_settings mirrors to env; clear again to simulate a FRESH
        # process that only has settings.json (the failing scenario)
        monkeypatch.delenv("RESEARCH_COMPANION_PROVIDER", raising=False)

        assert la._pipeline_provider_model() == ("openai", None)

    def test_env_var_still_wins_when_set(self, isolated_papergraph_dir, monkeypatch):
        import research_companion.lab_api as la
        monkeypatch.setenv("RESEARCH_COMPANION_PROVIDER", "openai")
        monkeypatch.setenv("RESEARCH_COMPANION_MODEL", "gpt-4o-2024-11-20")
        assert la._pipeline_provider_model() == ("openai", "gpt-4o-2024-11-20")
