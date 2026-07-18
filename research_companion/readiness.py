# research_companion/readiness.py
"""Deterministic submission-readiness synthesis over the review lanes.

Reads each SOURCE lane's result and produces one verdict + a prioritized,
cross-lane action list. Pure: no LLM, no network. Only definitive deterministic
findings (compliance desk-rejects) are blockers; everything else is a warning.
Reads whatever lanes ran and reports coverage caveats honestly. The derived
`severity` lane is intentionally NOT read (it would double-count and let
heuristics block).
"""
from __future__ import annotations

# Source lanes the synthesizer knows how to read (NOT the derived `severity` lane).
KNOWN_LANES = ("compliance", "citation", "novelty", "reproducibility",
               "ethics", "statsoundness", "venuefit", "overlap")

# Warning display order (lower = first). Blockers always precede warnings.
_WARNING_ORDER = {
    "statsoundness": 0, "compliance": 1, "citation": 2, "novelty": 3,
    "reproducibility": 4, "ethics": 5, "venuefit": 6, "overlap": 7,
}
_VENUE_LANES = ("venuefit", "compliance")   # absent without --venue
_FAST_LANES = ("novelty",)                  # absent under --fast


def _item(lane: str, severity: str, title: str, action: str) -> dict:
    return {"lane": lane, "severity": severity, "title": title, "action": action}


def _extract_compliance(data: dict) -> list[dict]:
    out = []
    for c in data.get("checks", []):
        if c.get("status") != "finding":
            continue
        sev = "blocker" if c.get("severity") == "desk_reject" else "warning"
        action = ("Fix before submission — this is a desk-reject rule."
                  if sev == "blocker" else "Review this compliance warning.")
        out.append(_item("compliance", sev, c.get("message", ""), action))
    return out


_EXTRACTORS = {
    "compliance": _extract_compliance,
}


def _summary(verdict: str, blockers: list, warnings: list, coverage: dict) -> str:
    head = {
        "not_ready": f"Not ready — {len(blockers)} blocker(s) to fix",
        "revise": f"Revise — {len(warnings)} item(s) to review, no hard blockers",
        "ready": "Ready to submit, based on the checks that ran",
    }[verdict]
    caveats = []
    nr = set(coverage["not_run"])
    if nr & set(_VENUE_LANES):
        caveats.append("venue/compliance checks not run — pass --venue")
    if nr & set(_FAST_LANES):
        caveats.append("novelty lane not run — remove --fast")
    if coverage["failed"]:
        caveats.append(f"lane(s) failed and not reflected: {', '.join(coverage['failed'])}")
    return head + ("; " + "; ".join(caveats) if caveats else "")


def build_readiness(lanes: dict) -> dict:
    """Synthesize a submission-readiness verdict from the review lanes.

    `lanes` maps lane name -> {"ok","error","data"} (build_report_json shape).
    Returns {} when nothing assessable ran (no readiness section rendered)."""
    if not lanes:
        return {}
    blockers: list[dict] = []
    warnings: list[dict] = []
    ran: list[str] = []
    not_run: list[str] = []
    failed: list[str] = []
    for name in KNOWN_LANES:
        entry = lanes.get(name)
        if entry is None:
            not_run.append(name)
            continue
        if not entry.get("ok", False):
            failed.append(name)
            continue
        data = entry.get("data") or {}
        if name == "venuefit" and data.get("skipped"):
            not_run.append(name)
            continue
        ran.append(name)
        extractor = _EXTRACTORS.get(name)
        for item in (extractor(data) if extractor else []):
            (blockers if item["severity"] == "blocker" else warnings).append(item)
    if not ran:
        return {}
    warnings.sort(key=lambda i: _WARNING_ORDER.get(i["lane"], 99))
    verdict = "not_ready" if blockers else ("revise" if warnings else "ready")
    coverage = {"ran": ran, "not_run": not_run, "failed": failed}
    return {"verdict": verdict, "blockers": blockers, "warnings": warnings,
            "coverage": coverage, "summary": _summary(verdict, blockers, warnings, coverage)}
