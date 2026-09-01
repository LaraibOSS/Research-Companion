"""The arm/disarm surface."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from research_companion.agents.bus import Bus
from research_companion.lab_api import create_lab_app


@pytest.fixture
def lab_client():
    """Mirrors _make_client in tests/test_lab_api.py. Workspace isolation is
    autouse via conftest.isolated_papergraph_dir."""
    return TestClient(create_lab_app(Bus()))


def test_arming_reports_the_window(lab_client):
    r = lab_client.post("/api/acquire/arm",
                        json={"paper_ids": ["doi:10.1145/1"], "ttl": 600})
    assert r.status_code == 200
    assert r.json()["armed"] is True
    assert 0 < r.json()["seconds_left"] <= 600


def test_status_reports_disarmed_before_anything_is_armed(lab_client):
    assert lab_client.get("/api/acquire/status").json()["armed"] is False


def test_disarming_works(lab_client):
    lab_client.post("/api/acquire/arm", json={"paper_ids": ["doi:10.1145/1"]})
    lab_client.post("/api/acquire/disarm")
    assert lab_client.get("/api/acquire/status").json()["armed"] is False


def test_arming_twice_extends_rather_than_replaces(lab_client):
    lab_client.post("/api/acquire/arm", json={"paper_ids": ["a"]})
    r = lab_client.post("/api/acquire/arm", json={"paper_ids": ["b"]})
    assert set(r.json()["paper_ids"]) == {"a", "b"}


def test_the_ttl_is_capped(lab_client):
    """A caller must not be able to arm an unbounded watcher."""
    r = lab_client.post("/api/acquire/arm", json={"paper_ids": ["a"], "ttl": 999999})
    assert r.json()["seconds_left"] <= 3600


def test_the_queue_lists_only_papers_a_person_can_help_with(lab_client):
    from research_companion import store
    store.record_failure("doi:blocked", {
        "stage": "add", "error": "x", "paper_id": "doi:blocked",
        "acquisition": {"obtained": False, "reason": "blocked_by_host",
                        "human_can_help": True, "attempts": [], "source": None}})
    store.record_failure("doi:transient", {
        "stage": "add", "error": "x", "paper_id": "doi:transient",
        "acquisition": {"obtained": False, "reason": "source_unavailable",
                        "human_can_help": False, "attempts": [], "source": None}})
    ids = [p["paper_id"] for p in lab_client.get("/api/acquire/queue").json()["papers"]]
    assert "doi:blocked" in ids
    assert "doi:transient" not in ids, "the machine owns transient failures"
