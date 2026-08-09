"""Tests for the /api/workspaces endpoints (W4-B4)."""
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


class TestWorkspaceCrud:
    def test_get_lists_default_main_with_stats(self, isolated_papergraph_dir):
        _app, _bus, c = _make_client()
        with c:
            data = c.get("/api/workspaces").json()
            assert data["active"] == "main"
            main = next(w for w in data["workspaces"] if w["id"] == "main")
            assert "stats" in main
            assert main["stats"]["papers"] == 0

    def test_create_201_and_listed(self, isolated_papergraph_dir):
        _app, _bus, c = _make_client()
        with c:
            resp = c.post("/api/workspaces", json={"name": "LLM Safety"})
            assert resp.status_code == 201
            assert resp.json()["id"] == "llm-safety"
            ids = [w["id"] for w in c.get("/api/workspaces").json()["workspaces"]]
            assert "llm-safety" in ids and "main" in ids

    def test_create_duplicate_409_empty_422(self, isolated_papergraph_dir):
        _app, _bus, c = _make_client()
        with c:
            c.post("/api/workspaces", json={"name": "Twice"})
            assert c.post("/api/workspaces", json={"name": "twice"}).status_code == 409
            assert c.post("/api/workspaces", json={"name": "!!!"}).status_code == 422

    def test_patch_rename_and_archive(self, isolated_papergraph_dir):
        _app, _bus, c = _make_client()
        with c:
            c.post("/api/workspaces", json={"name": "Other"})
            resp = c.patch("/api/workspaces/other", json={"name": "Renamed"})
            assert resp.status_code == 200
            assert resp.json()["name"] == "Renamed"
            assert c.patch("/api/workspaces/other",
                           json={"archived": True}).json()["archived"] is True

    def test_patch_unknown_404_archive_active_409(self, isolated_papergraph_dir):
        _app, _bus, c = _make_client()
        with c:
            assert c.patch("/api/workspaces/nope", json={"name": "x"}).status_code == 404
            assert c.patch("/api/workspaces/main",
                           json={"archived": True}).status_code == 409


class TestActivate:
    def test_activate_switches_and_instructs_reload(self, isolated_papergraph_dir):
        _app, _bus, c = _make_client()
        with c:
            c.post("/api/workspaces", json={"name": "Proj B"})
            resp = c.post("/api/workspaces/proj-b/activate")
            assert resp.status_code == 200
            assert resp.json() == {"active": "proj-b", "reload": True}
            assert store.papergraph_dir().name == "proj-b"

    def test_papers_endpoint_reads_new_workspace(self, isolated_papergraph_dir):
        # Seed a paper into main, switch, expect an empty library
        meta = store.PaperMetadata(
            paper_id="arxiv:wsx", title="Main Paper", authors=["A"],
            added_at="2026-01-01T00:00:00Z")
        meta.save()
        _app, _bus, c = _make_client()
        with c:
            assert len(c.get("/api/papers").json()) == 1
            c.post("/api/workspaces", json={"name": "Fresh"})
            c.post("/api/workspaces/fresh/activate")
            assert c.get("/api/papers").json() == []

    def test_activate_resets_recorder_and_publishes_workspace_changed(
            self, isolated_papergraph_dir):
        app, bus, c = _make_client()
        with c:
            c.post("/api/workspaces", json={"name": "Proj C"})
            # Give the recorder something to forget
            assert app.state.recorder.current_max_seq() >= 0
            c.post("/api/workspaces/proj-c/activate")
            snap = app.state.recorder.snapshot()
            # bus.history holds exactly the WorkspaceChanged event
            kinds = [type(e).__name__ for e in bus.history]
            assert kinds == ["WorkspaceChanged"]
            # recorder restarted: nothing above seq 1 recorded from before
            assert all(seq >= 1 for seq, _ in snap)
            assert app.state.recorder.current_max_seq() <= 1

    def test_activate_unknown_404_archived_409(self, isolated_papergraph_dir):
        _app, _bus, c = _make_client()
        with c:
            assert c.post("/api/workspaces/nope/activate").status_code == 404
            c.post("/api/workspaces", json={"name": "Arch"})
            c.patch("/api/workspaces/arch", json={"archived": True})
            assert c.post("/api/workspaces/arch/activate").status_code == 409

    def test_activate_blocked_while_job_running(self, isolated_papergraph_dir):
        app, _bus, c = _make_client()
        with c:
            c.post("/api/workspaces", json={"name": "Blocked"})
            app.state.jobs["job-1"] = {"status": "running", "detail": None, "kind": "add"}
            resp = c.post("/api/workspaces/blocked/activate")
            assert resp.status_code == 409
            app.state.jobs["job-1"]["status"] = "done"
            assert c.post("/api/workspaces/blocked/activate").status_code == 200


class TestDelete:
    def test_delete_non_active(self, isolated_papergraph_dir):
        _app, _bus, c = _make_client()
        with c:
            c.post("/api/workspaces", json={"name": "Doomed"})
            resp = c.delete("/api/workspaces/doomed")
            assert resp.status_code == 200
            assert resp.json() == {
                "removed": True, "active": "main", "switched": False}
            assert not (store.workspaces_root() / "doomed").exists()
            data = c.get("/api/workspaces").json()
            assert data["active"] == "main"
            assert all(w["id"] != "doomed" for w in data["workspaces"])

    def test_delete_active_switches_and_publishes_workspace_changed(
            self, isolated_papergraph_dir):
        _app, bus, c = _make_client()
        with c:
            c.post("/api/workspaces", json={"name": "Proj D"})
            c.post("/api/workspaces/proj-d/activate")
            resp = c.delete("/api/workspaces/proj-d")
            assert resp.status_code == 200
            assert resp.json() == {
                "removed": True, "active": "main", "switched": True}
            # history was cleared on switch, then the delete's event published
            kinds = [type(e).__name__ for e in bus.history]
            assert kinds == ["WorkspaceChanged"]
            assert bus.history[0].workspace_id == "main"
            assert store.papergraph_dir().name == "main"
            assert not (store.workspaces_root() / "proj-d").exists()

    def test_delete_only_workspace_leaves_none_active(
            self, isolated_papergraph_dir):
        _app, _bus, c = _make_client()
        with c:
            resp = c.delete("/api/workspaces/main")
            assert resp.status_code == 200
            assert resp.json() == {
                "removed": True, "active": None, "switched": True}
            data = c.get("/api/workspaces").json()
            assert data["active"] is None
            assert data["workspaces"] == []

    def test_delete_main_while_not_active_allowed(self, isolated_papergraph_dir):
        _app, _bus, c = _make_client()
        with c:
            c.post("/api/workspaces", json={"name": "Other"})
            c.post("/api/workspaces/other/activate")
            resp = c.delete("/api/workspaces/main")
            assert resp.status_code == 200
            assert resp.json() == {
                "removed": True, "active": "other", "switched": False}

    def test_delete_unknown_404(self, isolated_papergraph_dir):
        _app, _bus, c = _make_client()
        with c:
            assert c.delete("/api/workspaces/nope").status_code == 404

    def test_delete_active_with_persistent_log_returns_200(
            self, isolated_papergraph_dir):
        # REGRESSION: after a switched delete the endpoint repoints the event
        # log to the new active's lab_events.jsonl and publishes
        # WorkspaceChanged — if the new active's dir does not exist, the
        # append raises FileNotFoundError and the delete 500s after already
        # committing.
        from research_companion.agents.events import EventLog

        bus = Bus(log=EventLog(store.papergraph_dir() / "lab_events.jsonl"))
        app = create_lab_app(bus)
        with TestClient(app) as c:
            c.post("/api/workspaces", json={"name": "Other"})
            resp = c.delete("/api/workspaces/main")
            assert resp.status_code == 200
            assert resp.json()["switched"] is True
            assert resp.json()["active"] == "other"
            assert (store.workspaces_root() / "other" / "lab_events.jsonl").exists()

    def test_delete_blocked_while_job_running(self, isolated_papergraph_dir):
        app, _bus, c = _make_client()
        with c:
            c.post("/api/workspaces", json={"name": "Busy"})
            app.state.jobs["x"] = {"status": "running"}
            assert c.delete("/api/workspaces/busy").status_code == 409
            app.state.jobs["x"]["status"] = "done"
            assert c.delete("/api/workspaces/busy").status_code == 200


class TestWorkspaceChangedNotReplayed:
    """REGRESSION (0.4.0 flicker loop): workspace_changed is a transient
    "reload now" signal. The SSE endpoint replays history to every fresh
    connection — replaying workspace_changed made every page load reload
    itself, an infinite flicker loop on any store that had ever switched
    research."""

    def test_replay_omits_workspace_changed_but_live_history_keeps_it(
            self, isolated_papergraph_dir):
        import asyncio as _asyncio
        import json as _json

        from research_companion.agents.events import PaperAdded, WorkspaceChanged

        bus = Bus()
        _asyncio.run(bus.publish(WorkspaceChanged(workspace_id="other")))
        _asyncio.run(bus.publish(PaperAdded(paper_id="p1", title="After switch")))
        app = create_lab_app(bus)
        app.state._sse_done = True  # terminate after history replay (test mode)

        with TestClient(app) as c:
            resp = c.get("/api/events")
            events = [
                _json.loads(line[len("data: "):])
                for line in resp.text.splitlines()
                if line.startswith("data: ")
            ]
        kinds = [e.get("event") for e in events]
        assert "workspace_changed" not in kinds, (
            "replaying workspace_changed causes an infinite reload loop")
        assert "paper_added" in kinds  # ordinary history still replays
