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
