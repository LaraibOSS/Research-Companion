"""Build self-contained HTML and JSON reports from agent results."""
from __future__ import annotations

import html as html_module
from typing import Any


def build_report_json(
    paper_id: str,
    title: str,
    results: dict[str, Any],
) -> dict:
    """Build a report dict from agent results.

    Args:
        paper_id: Paper identifier
        title: Paper title
        results: dict[agent_name] -> AgentResult

    Returns:
        {"paper_id","title","lanes":{name:{"ok","error","data"}},"generated_by":"papergraph"}
    """
    lanes = {}
    for agent_name, result in results.items():
        lanes[agent_name] = {
            "ok": result.ok,
            "error": result.error if not result.ok else "",
            "data": result.data if result.ok else {},
        }
    return {
        "paper_id": paper_id,
        "title": title,
        "lanes": lanes,
        "generated_by": "papergraph",
    }


def _escape(s: Any) -> str:
    """Escape a value for HTML; convert to string first."""
    return html_module.escape(str(s))


def _section_citation(data: dict) -> str:
    """Render citation lane section."""
    if "counts" not in data or "references" not in data:
        return ""
    counts = data["counts"]
    verified = counts.get("verified", 0)
    unverified = counts.get("unverified", 0)
    suspect = counts.get("suspect", 0)
    refs = data["references"]
    unverified_refs = [r for r in refs if r.get("status") != "verified"]
    html_out = f"""
      <h3>Citation Health</h3>
      <p><strong>Verified:</strong> {verified} · <strong>Suspect:</strong> {suspect} · <strong>Unverified:</strong> {unverified}</p>
"""
    if unverified_refs:
        html_out += "      <p><strong>Unverified references:</strong></p>\n"
        html_out += "      <ul>\n"
        for ref in unverified_refs:
            title = _escape(ref.get("title", ""))
            status = _escape(ref.get("status", ""))
            html_out += f"        <li>{title} [{status}]</li>\n"
        html_out += "      </ul>\n"
    return html_out


def _section_novelty(data: dict) -> str:
    """Render novelty lane section."""
    if "claims" not in data:
        return ""
    claims = data["claims"]
    if not claims:
        return ""
    html_out = """      <h3>Novelty Claims</h3>
      <table border="1" cellpadding="8" style="width: 100%; border-collapse: collapse;">
        <tr style="background-color: #f0f0f0;">
          <th>Text</th>
          <th>Verdict</th>
          <th>Confidence</th>
          <th>Evidence Verified</th>
        </tr>
"""
    for claim in claims:
        text = _escape(claim.get("text", ""))
        verdict = _escape(claim.get("verdict", ""))
        confidence = claim.get("confidence", 0)
        evidence_verified = claim.get("evidence_verified", False)
        verified_badge = "✓" if evidence_verified else "✗"
        html_out += f"""        <tr>
          <td>{text}</td>
          <td>{verdict}</td>
          <td>{confidence:.2f}</td>
          <td>{verified_badge}</td>
        </tr>
"""
    html_out += "      </table>\n"
    return html_out


def _section_confidence(data: dict) -> str:
    """Render confidence lane section."""
    if "claims" not in data:
        return ""
    claims = data["claims"]
    if not claims:
        return ""
    html_out = "      <h3>Confidence Scores</h3>\n"
    for claim in claims:
        text = _escape(claim.get("text", ""))
        score = claim.get("score", 0)
        band = claim.get("band", 0)
        html_out += "      <div style=\"margin: 10px 0; padding: 8px; border-left: 3px solid #0066cc;\">\n"
        html_out += f"        <strong>{score:.3f} ± {band:.3f}</strong> {text}\n"
        html_out += "      </div>\n"
    return html_out


def _section_benchmark(data: dict) -> str:
    """Render benchmark lane section."""
    if "suggestions" not in data:
        return ""
    suggestions = data["suggestions"]
    if not suggestions:
        return ""
    html_out = "      <h3>Suggested Benchmarks</h3>\n"
    html_out += "      <ul>\n"
    for sugg in suggestions:
        name = _escape(sugg.get("name", ""))
        degree = sugg.get("graph_degree", 0)
        mentions = sugg.get("prior_art_mentions", 0)
        html_out += f"        <li>{name} (degree: {degree}, mentions: {mentions})</li>\n"
    html_out += "      </ul>\n"
    return html_out


def _section_rebuttal(data: dict) -> str:
    """Render rebuttal lane section."""
    if "drafts" not in data:
        return ""
    drafts = data["drafts"]
    if not drafts:
        return ""
    html_out = "      <h3>Rebuttal Drafts</h3>\n"
    for draft in drafts:
        concern_id = _escape(draft.get("concern_id", ""))
        verified = draft.get("evidence_status") == "verified"
        verified_badge = "✓ VERIFIED" if verified else "⚠ CHECK"
        html_out += "      <div style=\"margin: 10px 0; padding: 8px; border-left: 3px solid #cc6600;\">\n"
        html_out += f"        <strong>{concern_id}</strong> [{verified_badge}]\n"
        html_out += "      </div>\n"
    return html_out


def _section_priorart(data: dict) -> str:
    """Render priorart lane section."""
    if "papers" not in data or "count" not in data:
        return ""
    count = data["count"]
    return f"      <p><strong>Related papers found:</strong> {count}</p>\n"


def _section_ingest(data: dict) -> str:
    """Render ingest lane section."""
    if "graph_nodes" not in data or "graph_edges" not in data:
        return ""
    nodes = data["graph_nodes"]
    edges = data["graph_edges"]
    return f"      <p><strong>Graph:</strong> {nodes} nodes, {edges} edges</p>\n"


def render_report_html(report: dict) -> str:
    """Render report dict to self-contained HTML.

    Args:
        report: dict from build_report_json

    Returns:
        Self-contained HTML string (no external assets, all CSS inline, ASCII-only source)
    """
    paper_id = _escape(report.get("paper_id", ""))
    title = _escape(report.get("title", ""))
    lanes = report.get("lanes", {})

    # Preferred order for lanes
    preferred_order = ["ingest", "citation", "priorart", "novelty", "confidence", "benchmark", "rebuttal"]
    ordered_lanes = []
    for name in preferred_order:
        if name in lanes:
            ordered_lanes.append((name, lanes[name]))
    # Add any remaining lanes not in preferred order
    for name, lane in lanes.items():
        if name not in preferred_order:
            ordered_lanes.append((name, lane))

    # Build lane cards
    lane_cards = ""
    for name, lane in ordered_lanes:
        ok = lane.get("ok", False)
        status_text = "OK" if ok else "FAILED"
        status_style = "background-color: #e8f5e9; border-left: 4px solid #4caf50;" if ok else "background-color: #ffebee; border-left: 4px solid #f44336;"
        lane_cards += f"""  <div style="{status_style} margin: 16px 0; padding: 12px; border-radius: 4px;">
    <h2 style="margin: 0 0 8px 0; display: inline-block;">{_escape(name)}</h2>
    <span style="float: right; font-weight: bold; color: {'#2e7d32' if ok else '#c62828'};\">{status_text}</span>
    <div style="clear: both;"></div>
"""
        if not ok:
            error = _escape(lane.get("error", ""))
            lane_cards += f"    <p style=\"color: #c62828; margin: 8px 0;\"><strong>Error:</strong> {error}</p>\n"
        else:
            data = lane.get("data", {})
            # Render lane-specific sections based on data shape
            if name == "ingest":
                section = _section_ingest(data)
                if section:
                    lane_cards += section
            elif name == "citation":
                section = _section_citation(data)
                if section:
                    lane_cards += section
            elif name == "priorart":
                section = _section_priorart(data)
                if section:
                    lane_cards += section
            elif name == "novelty":
                section = _section_novelty(data)
                if section:
                    lane_cards += section
            elif name == "confidence":
                section = _section_confidence(data)
                if section:
                    lane_cards += section
            elif name == "benchmark":
                section = _section_benchmark(data)
                if section:
                    lane_cards += section
            elif name == "rebuttal":
                section = _section_rebuttal(data)
                if section:
                    lane_cards += section
        lane_cards += "  </div>\n"

    html = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Report: {title}</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      line-height: 1.6;
      max-width: 1200px;
      margin: 0 auto;
      padding: 20px;
      background-color: #fafafa;
      color: #333;
    }}
    h1 {{
      border-bottom: 2px solid #0066cc;
      padding-bottom: 12px;
      margin-bottom: 24px;
    }}
    h1 small {{
      display: block;
      font-size: 0.6em;
      color: #666;
      font-weight: normal;
      margin-top: 8px;
    }}
    table {{
      font-size: 0.9em;
    }}
    table th {{
      text-align: left;
    }}
    table td {{
      border: 1px solid #ddd;
      padding: 8px;
    }}
    ul {{
      margin: 8px 0;
      padding-left: 24px;
    }}
    li {{
      margin: 4px 0;
    }}
  </style>
</head>
<body>
  <h1>{title}<small>ID: {paper_id}</small></h1>
{lane_cards}</body>
</html>"""
    return html
