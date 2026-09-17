"""A failed add must leave a trace.

_add_paper_task recorded the job status in memory and the reducer discarded
it, so once the toast faded a failed add was invisible: no library entry, no
failure record, nothing to retry. This is why none of the acquisition problem
was diagnosable from the UI.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from research_companion.agents.bus import Bus
from research_companion.lab_api import create_lab_app


@pytest.fixture
def lab_client():
    """Mirrors _make_client in tests/test_lab_api.py. Workspace isolation is
    autouse via conftest.isolated_papergraph_dir.

    Entered as a context manager (unlike _make_client's bare TestClient(app)):
    TestClient only keeps one persistent event-loop portal open across calls
    while inside its own `with` block (see starlette.testclient.TestClient.
    _portal_factory) -- without it, each request gets its own throwaway
    portal that is torn down the instant that request's response is sent,
    so the add job's asyncio.create_task(_run()) background work (the
    entire point of these tests) never gets to actually run before its loop
    is killed and /api/jobs would show it "running" forever."""
    with TestClient(create_lab_app(Bus())) as c:
        yield c


def test_a_failed_add_is_recorded_in_failed_json(lab_client):
    from research_companion import store
    r = lab_client.post("/api/papers", json={"target": "10.9999/definitely-not-real"})
    assert r.status_code in (200, 202)
    _wait_for_jobs(lab_client)
    failures = store.list_failures()
    assert any("10.9999/definitely-not-real" in k for k in failures)


def test_the_record_carries_the_acquisition_reason(lab_client):
    from research_companion import store
    lab_client.post("/api/papers", json={"target": "10.9999/definitely-not-real"})
    _wait_for_jobs(lab_client)
    info = next(iter(store.list_failures().values()))
    assert "acquisition" in info
    assert info["acquisition"]["reason"]


def test_existing_failure_keys_are_untouched(lab_client):
    """Additive: every current reader of failed.json must keep working."""
    from research_companion import store
    lab_client.post("/api/papers", json={"target": "10.9999/definitely-not-real"})
    _wait_for_jobs(lab_client)
    info = next(iter(store.list_failures().values()))
    for key in ("stage", "error", "at"):
        assert key in info


def _wait_for_jobs(client, timeout=30.0):
    import time
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        jobs = client.get("/api/jobs").json()
        # GET /api/jobs returns {"jobs": [...]} with only currently-running
        # jobs listed at all -- an empty list means every job is done, so
        # this must fall back to `jobs` only when the "jobs" key is truly
        # absent (`jobs.get("jobs") or jobs` would wrongly fall back to the
        # whole {"jobs": []} dict once the list empties, and iterating that
        # dict's string keys blows up on `.get`).
        running = [j for j in jobs.get("jobs", jobs) if j.get("status") == "running"]
        if not running:
            return
        time.sleep(0.2)
    raise AssertionError("jobs did not finish")
