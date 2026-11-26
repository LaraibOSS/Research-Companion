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


def _extract_statsoundness(data: dict) -> list[dict]:
    s = data.get("summary", {}) or {}
    dec = s.get("n_decision_inconsistent", 0)
    if dec:
        return [_item("statsoundness", "warning",
                      f"{dec} reported result(s) are decision-inconsistent "
                      f"(significance flips on recomputation)",
                      "Re-check these statistics against the reported test and df.")]
    n = s.get("n_inconsistent", 0) + s.get("n_impossible_means", 0)
    if n:
        return [_item("statsoundness", "warning", f"{n} statistical inconsistency/ies detected",
                      "Verify reported p-values and means.")]
    return []


def _extract_citation(data: dict) -> list[dict]:
    c = data.get("counts", {}) or {}
    bad = c.get("unverified", 0) + c.get("suspect", 0)
    if bad:
        return [_item("citation", "warning", f"{bad} reference(s) unverified or suspect",
                      "Verify or correct these citations.")]
    return []


def _extract_novelty(data: dict) -> list[dict]:
    c = data.get("counts", {}) or {}
    n = c.get("overlaps", 0) + c.get("anticipated", 0)
    if n:
        return [_item("novelty", "warning",
                      f"{n} claimed contribution(s) overlap or are anticipated by prior work",
                      "Strengthen or reframe the novelty of these contributions.")]
    return []


def _extract_reproducibility(data: dict) -> list[dict]:
    if data.get("level") == "low" or not data.get("has_availability_statement"):
        return [_item("reproducibility", "warning",
                      "Weak reproducibility (low level or no availability statement)",
                      "Add code/data links and an availability statement.")]
    return []


def _extract_ethics(data: dict) -> list[dict]:
    missing = data.get("missing_expected", []) or []
    if missing:
        return [_item("ethics", "warning",
                      f"Missing expected declaration(s): {', '.join(str(m) for m in missing)}",
                      "Add the missing ethics/integrity declarations.")]
    return []


def _extract_venuefit(data: dict) -> list[dict]:
    if data.get("desk_reject_risk") or data.get("fit") in ("weak", "out_of_scope"):
        return [_item("venuefit", "warning",
                      f"Venue fit is {data.get('fit', 'weak')} (desk-reject risk)",
                      "Reconsider the target venue or reframe scope.")]
    return []


def _extract_overlap(data: dict) -> list[dict]:
    n = (data.get("summary", {}) or {}).get("n_passages", 0)
    if n:
        return [_item("overlap", "warning", f"{n} passage(s) near-duplicate another library paper",
                      "Check for self-plagiarism / duplicated text.")]
    return []


# --- Did a lane that ran actually examine anything? ---------------------------
#
# "Ran without finding a problem" and "ran and had nothing to look at" are
# different facts, and only the first supports the word "ready". A lane with no
# entry here always examines the paper's text and so always establishes
# something.

def _examined_compliance(data: dict) -> bool:
    # Every check skipped (unknown venue, no rule for it) is nothing checked.
    return any(c.get("status") in ("ok", "finding") for c in data.get("checks", []) or [])


def _examined_citation(data: dict) -> bool:
    c = data.get("counts", {}) or {}
    return (c.get("verified", 0) + c.get("suspect", 0) + c.get("unverified", 0)) > 0


def _examined_statsoundness(data: dict) -> bool:
    s = data.get("summary", {}) or {}
    return (s.get("n_tests", 0) + s.get("n_means", 0)) > 0


def _examined_novelty(data: dict) -> bool:
    c = data.get("counts", {}) or {}
    return any(c.get(v, 0) for v in ("novel", "incremental", "overlaps", "anticipated"))


def _examined_overlap(data: dict) -> bool:
    # Absent on results from before the field existed: assume compared.
    return (data.get("summary", {}) or {}).get("n_compared", 1) > 0


_EXAMINED = {
    "compliance": (_examined_compliance, "no venue rule could be applied"),
    "citation": (_examined_citation, "no references were found to check"),
    "statsoundness": (_examined_statsoundness, "no statistics were found to check"),
    "novelty": (_examined_novelty, "no contribution could be assessed"),
    "overlap": (_examined_overlap, "no other papers to compare against"),
}


_EXTRACTORS = {
    "compliance": _extract_compliance,
    "statsoundness": _extract_statsoundness,
    "citation": _extract_citation,
    "novelty": _extract_novelty,
    "reproducibility": _extract_reproducibility,
    "ethics": _extract_ethics,
    "venuefit": _extract_venuefit,
    "overlap": _extract_overlap,
}


def _summary(verdict: str, blockers: list, warnings: list, coverage: dict) -> str:
    head = {
        "not_ready": f"Not ready — {len(blockers)} blocker(s) to fix",
        "revise": f"Revise — {len(warnings)} item(s) to review, no hard blockers",
        "ready": "Ready to submit, based on the checks that ran",
        "not_assessed": "Not assessed — the checks that ran had nothing to examine",
    }[verdict]
    caveats = []
    for lane, why in (coverage.get("nothing_checked") or {}).items():
        caveats.append(f"{lane}: {why}")
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
    nothing_checked: dict[str, str] = {}
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
        extractor = _EXTRACTORS.get(name)
        items = extractor(data) if extractor else []
        for item in items:
            (blockers if item["severity"] == "blocker" else warnings).append(item)
        examined, why = _EXAMINED.get(name, (None, ""))
        if not items and examined is not None and not examined(data):
            # It returned, but looked at nothing: zero references parsed, zero
            # statistics found, every venue check skipped. Counting that as a
            # lane that "ran" is what let an empty review say "ready".
            nothing_checked[name] = why
            continue
        ran.append(name)
    if not ran and not nothing_checked:
        return {}
    warnings.sort(key=lambda i: _WARNING_ORDER.get(i["lane"], 99))
    if blockers:
        verdict = "not_ready"
    elif warnings:
        verdict = "revise"
    elif ran:
        verdict = "ready"
    else:
        verdict = "not_assessed"
    coverage = {"ran": ran, "not_run": not_run, "failed": failed,
                "nothing_checked": nothing_checked}
    return {"verdict": verdict, "blockers": blockers, "warnings": warnings,
            "coverage": coverage, "summary": _summary(verdict, blockers, warnings, coverage)}
