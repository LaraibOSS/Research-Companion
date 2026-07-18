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
        {"paper_id","title","lanes":{name:{"ok","error","data"}},"generated_by":"research-companion"}
    """
    lanes = {}
    for agent_name, result in results.items():
        lanes[agent_name] = {
            "ok": result.ok,
            "error": result.error if not result.ok else "",
            "data": result.data if result.ok else {},
        }
    from research_companion.readiness import build_readiness
    report = {
        "paper_id": paper_id,
        "title": title,
        "lanes": lanes,
        "generated_by": "research-companion",
    }
    readiness = build_readiness(lanes)
    if readiness:
        report["readiness"] = readiness
    return report


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
    nudge = data.get("connectors_nudge")
    if nudge:
        html_out += f'<p class="report-nudge muted">{_escape(nudge)}</p>\n'
    return html_out


def _section_citation_polarity(data: dict) -> str:
    """Render the citation-stance lane: counts + the contrast/refutation cites."""
    counts = data.get("counts") or {}
    cites = data.get("citations") or []
    if not counts and not cites:
        return ""
    summary = " · ".join(f"{_escape(k)}: {v}" for k, v in sorted(counts.items()))
    html_out = f"      <h3>Citation Stance</h3>\n      <p>{summary}</p>\n"
    notable = [c for c in cites if c.get("polarity") in ("contrast", "refutation")]
    if notable:
        html_out += "      <p><strong>Contrasts / refutations:</strong></p>\n      <ul>\n"
        for c in notable:
            cite = _escape(c.get("cite", ""))
            pol = _escape(c.get("polarity", ""))
            ev = _escape(c.get("evidence_quote", ""))
            html_out += f'        <li>{cite} [{pol}]: "{ev}"</li>\n'
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
        verified_badge = "OK" if evidence_verified else "X"
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
        html_out += f"        <strong>{score:.3f} +/- {band:.3f}</strong> {text}\n"
        html_out += "      </div>\n"
    return html_out


_SEVERITY_COLORS = {"critical": "#c62828", "major": "#ef6c00", "minor": "#f9a825"}


def _section_severity(data: dict) -> str:
    """Render severity lane: per-tier counts + ranked findings, worst first."""
    findings = data.get("findings")
    if not findings:
        return ""
    counts = data.get("counts", {})
    html_out = "      <h3>Ranked Findings</h3>\n"
    html_out += (
        f"      <p><strong>{counts.get('critical', 0)} critical</strong> &middot; "
        f"{counts.get('major', 0)} major &middot; "
        f"{counts.get('minor', 0)} minor</p>\n"
    )
    for f in findings:
        sev = f.get("severity", "")
        color = _SEVERITY_COLORS.get(sev, "#999")
        title = _escape(f.get("title", ""))
        subject = _escape(f.get("subject", ""))
        html_out += f"      <div style=\"margin: 10px 0; padding: 8px; border-left: 4px solid {color};\">\n"
        html_out += f"        <strong style=\"color: {color};\">[{_escape(sev.upper())}]</strong> {title}\n"
        if subject:
            html_out += f"        <div style=\"color: #666; font-size: 0.9em;\">{subject}</div>\n"
        html_out += "      </div>\n"
    return html_out


_FIT_COLORS = {"strong": "#2e7d32", "moderate": "#f9a825",
               "weak": "#ef6c00", "out_of_scope": "#c62828"}


def _section_venuefit(data: dict) -> str:
    """Render venue-fit lane: fit verdict, overlap, reasons, alternatives."""
    if data.get("skipped") or "fit" not in data:
        return ""
    fit = data.get("fit", "")
    color = _FIT_COLORS.get(fit, "#999")
    name = _escape(data.get("venue_name", data.get("venue", "")))
    discipline = _escape(str(data.get("discipline", "")).replace("_", " "))
    conf = data.get("confidence", 0)
    overlap = data.get("topic_overlap", 0)
    html_out = f"      <h3>Venue Fit: {name}</h3>\n"
    if discipline:
        html_out += f"      <p style=\"color: #666;\">Discipline: {discipline}</p>\n"
    html_out += (
        f"      <p><strong style=\"color: {color};\">{_escape(fit.replace('_', ' ').upper())}</strong> "
        f"(confidence {conf:.2f}, topic overlap {overlap:.2f})</p>\n"
    )
    rationale = _escape(data.get("rationale", ""))
    if rationale:
        html_out += f"      <p>{rationale}</p>\n"
    checklists = data.get("checklists") or []
    if checklists:
        html_out += ("      <p><strong>Required checklists:</strong> "
                     f"{_escape(', '.join(checklists))}</p>\n")
    reasons = data.get("reasons") or []
    if reasons:
        html_out += "      <ul>\n"
        for r in reasons:
            html_out += f"        <li>{_escape(r)}</li>\n"
        html_out += "      </ul>\n"
    alts = data.get("suggested_alternatives") or []
    if alts:
        html_out += ("      <p><strong>Consider instead:</strong> "
                     f"{_escape(', '.join(alts))}</p>\n")
    return html_out


_LEVEL_COLORS = {"high": "#2e7d32", "medium": "#f9a825", "low": "#c62828"}


def _section_compliance(data: dict) -> str:
    """Render venue-compliance lane: desk-reject findings, warnings, skipped checks, disclaimer."""
    checks = data.get("checks") or []
    if not checks:
        return ""
    desk = [c for c in checks if c.get("status") == "finding" and c.get("severity") == "desk_reject"]
    warn = [c for c in checks if c.get("status") == "finding" and c.get("severity") == "warning"]
    skip = [c for c in checks if c.get("status") == "skipped"]
    html_out = "      <h3>Venue compliance (desk-reject linter)</h3>\n"
    if desk:
        html_out += "      <p><strong>Desk-reject risks:</strong></p>\n      <ul>\n"
        for c in desk:
            _line = _escape(c.get("message", ""))
            _det = c.get("detail", "")
            if _det:
                _line += f' <span class="muted">— {_escape(_det)}</span>'
            html_out += f"        <li>{_line}</li>\n"
        html_out += "      </ul>\n"
    if warn:
        html_out += "      <p><strong>Warnings:</strong></p>\n      <ul>\n"
        for c in warn:
            _line = _escape(c.get("message", ""))
            _det = c.get("detail", "")
            if _det:
                _line += f' <span class="muted">— {_escape(_det)}</span>'
            html_out += f"        <li>{_line}</li>\n"
        html_out += "      </ul>\n"
    if skip:
        skipped = ", ".join(_escape(c.get("check", "")) for c in skip)
        html_out += f"      <p class=\"muted\">Not checked: {skipped}</p>\n"
    disc = data.get("disclaimer")
    if disc:
        html_out += f"      <p class=\"muted\"><em>{_escape(disc)}</em></p>\n"
    return html_out


def _section_reproducibility(data: dict) -> str:
    """Render reproducibility lane: level, artifact links, and gaps."""
    if "level" not in data:
        return ""
    level = data.get("level", "")
    color = _LEVEL_COLORS.get(level, "#999")
    code = data.get("code_links", []) or []
    data_links = data.get("data_links", []) or []
    html_out = "      <h3>Reproducibility</h3>\n"
    html_out += (
        f"      <p><strong style=\"color: {color};\">{_escape(level.upper())}</strong> "
        f"&middot; {len(code)} code link(s) &middot; {len(data_links)} data link(s) "
        f"&middot; availability statement: {'yes' if data.get('has_availability_statement') else 'no'}</p>\n"
    )
    checklists = data.get("checklists") or []
    if checklists:
        html_out += (f"      <p><strong>Checklists:</strong> "
                     f"{_escape(', '.join(checklists))}</p>\n")
    missing = data.get("missing") or []
    if missing:
        html_out += "      <p><strong>Gaps:</strong></p>\n      <ul>\n"
        for m in missing:
            html_out += f"        <li>{_escape(m)}</li>\n"
        html_out += "      </ul>\n"
    return html_out


def _section_ethics(data: dict) -> str:
    """Render ethics lane: present declarations + expected-but-missing ones."""
    if "declarations" not in data:
        return ""
    present = data.get("present") or []
    missing = data.get("missing_expected") or []
    html_out = "      <h3>Integrity Declarations</h3>\n"
    if present:
        pretty = ", ".join(p.replace("_", " ") for p in present)
        html_out += f"      <p><strong>Present:</strong> {_escape(pretty)}</p>\n"
    if missing:
        pretty = ", ".join(m.replace("_", " ") for m in missing)
        html_out += ("      <p style=\"color: #ef6c00;\"><strong>Expected but missing:"
                     f"</strong> {_escape(pretty)}</p>\n")
    if not present and not missing:
        html_out += "      <p>All expected declarations present.</p>\n"
    return html_out


def _section_statsoundness(data: dict) -> str:
    """Render statistical-soundness lane: recomputed p-values + GRIM means."""
    if "summary" not in data:
        return ""
    summary = data.get("summary", {})
    findings = data.get("findings", []) or []
    problems = [f for f in findings if f.get("status") not in ("consistent", None)]
    html_out = "      <h3>Statistical Soundness</h3>\n"
    html_out += f"      <p>{_escape(summary.get('text', ''))}</p>\n"
    if problems:
        html_out += "      <ul>\n"
        for f in problems:
            status = str(f.get("status", "")).replace("_", " ")
            if f.get("test_type") == "mean":
                desc = (f"Reported mean {f.get('mean')} with N={f.get('n')} is "
                        f"arithmetically impossible (GRIM)")
            else:
                desc = (f"{f.get('test_type')}: reported p{f.get('p_operator')}"
                        f"{f.get('p_reported')}, recomputed p≈{f.get('recomputed_p')} "
                        f"({status})")
            html_out += f"        <li>{_escape(desc)}</li>\n"
        html_out += "      </ul>\n"
    return html_out


def _section_overlap(data: dict) -> str:
    """Render near-duplicate lane: passages overlapping another library paper."""
    if "summary" not in data:
        return ""
    summary = data.get("summary", {})
    findings = data.get("findings", []) or []
    html_out = "      <h3>Near-duplicate passages</h3>\n"
    html_out += f"      <p>{_escape(summary.get('text', ''))}</p>\n"
    if findings:
        html_out += "      <ul>\n"
        for f in findings[:20]:
            pct = round(float(f.get("score", 0.0)) * 100)
            label = "paraphrase" if f.get("method") == "semantic" else "overlap"
            snippet = _escape(str(f.get("snippet", "")))
            html_out += (f"        <li>{pct}% {label} with "
                         f"{_escape(f.get('matched_paper_id', ''))}: "
                         f"&ldquo;{snippet}&hellip;&rdquo;</li>\n")
        html_out += "      </ul>\n"
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
        verified_badge = "OK VERIFIED" if verified else "! CHECK"
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


def _section_taxonomy(data: dict) -> str:
    """Render the prior-art taxonomy as a nested list (group -> papers)."""
    groups = data.get("groups") or []
    if not groups:
        return ""
    html_out = "      <h3>Prior-art taxonomy</h3>\n      <ul>\n"
    for g in groups:
        label = _escape(g.get("label", ""))
        html_out += f"        <li><strong>{label}</strong>\n          <ul>\n"
        for p in g.get("papers", []):
            title = _escape(p.get("title", ""))
            year = _escape(p.get("year", "") if p.get("year") is not None else "")
            html_out += f"            <li>{title} ({year})</li>\n"
        html_out += "          </ul>\n        </li>\n"
    html_out += "      </ul>\n"
    return html_out


def _section_ingest(data: dict) -> str:
    """Render ingest lane section."""
    if "graph_nodes" not in data or "graph_edges" not in data:
        return ""
    nodes = data["graph_nodes"]
    edges = data["graph_edges"]
    return f"      <p><strong>Graph:</strong> {nodes} nodes, {edges} edges</p>\n"


_VERDICT_LABEL = {"not_ready": "Not ready to submit", "revise": "Revise before submitting",
                  "ready": "Ready to submit"}
_VERDICT_COLOR = {"not_ready": "#c62828", "revise": "#e65100", "ready": "#2e7d32"}


def _render_readiness(readiness: dict | None) -> str:
    """Render the submission-readiness banner (verdict, blockers, warnings)."""
    if not readiness:
        return ""
    verdict = readiness.get("verdict", "revise")
    color = _VERDICT_COLOR.get(verdict, "#e65100")
    label = _VERDICT_LABEL.get(verdict, "Revise before submitting")
    html_out = (f'  <div style="border-left: 6px solid {color}; background:#fafafa; '
                f'margin: 16px 0; padding: 12px;">\n'
                f'    <h2 style="margin:0 0 6px 0; color:{color};">Submission readiness: '
                f'{_escape(label)}</h2>\n'
                f'    <p style="margin:0 0 8px 0; color:#555;">{_escape(readiness.get("summary", ""))}</p>\n')
    blockers = readiness.get("blockers") or []
    if blockers:
        html_out += "    <p><strong>Must fix (desk-reject risks):</strong></p>\n    <ul>\n"
        for b in blockers:
            html_out += (f"      <li>[{_escape(b.get('lane', ''))}] {_escape(b.get('title', ''))} "
                         f"— {_escape(b.get('action', ''))}</li>\n")
        html_out += "    </ul>\n"
    warnings = readiness.get("warnings") or []
    if warnings:
        html_out += "    <p><strong>Should review:</strong></p>\n    <ul>\n"
        for w in warnings:
            html_out += (f"      <li>[{_escape(w.get('lane', ''))}] {_escape(w.get('title', ''))} "
                         f"— {_escape(w.get('action', ''))}</li>\n")
        html_out += "    </ul>\n"
    html_out += "  </div>\n"
    return html_out


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
    preferred_order = ["severity", "venuefit", "compliance", "ingest", "citation", "citation_polarity", "priorart", "taxonomy", "novelty", "confidence", "statsoundness", "reproducibility", "ethics", "overlap", "benchmark", "rebuttal"]
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
            if name == "severity":
                section = _section_severity(data)
                if section:
                    lane_cards += section
            elif name == "venuefit":
                section = _section_venuefit(data)
                if section:
                    lane_cards += section
            elif name == "compliance":
                section = _section_compliance(data)
                if section:
                    lane_cards += section
            elif name == "ingest":
                section = _section_ingest(data)
                if section:
                    lane_cards += section
            elif name == "citation":
                section = _section_citation(data)
                if section:
                    lane_cards += section
            elif name == "citation_polarity":
                section = _section_citation_polarity(data)
                if section:
                    lane_cards += section
            elif name == "priorart":
                section = _section_priorart(data)
                if section:
                    lane_cards += section
            elif name == "taxonomy":
                section = _section_taxonomy(data)
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
            elif name == "statsoundness":
                section = _section_statsoundness(data)
                if section:
                    lane_cards += section
            elif name == "reproducibility":
                section = _section_reproducibility(data)
                if section:
                    lane_cards += section
            elif name == "ethics":
                section = _section_ethics(data)
                if section:
                    lane_cards += section
            elif name == "overlap":
                section = _section_overlap(data)
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

    readiness_html = _render_readiness(report.get("readiness"))

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
{readiness_html}{lane_cards}</body>
</html>"""
    return html
