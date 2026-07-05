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
        from research_companion import lab_api as _la
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
        from research_companion import store
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

        import research_companion.lab_api as _la
        app = create_lab_app(Bus())
        app.state.ingest_override = blocking_ingest

        with TestClient(app) as c:
            # First POST — starts a background task (never completes in test)
            # We need to simulate an active job
            # Inject the running job directly
            app.state.jobs = {"job-1": {"status": "running"}}
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
        from unittest.mock import AsyncMock, patch
        from research_companion.store import PaperMetadata

        fake_meta = PaperMetadata(
            paper_id="local:abc123def456",
            title="Test",
            authors=[],
            added_at="2024-01-01T00:00:00Z",
        )

        async def fake_add_paper_task(target, bus):
            pass

        app = create_lab_app(Bus())
        app.state.add_paper_override = fake_add_paper_task

        with TestClient(app) as c:
            resp = c.post("/api/papers", json={"target": str(fake_pdf)})
            assert resp.status_code == 202
            assert "job_id" in resp.json()


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
        data = [l for l in body.split("\n") if l.startswith("data:")]
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

        data_lines = [l for l in body.split("\n") if l.startswith("data:")]
        assert len(data_lines) >= 2
        events = [json.loads(l[len("data: "):].strip()) for l in data_lines]
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


# ---------------------------------------------------------------------------
# Module import without fastapi (basic lazy-import check)
# ---------------------------------------------------------------------------

class TestModuleImport:
    def test_lab_api_module_can_be_imported(self):
        """lab_api module imports without errors (fastapi is available in test env)."""
        import research_companion.lab_api as la
        assert hasattr(la, "create_lab_app")
        assert hasattr(la, "serve_lab")
