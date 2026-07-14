"""Tests for the post-run report builder."""
from __future__ import annotations

import json

from research_companion.agents.base import AgentResult
from research_companion.report import build_report_json, render_report_html


def _results():
    return {
        "ingest": AgentResult(agent="ingest", ok=True, data={"graph_nodes": 3, "graph_edges": 2}),
        "citation": AgentResult(agent="citation", ok=True, data={
            "counts": {"verified": 1, "suspect": 0, "unverified": 1},
            "references": [{"title": "Real Paper", "status": "verified", "reasons": []},
                            {"title": "Fake <Paper>", "status": "unverified",
                             "reasons": ["No matching record found in authoritative sources"]}]}),
        "novelty": AgentResult(agent="novelty", ok=False, error="LLM unavailable"),
    }


def test_build_report_json_includes_failed_lanes():
    r = build_report_json("local:x", "My Paper", _results())
    assert r["lanes"]["novelty"]["ok"] is False
    assert "LLM unavailable" in r["lanes"]["novelty"]["error"]
    assert r["lanes"]["citation"]["data"]["counts"]["verified"] == 1
    json.dumps(r)


def test_render_report_html_escapes_and_marks_failures():
    html_out = render_report_html(build_report_json("local:x", "My <Paper>", _results()))
    assert "&lt;Paper&gt;" in html_out and "<Paper>" not in html_out.replace("&lt;Paper&gt;", "")
    assert "FAILED" in html_out and "LLM unavailable" in html_out
    assert "Fake &lt;Paper&gt;" in html_out
    assert html_out.lstrip().lower().startswith("<!doctype html")


def test_render_report_html_shows_ranked_severity_findings():
    results = {
        "severity": AgentResult(agent="severity", ok=True, data={
            "counts": {"critical": 1, "major": 1, "minor": 0},
            "findings": [
                {"severity": "critical", "category": "unsupported_claim",
                 "title": "Claimed contribution has no verifiable evidence",
                 "subject": "Our method beats SOTA", "evidence": {}, "rank": 0},
                {"severity": "major", "category": "unverified_reference",
                 "title": "Reference could not be found in any database",
                 "subject": "Ghost et al.", "evidence": {}, "rank": 1},
            ]}),
    }
    html_out = render_report_html(build_report_json("local:x", "P", results))
    assert "Ranked Findings" in html_out
    assert "1 critical" in html_out
    assert "[CRITICAL]" in html_out and "[MAJOR]" in html_out
    # Severity section renders before the (absent here) other lanes.
    assert "Our method beats SOTA" in html_out


def test_render_report_html_shows_venue_fit():
    results = {
        "venuefit": AgentResult(agent="venuefit", ok=True, data={
            "venue": "iclr", "venue_name": "ICLR", "fit": "out_of_scope",
            "confidence": 0.8, "topic_overlap": 0.1,
            "rationale": "Not a learning-representations paper.",
            "reasons": ["no ML contribution"],
            "suggested_alternatives": ["CHI"], "desk_reject_risk": True}),
    }
    html_out = render_report_html(build_report_json("local:x", "P", results))
    assert "Venue Fit: ICLR" in html_out
    assert "OUT OF SCOPE" in html_out
    assert "Consider instead:" in html_out and "CHI" in html_out


def test_render_report_html_hides_skipped_venue_fit():
    results = {
        "venuefit": AgentResult(agent="venuefit", ok=True,
                                data={"skipped": True, "reason": "no target venue specified"}),
    }
    html_out = render_report_html(build_report_json("local:x", "P", results))
    assert "Venue Fit" not in html_out


def test_render_report_html_shows_reproducibility():
    results = {
        "reproducibility": AgentResult(agent="reproducibility", ok=True, data={
            "code_links": ["https://github.com/a/b"], "data_links": [],
            "has_availability_statement": True,
            "signals": {"hyperparameters": True}, "checklists": ["model_card"],
            "level": "medium",
            "missing": ["No public data/artifact repository link found"]}),
    }
    html_out = render_report_html(build_report_json("local:x", "P", results))
    assert "Reproducibility" in html_out
    assert "MEDIUM" in html_out
    assert "model_card" in html_out
    assert "No public data/artifact repository link found" in html_out
