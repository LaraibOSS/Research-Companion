"""Lab endpoints for the Zotero import: status, collections, the import job.

Zotero is a fake transport and the fetch adds are replaced, so nothing here
contacts Zotero or the network.
"""
from __future__ import annotations

import time

import pytest

from research_companion import fetch, store
from research_companion.interop import zotero
from tests.test_interop_zotero import FakeZotero, _item

_fastapi = pytest.importorskip("fastapi", reason="fastapi required for lab_api tests")
from fastapi.testclient import TestClient  # noqa: E402

from research_companion.agents.bus import Bus  # noqa: E402
from research_companion.lab_api import create_lab_app  # noqa: E402


def _client():
    bus = Bus()
    app = create_lab_app(bus)
    return app, bus, TestClient(app)


def _wait(c, job_id, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = c.get(f"/api/jobs/{job_id}").json()
        if job["status"] != "running":
            return job
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} still running")


@pytest.fixture
def fake_zotero(monkeypatch):
    fake = FakeZotero([_item("A1", "Via arXiv", extra="arXiv: 2101.00001"),
                       _item("M1", "Only metadata")],
                      collections={"COLL1": {"name": "Thesis",
                                             "items": [_item("M2", "In the collection")]}})
    monkeypatch.setattr(zotero, "http_get", fake)

    def fake_arxiv(aid):
        meta = store.PaperMetadata(paper_id=store.make_arxiv_id(aid), title="Via arXiv",
                                   authors=[])
        meta.save()
        store.save_pdf(meta.paper_id, b"%PDF-1.4 x")
        return meta

    monkeypatch.setattr(fetch, "add_arxiv", fake_arxiv)
    return fake


class TestStatus:
    def test_ready(self, fake_zotero):
        _app, _bus, c = _client()
        with c:
            r = c.get("/api/zotero/status")
        assert r.status_code == 200
        assert r.json()["state"] == "ready"

    def test_disabled(self, monkeypatch):
        monkeypatch.setattr(zotero, "http_get", FakeZotero(status=403))
        _app, _bus, c = _client()
        with c:
            body = c.get("/api/zotero/status").json()
        assert body["state"] == "disabled"
        assert "Advanced" in body["message"]

    def test_not_running(self, monkeypatch):
        monkeypatch.setattr(zotero, "http_get",
                            FakeZotero(raise_exc=zotero.ZoteroNotRunning("x")))
        _app, _bus, c = _client()
        with c:
            assert c.get("/api/zotero/status").json()["state"] == "not_running"


class TestCollections:
    def test_lists(self, fake_zotero):
        _app, _bus, c = _client()
        with c:
            r = c.get("/api/zotero/collections")
        assert r.status_code == 200
        assert r.json()["collections"][0]["key"] == "COLL1"

    def test_unreadable_is_503_with_reason(self, monkeypatch):
        monkeypatch.setattr(zotero, "http_get", FakeZotero(status=403))
        _app, _bus, c = _client()
        with c:
            r = c.get("/api/zotero/collections")
        assert r.status_code == 503
        assert "Advanced" in r.json()["detail"]


class TestImport:
    def test_preview_is_the_default_and_writes_nothing(self, fake_zotero):
        _app, _bus, c = _client()
        with c:
            r = c.post("/api/zotero/import", json={})
            assert r.status_code == 202
            assert r.json()["dry_run"] is True
            job = _wait(c, r.json()["job_id"])
        assert job["status"] == "done"
        rep = job["report"]
        assert rep["dry_run"] is True and rep["added"] == 1 and rep["metadata_only"] == 1
        assert store.list_papers() == []

    def test_import_adds_papers(self, fake_zotero):
        _app, _bus, c = _client()
        with c:
            r = c.post("/api/zotero/import", json={"dry_run": False})
            job = _wait(c, r.json()["job_id"])
            papers = {p["paper_id"] for p in c.get("/api/papers").json()}
        assert job["status"] == "done", job
        assert job["kind"] == "zotero-import"
        assert job["progress"] == {"done": 2, "total": 2}
        assert {"arxiv:2101.00001", "zotero:M1"} <= papers

    def test_collection(self, fake_zotero):
        _app, _bus, c = _client()
        with c:
            r = c.post("/api/zotero/import",
                       json={"collection_key": "COLL1", "dry_run": False})
            job = _wait(c, r.json()["job_id"])
        assert job["report"]["total"] == 1
        assert store.PaperMetadata.load("zotero:M2") is not None

    def test_publishes_job_started_and_finished(self, fake_zotero):
        _app, bus, c = _client()
        with c:
            r = c.post("/api/zotero/import", json={"dry_run": True})
            _wait(c, r.json()["job_id"])
            time.sleep(0.1)
        kinds = [(type(e).__name__, getattr(e, "kind", None)) for e in bus.history]
        assert ("JobStarted", "zotero-import") in kinds
        assert ("JobFinished", "zotero-import") in kinds

    def test_bad_collection_fails_the_job_with_reason(self, fake_zotero):
        _app, _bus, c = _client()
        with c:
            r = c.post("/api/zotero/import", json={"collection_key": "NOPE"})
            job = _wait(c, r.json()["job_id"])
        assert job["status"] == "failed"
        assert "could not find collection" in job["detail"]

    def test_zotero_off_is_refused_before_a_job_starts(self, monkeypatch):
        monkeypatch.setattr(zotero, "http_get", FakeZotero(status=403))
        app, _bus, c = _client()
        with c:
            r = c.post("/api/zotero/import", json={"dry_run": False})
        assert r.status_code == 503
        assert "Allow other applications" in r.json()["detail"]
        assert not any(j.get("kind") == "zotero-import" for j in app.state.jobs.values())

    def test_second_import_while_running_is_409(self, fake_zotero):
        app, _bus, c = _client()
        with c:
            app.state.jobs["job-x"] = {"status": "running", "kind": "zotero-import"}
            r = c.post("/api/zotero/import", json={})
        assert r.status_code == 409

    def test_requires_active_research(self, fake_zotero):
        reg = store.load_registry()
        reg["active"] = None
        store.save_registry(reg)
        store._reset_workspace_caches()
        _app, _bus, c = _client()
        with c:
            r = c.post("/api/zotero/import", json={"dry_run": False})
        assert r.status_code == 409
        assert r.json() == {"error": "no_active_workspace"}

    def test_cross_origin_post_refused(self, fake_zotero):
        _app, _bus, c = _client()
        with c:
            r = c.post("/api/zotero/import", json={"dry_run": False},
                       headers={"Origin": "https://evil.example"})
        assert r.status_code == 403
