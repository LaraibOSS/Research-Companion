"""Tests for /api/draft/citations endpoints + coverage refresh hooks (W5-C2)."""
from __future__ import annotations

import time

import pytest

from research_companion import store
from research_companion.citations_coverage import load_coverage

_fastapi = pytest.importorskip("fastapi", reason="fastapi required for lab_api tests")
from fastapi.testclient import TestClient  # noqa: E402

from research_companion.agents.bus import Bus  # noqa: E402
from research_companion.lab_api import create_lab_app  # noqa: E402

_BIB = """[1] A. Vaswani et al. Attention is all you need. NeurIPS, 2017.
[2] J. Devlin et al. BERT: Pre-training of deep bidirectional transformers. arXiv:1810.04805, 2018.
[3] E. Hu et al. LoRA: Low-rank adaptation of large language models. arXiv:2106.09685, 2021."""


def _seed_draft(draft_id="local:citdraft01"):
    text = "Introduction\nBody.\n\nReferences\n" + _BIB + "\n"
    store.PaperMetadata(paper_id=draft_id, title="Draft", authors=["Me"],
                        year=2026, added_at="2026-01-01T00:00:00Z").save()
    store.save_text(draft_id, text)
    store.set_draft_paper_id(draft_id)
    return draft_id


def _make_client():
    bus = Bus()
    app = create_lab_app(bus)
    return app, bus, TestClient(app)


class TestGetDraftCitations:
    def test_no_draft_empty_shape(self, isolated_papergraph_dir):
        _app, _bus, c = _make_client()
        with c:
            data = c.get("/api/draft/citations").json()
            assert data["draft_paper_id"] is None
            assert data["source"] == "none"
            assert data["references"] == []
            assert data["counts"]["total"] == 0

    def test_computes_and_caches(self, isolated_papergraph_dir):
        _seed_draft()
        _app, _bus, c = _make_client()
        with c:
            data = c.get("/api/draft/citations").json()
            assert data["source"] == "bibliography"
            assert data["counts"]["total"] == 3
            assert data["counts"]["available"] == 2   # two parsed arXiv ids
            assert data["counts"]["unchecked"] == 1   # Vaswani, title-only
        assert load_coverage()["counts"]["total"] == 3

    def test_stale_on_text_change_recomputes(self, isolated_papergraph_dir):
        draft = _seed_draft()
        _app, _bus, c = _make_client()
        with c:
            assert c.get("/api/draft/citations").json()["counts"]["total"] == 3
            store.save_text(draft, "Intro.\n\nReferences\n" + _BIB +
                            "\n[4] New Author. A fourth cited paper title. 2024.\n")
            assert c.get("/api/draft/citations").json()["counts"]["total"] == 4

    def test_no_text_draft_returns_none_source(self, isolated_papergraph_dir):
        store.PaperMetadata(paper_id="local:notext", title="D", authors=["M"],
                            year=2026, added_at="2026-01-01T00:00:00Z").save()
        store.set_draft_paper_id("local:notext")
        _app, _bus, c = _make_client()
        with c:
            data = c.get("/api/draft/citations").json()
            assert data["source"] == "none"
        assert load_coverage() is None


class TestResolveEndpoint:
    def test_resolve_400_without_draft(self, isolated_papergraph_dir):
        _app, _bus, c = _make_client()
        with c:
            assert c.post("/api/draft/citations/resolve").status_code == 400

    def test_resolve_job_flips_and_publishes(self, isolated_papergraph_dir):
        _seed_draft()
        app, bus, c = _make_client()

        def fake_resolver(ref):
            return {"title": "Attention Is All You Need", "year": 2017,
                    "doi": None, "arxiv_id": "1706.03762"}
        app.state.citations_resolver_override = fake_resolver

        with c:
            resp = c.post("/api/draft/citations/resolve")
            assert resp.status_code == 202
            job_id = resp.json()["job_id"]
            deadline = time.time() + 10
            while time.time() < deadline:
                job = c.get(f"/api/jobs/{job_id}").json()
                if job["status"] in ("done", "failed"):
                    break
                time.sleep(0.05)
            assert job["status"] == "done", job
            data = c.get("/api/draft/citations").json()
            assert data["counts"]["unchecked"] == 0
            assert data["counts"]["available"] == 3
        kinds = [type(e).__name__ for e in bus.history]
        assert "CitationCoverageUpdated" in kinds

    def test_resolve_409_when_running(self, isolated_papergraph_dir):
        _seed_draft()
        app, _bus, c = _make_client()
        with c:
            app.state.jobs["job-77"] = {"status": "running", "detail": None, "kind": "citations"}
            assert c.post("/api/draft/citations/resolve").status_code == 409


class TestCoverageRefreshHooks:
    def test_add_paper_job_completion_triggers_recompute_and_event(
            self, isolated_papergraph_dir):
        _seed_draft()
        app, bus, c = _make_client()

        async def fake_add(target, b):
            # Simulate the add job storing the BERT paper
            store.PaperMetadata(
                paper_id="arxiv:1810.04805",
                title="BERT: Pre-training of Deep Bidirectional Transformers",
                authors=["Devlin"], year=2018,
                added_at="2026-01-02T00:00:00Z").save()
        app.state.add_paper_override = fake_add

        with c:
            resp = c.post("/api/papers", json={"target": "1810.04805"})
            job_id = resp.json()["job_id"]
            deadline = time.time() + 10
            while time.time() < deadline:
                if c.get(f"/api/jobs/{job_id}").json()["status"] == "done":
                    break
                time.sleep(0.05)
            # background coverage refresh runs as a task — poll for the result
            deadline = time.time() + 10
            in_lib = 0
            while time.time() < deadline:
                cov = load_coverage()
                in_lib = (cov or {}).get("counts", {}).get("in_library", 0)
                if in_lib >= 1:
                    break
                time.sleep(0.05)
            assert in_lib == 1
        kinds = [type(e).__name__ for e in bus.history]
        assert "CitationCoverageUpdated" in kinds

    def test_apply_draft_triggers_coverage(self, isolated_papergraph_dir):
        draft = _seed_draft()
        store.set_draft_paper_id(None)
        _app, bus, c = _make_client()
        with c:
            c.post("/api/draft", json={"paper_id": draft})
            deadline = time.time() + 10
            while time.time() < deadline:
                if load_coverage() is not None:
                    break
                time.sleep(0.05)
            assert load_coverage()["counts"]["total"] == 3


class TestCitationEventRoundTrip:
    def test_event_to_dict_kind(self):
        from research_companion.agents.events import (
            CitationCoverageUpdated,
            event_to_dict,
        )
        d = event_to_dict(CitationCoverageUpdated(
            draft_paper_id="local:x", total=5, in_library=2,
            available=2, unchecked=1, unresolved=0))
        assert d["event"] == "citation_coverage_updated"
        assert d["total"] == 5
