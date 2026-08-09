"""Tests for the require_active_workspace() write-guard (409 on mutating
endpoints, reads stay 200 + empty) when no research is active."""
from __future__ import annotations

import pytest

from research_companion import store

_fastapi = pytest.importorskip("fastapi", reason="fastapi required for lab_api tests")
from fastapi.testclient import TestClient  # noqa: E402

from research_companion.agents.bus import Bus  # noqa: E402
from research_companion.lab_api import create_lab_app  # noqa: E402


def _make_client() -> tuple:
    bus = Bus()
    app = create_lab_app(bus)
    return app, bus, TestClient(app)


@pytest.fixture
def no_active_workspace(isolated_papergraph_dir):
    reg = store.load_registry()
    reg["active"] = None
    store.save_registry(reg)
    store._reset_workspace_caches()
    return reg


class TestMutatingEndpoints409:
    def test_add_paper_409(self, no_active_workspace):
        _app, _bus, c = _make_client()
        with c:
            resp = c.post("/api/papers", json={"target": "arxiv:2410.05779"})
            assert resp.status_code == 409
            assert resp.json() == {"error": "no_active_workspace"}

    def test_delete_paper_409(self, no_active_workspace):
        _app, _bus, c = _make_client()
        with c:
            resp = c.delete("/api/papers/arxiv:none-active")
            assert resp.status_code == 409
            assert resp.json() == {"error": "no_active_workspace"}

    def test_create_note_409(self, no_active_workspace):
        _app, _bus, c = _make_client()
        with c:
            resp = c.post("/api/notes", json={"kind": "freeform", "comment": "x"})
            assert resp.status_code == 409
            assert resp.json() == {"error": "no_active_workspace"}

    def test_ingest_409(self, no_active_workspace):
        _app, _bus, c = _make_client()
        with c:
            resp = c.post("/api/ingest", json={"folder": "C:/some/folder"})
            assert resp.status_code == 409
            assert resp.json() == {"error": "no_active_workspace"}

    def test_converse_409(self, no_active_workspace):
        _app, _bus, c = _make_client()
        with c:
            resp = c.post("/api/converse", json={
                "message": "hi", "context": {"type": "ask"}})
            assert resp.status_code == 409
            assert resp.json() == {"error": "no_active_workspace"}

    def test_align_409(self, no_active_workspace):
        _app, _bus, c = _make_client()
        with c:
            resp = c.post("/api/align", json={"paper_id": "arxiv:x"})
            assert resp.status_code == 409

    def test_views_create_409(self, no_active_workspace):
        _app, _bus, c = _make_client()
        with c:
            resp = c.post("/api/views", json={"name": "v1", "source": {"type": "manual"},
                                               "node_ids": []})
            assert resp.status_code == 409


class TestReadEndpointsStay200Empty:
    def test_get_papers_empty_200(self, no_active_workspace):
        _app, _bus, c = _make_client()
        with c:
            resp = c.get("/api/papers")
            assert resp.status_code == 200
            assert resp.json() == []

    def test_get_graph_empty_200(self, no_active_workspace):
        _app, _bus, c = _make_client()
        with c:
            resp = c.get("/api/graph")
            assert resp.status_code == 200

    def test_get_journey_empty_200(self, no_active_workspace):
        _app, _bus, c = _make_client()
        with c:
            resp = c.get("/api/journey")
            assert resp.status_code == 200
            assert resp.json()["versions"] == []

    def test_get_suggestions_empty_200(self, no_active_workspace):
        _app, _bus, c = _make_client()
        with c:
            resp = c.get("/api/suggestions")
            assert resp.status_code == 200
            assert resp.json()["suggestions"] == []

    def test_get_notes_empty_200(self, no_active_workspace):
        _app, _bus, c = _make_client()
        with c:
            resp = c.get("/api/notes")
            assert resp.status_code == 200


class TestWorkspaceCrudExemptFromGuard:
    def test_create_workspace_still_works_when_none_active(self, no_active_workspace):
        _app, _bus, c = _make_client()
        with c:
            resp = c.post("/api/workspaces", json={"name": "Fresh Start"})
            assert resp.status_code == 201

    def test_activate_workspace_still_works_when_none_active(self, no_active_workspace):
        _app, _bus, c = _make_client()
        with c:
            resp = c.post("/api/workspaces/main/activate")
            assert resp.status_code == 200
            assert store.active_workspace_id() == "main"
