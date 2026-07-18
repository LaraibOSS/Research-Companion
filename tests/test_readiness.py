# tests/test_readiness.py
from research_companion.readiness import KNOWN_LANES, build_readiness


def _lane(data, ok=True):
    return {"ok": ok, "error": "" if ok else "boom", "data": data if ok else {}}


def test_empty_lanes_returns_empty():
    assert build_readiness({}) == {}


def test_nothing_known_ran_returns_empty():
    # only a non-source lane present -> nothing to assess -> {}
    assert build_readiness({"ingest": _lane({"graph_nodes": 1})}) == {}


def test_compliance_desk_reject_is_blocker_not_ready():
    lanes = {"compliance": _lane({"checks": [
        {"status": "finding", "severity": "desk_reject", "message": "no limitations section detected", "detail": ""}]})}
    r = build_readiness(lanes)
    assert r["verdict"] == "not_ready"
    assert len(r["blockers"]) == 1 and r["blockers"][0]["lane"] == "compliance"
    assert r["warnings"] == []


def test_compliance_warning_is_revise():
    lanes = {"compliance": _lane({"checks": [
        {"status": "finding", "severity": "warning", "message": "email near the top", "detail": "a@b.com"}]})}
    r = build_readiness(lanes)
    assert r["verdict"] == "revise" and len(r["warnings"]) == 1 and r["blockers"] == []


def test_clean_lane_is_ready():
    lanes = {"compliance": _lane({"checks": [{"status": "ok", "severity": None, "message": "fine", "detail": ""}]})}
    r = build_readiness(lanes)
    assert r["verdict"] == "ready" and r["blockers"] == [] and r["warnings"] == []


def test_coverage_caveats_and_failed_lane():
    lanes = {"compliance": _lane({"checks": []}),
             "citation": _lane({}, ok=False)}   # citation failed
    r = build_readiness(lanes)
    assert "compliance" in r["coverage"]["ran"]
    assert "citation" in r["coverage"]["failed"]
    # venue/novelty not present -> caveats surfaced
    assert "not run" in r["summary"]
    assert set(KNOWN_LANES) >= {"compliance", "citation", "novelty"}
