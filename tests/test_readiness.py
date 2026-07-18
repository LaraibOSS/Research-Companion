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


def _warnings(r):
    return [(w["lane"], w["title"]) for w in r["warnings"]]


def test_statsoundness_decision_inconsistent_warns():
    r = build_readiness({"statsoundness": _lane({"summary": {"n_decision_inconsistent": 2, "n_inconsistent": 3}})})
    assert r["verdict"] == "revise"
    assert any(lane == "statsoundness" and "decision-inconsistent" in title for lane, title in _warnings(r))


def test_citation_unverified_warns():
    r = build_readiness({"citation": _lane({"counts": {"verified": 5, "suspect": 1, "unverified": 2}})})
    assert any(lane == "citation" for lane, _ in _warnings(r))


def test_novelty_overlap_warns():
    r = build_readiness({"novelty": _lane({"counts": {"novel": 1, "overlaps": 2, "anticipated": 1}})})
    assert any(lane == "novelty" for lane, _ in _warnings(r))


def test_reproducibility_low_warns():
    r = build_readiness({"reproducibility": _lane({"level": "low", "has_availability_statement": False})})
    assert any(lane == "reproducibility" for lane, _ in _warnings(r))


def test_ethics_missing_warns():
    r = build_readiness({"ethics": _lane({"present": [], "missing_expected": ["funding", "conflict of interest"]})})
    assert any(lane == "ethics" for lane, _ in _warnings(r))


def test_venuefit_desk_reject_risk_warns_but_skipped_is_not_run():
    r = build_readiness({"venuefit": _lane({"fit": "out_of_scope", "desk_reject_risk": True})})
    assert any(lane == "venuefit" for lane, _ in _warnings(r))
    r2 = build_readiness({"venuefit": _lane({"skipped": True, "reason": "no venue"}),
                          "citation": _lane({"counts": {}})})
    assert "venuefit" in r2["coverage"]["not_run"] and not any(lane == "venuefit" for lane, _ in _warnings(r2))


def test_overlap_warns():
    r = build_readiness({"overlap": _lane({"summary": {"n_passages": 3, "papers": ["x"]}})})
    assert any(lane == "overlap" for lane, _ in _warnings(r))


def test_warnings_ordered_by_lane_priority():
    lanes = {"overlap": _lane({"summary": {"n_passages": 1}}),
             "statsoundness": _lane({"summary": {"n_decision_inconsistent": 1}}),
             "citation": _lane({"counts": {"unverified": 1}})}
    order = [w["lane"] for w in build_readiness(lanes)["warnings"]]
    assert order == ["statsoundness", "citation", "overlap"]
