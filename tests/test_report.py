"""Tests for the post-run report builder."""
from __future__ import annotations

import json

from research_companion.agents.base import AgentResult
from research_companion.report import (
    _render_readiness,
    _section_citation_polarity,
    _section_compliance,
    _section_taxonomy,
    build_report_json,
    render_report_html,
)


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
            "venue": "iclr", "venue_name": "ICLR", "discipline": "machine_learning",
            "fit": "out_of_scope", "confidence": 0.8, "topic_overlap": 0.1,
            "rationale": "Not a learning-representations paper.",
            "reasons": ["no ML contribution"], "checklists": ["reproducibility statement"],
            "suggested_alternatives": ["CHI"], "desk_reject_risk": True}),
    }
    html_out = render_report_html(build_report_json("local:x", "P", results))
    assert "Venue Fit: ICLR" in html_out
    assert "OUT OF SCOPE" in html_out
    assert "machine learning" in html_out  # discipline shown
    assert "Required checklists:" in html_out
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


def test_render_report_html_shows_ethics_declarations():
    results = {
        "ethics": AgentResult(agent="ethics", ok=True, data={
            "declarations": {"funding": True, "conflict_of_interest": False},
            "present": ["funding"],
            "absent": ["conflict_of_interest"],
            "missing_expected": ["conflict_of_interest"]}),
    }
    html_out = render_report_html(build_report_json("local:x", "P", results))
    assert "Integrity Declarations" in html_out
    assert "funding" in html_out
    assert "Expected but missing" in html_out
    assert "conflict of interest" in html_out


def test_section_citation_polarity_renders_counts_and_evidence():
    data = {"counts": {"contrast": 1, "based_on": 2},
            "citations": [{"cite": "Smith 2019", "polarity": "contrast",
                           "evidence_quote": "unlike Smith we do X", "rationale": "", "verified": True}]}
    html = _section_citation_polarity(data)
    assert "contrast" in html and "based_on" in html
    assert "Smith 2019" in html and "unlike Smith we do X" in html


def test_section_citation_polarity_empty_when_no_data():
    assert _section_citation_polarity({}) == ""


def test_section_taxonomy_renders_nested_list():
    data = {"groups": [{"label": "Graph Retrieval", "shared_terms": ["graph"],
                        "papers": [{"title": "Graph retrieval", "year": 2020, "id": "1"}]}], "count": 1}
    html = _section_taxonomy(data)
    assert "Graph Retrieval" in html and "Graph retrieval" in html and "2020" in html


def test_section_taxonomy_empty_when_no_groups():
    assert _section_taxonomy({"groups": [], "count": 0}) == ""


def test_section_compliance_renders_findings_and_disclaimer():
    data = {"venue": "neurips",
            "checks": [
                {"check": "page_limit", "status": "finding", "severity": "desk_reject",
                 "message": "PDF is 14 pages; NeurIPS limit is 9", "detail": ""},
                {"check": "anonymization", "status": "finding", "severity": "warning",
                 "message": "email near the top", "detail": "a@b.com"}],
            "counts": {"desk_reject": 1, "warning": 1},
            "disclaimer": "verify against the CFP"}
    html = _section_compliance(data)
    assert "14 pages" in html and "email near the top" in html
    assert "verify against the CFP" in html


def test_section_compliance_empty_when_no_checks():
    assert _section_compliance({"checks": [], "counts": {}}) == ""


def test_section_compliance_renders_escaped_detail_for_desk_reject_and_warning():
    data = {"venue": "neurips",
            "checks": [
                {"check": "page_limit", "status": "finding", "severity": "desk_reject",
                 "message": "PDF is 14 pages; NeurIPS limit is 9",
                 "detail": "Counting all PDF pages incl. references/appendix with a "
                           "4-page allowance <caveat>"},
                {"check": "anonymization", "status": "finding", "severity": "warning",
                 "message": "email near the top", "detail": "<leaked@example.com>"}],
            "counts": {"desk_reject": 1, "warning": 1},
            "disclaimer": "verify against the CFP"}
    html = _section_compliance(data)
    # Detail text is present, and any HTML-significant characters in it are escaped.
    assert "4-page allowance" in html
    assert "&lt;caveat&gt;" in html and "<caveat>" not in html
    assert "&lt;leaked@example.com&gt;" in html and "<leaked@example.com>" not in html


def test_section_compliance_no_detail_span_when_detail_absent():
    data = {"checks": [
        {"check": "page_limit", "status": "finding", "severity": "desk_reject",
         "message": "PDF is 14 pages; NeurIPS limit is 9", "detail": ""}],
        "counts": {"desk_reject": 1, "warning": 0}}
    html = _section_compliance(data)
    assert "PDF is 14 pages" in html
    assert "muted" not in html


def test_build_report_json_includes_readiness_when_findings():
    results = {"compliance": AgentResult(agent="compliance", ok=True, data={"checks": [
        {"status": "finding", "severity": "desk_reject", "message": "no limitations section detected", "detail": ""}]})}
    r = build_report_json("local:x", "P", results)
    assert r["readiness"]["verdict"] == "not_ready"


def test_build_report_json_no_readiness_key_when_empty():
    results = {"ingest": AgentResult(agent="ingest", ok=True, data={"graph_nodes": 1, "graph_edges": 0})}
    r = build_report_json("local:x", "P", results)
    assert "readiness" not in r


def test_render_readiness_shows_verdict_blockers_and_caveats():
    r = {"verdict": "not_ready", "blockers": [{"lane": "compliance", "severity": "blocker",
            "title": "no limitations section detected", "action": "Fix before submission."}],
         "warnings": [{"lane": "citation", "severity": "warning", "title": "2 references unverified", "action": "Verify."}],
         "coverage": {"ran": ["compliance", "citation"], "not_run": ["novelty"], "failed": []},
         "summary": "Not ready — 1 blocker(s) to fix; novelty lane not run — remove --fast"}
    html = _render_readiness(r)
    assert "Not ready" in html and "no limitations section detected" in html
    assert "2 references unverified" in html and "novelty lane not run" in html


def test_render_readiness_empty_is_blank():
    assert _render_readiness(None) == "" and _render_readiness({}) == ""


def test_report_html_renders_readiness_before_lanes():
    results = {"compliance": AgentResult(agent="compliance", ok=True, data={"checks": [
        {"status": "finding", "severity": "desk_reject", "message": "no limitations section detected", "detail": ""}]})}
    html = render_report_html(build_report_json("local:x", "P", results))
    assert "Submission readiness" in html
    # readiness heading appears before the compliance lane card heading
    assert html.index("Submission readiness") < html.index("Venue compliance")


def test_overlap_section_labels_paraphrase_findings():
    data = {"findings": [
        {"matched_paper_id": "lib:1", "score": 0.7, "char_start": 0,
         "char_end": 100, "snippet": "lex snip"},
        {"matched_paper_id": "lib:2", "score": 0.9, "char_start": 200,
         "char_end": 300, "snippet": "sem <snip>", "method": "semantic",
         "matched_section_id": "c1"}],
        "summary": {"n_passages": 2, "papers": ["lib:1", "lib:2"],
                    "max_score": 0.9, "text": "2 passage(s) ..."}}
    from research_companion.report import _section_overlap
    html = _section_overlap(data)
    assert "70% overlap with" in html          # method absent -> today's wording
    assert "90% paraphrase with" in html       # semantic labeled
    assert "&lt;snip&gt;" in html              # snippet still escaped
