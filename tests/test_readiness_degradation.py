# tests/test_readiness_degradation.py
"""Characterization test: submission-readiness degrades cleanly.

No source lane (only a non-review lane like `ingest`) -> no `readiness` key
in the report JSON and no "Submission readiness" section in the rendered
HTML. A single clean source lane -> a `ready` verdict with no fabricated
findings for lanes that never ran (those surface only as coverage caveats).
"""
from research_companion import report as reportmod
from research_companion.agents.base import AgentResult
from research_companion.readiness import build_readiness


def test_no_readiness_key_or_section_without_source_lanes():
    results = {"ingest": AgentResult(agent="ingest", ok=True, data={"graph_nodes": 1, "graph_edges": 0})}
    rep = reportmod.build_report_json("local:x", "P", results)
    assert "readiness" not in rep
    html = reportmod.render_report_html(rep)
    assert "Submission readiness" not in html


def test_missing_lanes_never_fabricate_findings():
    # only citation ran, clean -> ready, and absent lanes are coverage caveats not findings
    r = build_readiness({"citation": {"ok": True, "error": "", "data": {"counts": {"verified": 3}}}})
    assert r["verdict"] == "ready"
    assert r["blockers"] == [] and r["warnings"] == []
    assert "novelty" in r["coverage"]["not_run"] and "compliance" in r["coverage"]["not_run"]
