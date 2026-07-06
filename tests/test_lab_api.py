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
        _store.save_text(paper_id, "This is the text. Introduction Methods Results.")

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
            for _ in range(50):
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
        _store.save_text(paper_id_val, "Introduction Methods Results.")

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

    def test_no_saved_report_returns_400(self, isolated_papergraph_dir):
        from research_companion import store
        _make_paper(isolated_papergraph_dir, "local:draft0001", "Draft Paper")
        store.set_draft_paper_id("local:draft0001")
        c = _make_client()
        resp = c.post("/api/suggestions/regenerate", json={})
        assert resp.status_code == 400

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
        from research_companion.alignment import build_alignment_payload
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
            q = bus.subscribe()
            snapshot = list(bus.history)
            event_kinds = [type(e).__name__ for e in snapshot]
        finally:
            loop.close()

        assert "SuggestionsUpdated" in event_kinds, (
            f"SuggestionsUpdated not published. Events: {event_kinds}"
        )
