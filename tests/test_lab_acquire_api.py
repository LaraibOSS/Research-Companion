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


def test_a_non_positive_ttl_reports_disarmed_honestly(lab_client):
    """Nothing clamps a ttl of 0 or below to a minimum -- the watcher is
    genuinely already expired, and the response says so (no hardcoded
    armed: true) rather than contradicting the very next status check."""
    r = lab_client.post("/api/acquire/arm", json={"paper_ids": ["a"], "ttl": 0})
    assert r.json()["armed"] is False
    assert r.json()["seconds_left"] == 0
    assert lab_client.get("/api/acquire/status").json()["armed"] is False

    r = lab_client.post("/api/acquire/arm", json={"paper_ids": ["a"], "ttl": -5})
    assert r.json()["armed"] is False


def test_queue_entries_carry_the_same_headline_and_detail_as_the_summary(lab_client):
    """GET /api/acquire/queue must not return a payload that looks like the
    paper summary's acquisition dict but is missing the copy -- it reuses
    the same enrichment _build_paper_summary uses."""
    from research_companion import store
    from research_companion.acquire import Acquisition
    from research_companion.acquire.copy import reason_detail, reason_headline

    acq_dict = {"obtained": False, "reason": "blocked_by_host",
               "human_can_help": True, "attempts": [], "source": None}
    store.record_failure("doi:blocked-copy", {
        "stage": "add", "error": "x", "paper_id": "doi:blocked-copy",
        "acquisition": acq_dict})

    papers = lab_client.get("/api/acquire/queue").json()["papers"]
    entry = next(p for p in papers if p["paper_id"] == "doi:blocked-copy")

    acq_obj = Acquisition.from_dict(acq_dict)
    assert entry["acquisition"]["headline"] == reason_headline(acq_obj)
    assert entry["acquisition"]["detail"] == reason_detail(acq_obj)


def test_enrich_acquisition_falls_back_to_the_raw_dict_on_malformed_data():
    """A stored acquisition dict that no longer parses (e.g. an unrecognized
    reason value from an older/foreign record) must not 500 GET /api/papers
    or GET /api/acquire/queue -- it is served as-is, without headline/detail."""
    from research_companion.lab_api import _enrich_acquisition

    malformed = {"obtained": False, "reason": "not-a-real-reason",
                "human_can_help": True, "attempts": [], "source": None}
    assert _enrich_acquisition(malformed) == malformed
    assert _enrich_acquisition(None) is None


def test_arm_hands_the_watcher_the_same_queue_the_queue_endpoint_reports(lab_client):
    """The `queued` list ArmedWatcher.arm() receives is not a separate,
    possibly-diverging computation from GET /api/acquire/queue -- it is the
    same _acquirable_failures() call."""
    from research_companion import store

    store.record_failure("doi:blocked-arm", {
        "stage": "add", "error": "x", "paper_id": "doi:blocked-arm",
        "acquisition": {"obtained": False, "reason": "blocked_by_host",
                        "human_can_help": True, "attempts": [], "source": None}})

    watcher = lab_client.app.state.watcher
    captured = {}
    original_arm = watcher.arm

    def spy(paper_ids, ttl=600, queued=()):
        captured["queued"] = list(queued)
        return original_arm(paper_ids, ttl=ttl, queued=queued)

    watcher.arm = spy
    lab_client.post("/api/acquire/arm", json={"paper_ids": ["x"]})

    queue_ids = {p["paper_id"] for p in lab_client.get("/api/acquire/queue").json()["papers"]}
    armed_ids = {q["paper_id"] for q in captured["queued"]}
    assert queue_ids == armed_ids
    assert "doi:blocked-arm" in armed_ids
