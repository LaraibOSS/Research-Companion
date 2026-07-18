"""Characterization tests: the compliance linter degrades cleanly.

- No `compliance` lane in the report -> no compliance section rendered
  (report.py is byte-identical to pre-linter behavior when the lane is absent,
  e.g. `--venue` was never passed).
- A bare `Venue` (all new fields at their defaults) -> every check self-skips
  with zero desk_reject/warning counts, rather than erroring or false-flagging.
"""
from research_companion import report as reportmod


def test_report_has_no_compliance_section_when_lane_absent():
    report = {"paper_id": "p", "title": "T", "lanes": {
        "citation": {"ok": True, "data": {"counts": {"verified": 1}, "references": []}}}}
    html = reportmod.render_report_html(report)
    assert "desk-reject linter" not in html.lower()


def test_all_checks_skip_for_bare_venue():
    from research_companion.compliance import check_compliance
    from research_companion.venues import Venue
    v = Venue(slug="v", name="V", kind="conference", scope="")  # all new fields defaulted
    res = check_compliance(v, fulltext="body", references=None)
    assert res["counts"] == {"desk_reject": 0, "warning": 0}
    assert all(c["status"] == "skipped" for c in res["checks"])
