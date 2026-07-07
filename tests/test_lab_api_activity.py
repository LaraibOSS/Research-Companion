"""Tests for the background-activity lifecycle (v0.5.2): JobStarted/JobFinished
events + GET /api/jobs boot hydration."""
from __future__ import annotations

import time

import pytest

from research_companion import store

_fastapi = pytest.importorskip("fastapi", reason="fastapi required for lab_api tests")
from fastapi.testclient import TestClient  # noqa: E402

from research_companion.agents.bus import Bus  # noqa: E402
from research_companion.lab_api import create_lab_app  # noqa: E402


def _make_client():
    bus = Bus()
    app = create_lab_app(bus)
    return app, bus, TestClient(app)


def _wait(cond, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return True
        time.sleep(0.05)
    return False


def _quiesce(c):
    """(Kept for reference) The original shutdown hang was a REAL bug — Python
    3.10 wait_for cancellation-swallowing in _SeqRecorder.drain — fixed via
    recorder.stop(); tests exit freely now."""
    _wait(lambda: c.get("/api/jobs").json()["jobs"] == [])


class TestJobLifecycleEvents:
    def test_add_job_publishes_started_and_finished(self, isolated_papergraph_dir):
        app, bus, c = _make_client()

        async def slow_add(target, b):
            pass
        app.state.add_paper_override = slow_add

        with c:
            resp = c.post("/api/papers", json={"target": "2106.09685"})
            job_id = resp.json()["job_id"]
            assert _wait(lambda: any(
                type(e).__name__ == "JobFinished" for e in bus.history))

        started = [e for e in bus.history if type(e).__name__ == "JobStarted"]
        finished = [e for e in bus.history if type(e).__name__ == "JobFinished"]
        assert len(started) == 1 and len(finished) == 1
        assert started[0].job_id == job_id
        assert started[0].kind == "add"
        assert started[0].target == "2106.09685"
        assert "2106.09685" in started[0].label
        assert finished[0].job_id == job_id
        assert finished[0].status == "done"

    def test_failed_add_finishes_with_failed_status(self, isolated_papergraph_dir):
        app, bus, c = _make_client()

        async def boom(target, b):
            raise RuntimeError("nope")
        app.state.add_paper_override = boom

        with c:
            c.post("/api/papers", json={"target": "bad-target"})
            assert _wait(lambda: any(
                type(e).__name__ == "JobFinished" for e in bus.history))
        fin = next(e for e in bus.history if type(e).__name__ == "JobFinished")
        assert fin.status == "failed"

    def test_resolve_job_publishes_lifecycle(self, isolated_papergraph_dir):
        # Seed a draft with one title-only ref so resolve has work
        draft = "local:actdraft"
        store.PaperMetadata(paper_id=draft, title="D", authors=["M"],
                            year=2026, added_at="2026-01-01T00:00:00Z").save()
        store.save_text(draft, "Intro.\n\nReferences\n"
                        "[1] A. Vaswani et al. Attention is all you need. 2017.\n"
                        "[2] B. Author. Another cited paper title here. 2020.\n"
                        "[3] C. Author. Third cited paper title here. 2021.\n")
        store.set_draft_paper_id(draft)

        app, bus, c = _make_client()
        app.state.citations_resolver_override = lambda ref: None
        from research_companion.settings import update_settings
        update_settings({"auto_add_citations": False})  # isolate the manual resolve

        with c:
            resp = c.post("/api/draft/citations/resolve")
            assert resp.status_code == 202
            assert _wait(lambda: any(
                type(e).__name__ == "JobFinished" and e.kind == "citations"
                for e in bus.history))
        started = [e for e in bus.history
                   if type(e).__name__ == "JobStarted" and e.kind == "citations"]
        assert started and "eferences" in started[0].label  # "Checking references…"


class TestJobsListEndpoint:
    def test_lists_running_then_empties(self, isolated_papergraph_dir):
        import asyncio as _asyncio

        app, _bus, c = _make_client()

        async def held_add(target, b):
            # Hold the job open briefly — an asyncio.Event set from the test
            # thread would never wake the loop (not thread-safe), so sleep.
            await _asyncio.sleep(0.8)
        app.state.add_paper_override = held_add

        with c:
            c.post("/api/papers", json={"target": "2106.09685"})
            jobs = c.get("/api/jobs").json()["jobs"]
            assert len(jobs) == 1
            assert jobs[0]["kind"] == "add"
            assert jobs[0]["target"] == "2106.09685"
            assert jobs[0]["label"]
            assert _wait(lambda: c.get("/api/jobs").json()["jobs"] == [])

    def test_empty_when_idle(self, isolated_papergraph_dir):
        _app, _bus, c = _make_client()
        with c:
            assert c.get("/api/jobs").json() == {"jobs": []}


class TestEventRoundTrips:
    def test_job_started_finished_kinds(self):
        from research_companion.agents.events import (
            JobFinished,
            JobStarted,
            event_to_dict,
        )
        s = event_to_dict(JobStarted(job_id="job-1", kind="add",
                                     label="Downloading X", target="X"))
        assert s["event"] == "job_started" and s["target"] == "X"
        f = event_to_dict(JobFinished(job_id="job-1", kind="add", status="done"))
        assert f["event"] == "job_finished" and f["status"] == "done"
