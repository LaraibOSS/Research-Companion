"""Claim-audit benchmark: does the audit flag claims a passage does not
support, and how often does it accuse a claim the passage does support?

Each case is run through the real :func:`research_companion.claim_audit.audit_claim`
-- prompt, response parsing, the minimum-passage rule, the fail-closed paths --
with the passage served as the anchored source text. Only the model call is
injectable: tests use a fake, a live run uses the configured provider (one
model call per case; ``--limit`` caps the spend).

Input (JSONL, one object per line)::

    {"claim": "...", "passage": "...", "label": "supported" | "not_supported",
     "type": "<optional category>"}

SciFact (Wadden et al., 2020) converts to this format: each claim with a
cited abstract becomes one case, the passage being the rationale sentences
(or the abstract), SUPPORT -> ``supported``, CONTRADICT -> ``not_supported``
(type ``contradict``), and NOINFO -> ``not_supported`` (type ``noinfo``),
since a passage that says nothing about a claim does not support it. No
converter ships and SciFact has not been run here.

Scoring, with the same honesty rules as the reference benchmark:

* detection rate = ``not_supported`` cases judged NOT_SUPPORTED, over
  ``not_supported`` cases the audit reached a verdict on;
* false-accusation rate = ``supported`` cases judged NOT_SUPPORTED, over
  ``supported`` cases the audit reached a verdict on;
* an inconclusive audit (model error, "unclear", passage too short) is
  counted separately and excluded from both rates -- it is a failure to check,
  not a pass or a miss.

Run::

    python -m research_companion.eval.claim_audit_bench FILE [--limit N]
        [--provider P] [--model M] [--json]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from research_companion.eval._common import BenchFormatError, fmt_rate, rate, read_jsonl

LABELS = ("supported", "not_supported")
EXPECTED = ('each line a JSON object: {"claim": "...", "passage": "...", '
            '"label": "supported" | "not_supported", "type": "<optional category>"}')


@dataclass(frozen=True)
class ClaimCase:
    line: int
    claim: str
    passage: str
    label: str
    type: str


def _case_from_row(no: int, obj: dict) -> ClaimCase:
    claim, passage = obj.get("claim"), obj.get("passage")
    if not isinstance(claim, str) or not claim.strip():
        raise ValueError('missing "claim" (a non-empty string)')
    if not isinstance(passage, str) or not passage.strip():
        raise ValueError('missing "passage" (a non-empty string)')
    label = str(obj.get("label") or "").strip().lower()
    if label not in LABELS:
        raise ValueError(f'"label" must be "supported" or "not_supported", got {obj.get("label")!r}')
    etype = str(obj.get("type") or "").strip() or label
    return ClaimCase(no, claim.strip(), passage, label, etype)


def load_cases(path: str | Path) -> tuple[list[ClaimCase], list[dict]]:
    """Cases and skipped rows. A file with no usable row raises, naming the
    expected fields."""
    cases: list[ClaimCase] = []
    skipped: list[dict] = []
    for no, obj, err in read_jsonl(path):
        if obj is None:
            skipped.append({"line": no, "error": err})
            continue
        try:
            cases.append(_case_from_row(no, obj))
        except ValueError as exc:
            skipped.append({"line": no, "error": str(exc)})
    if not cases:
        first = "; ".join(f"line {s['line']}: {s['error']}" for s in skipped[:3])
        raise BenchFormatError(f"No usable rows in {path}" + (f" ({first})" if first else "")
                               + f". Expected {EXPECTED}.")
    return cases, skipped


def run_cases(cases: list[ClaimCase], llm: Callable[[str], str] | None) -> list[dict]:
    """Audit each case through the real ``audit_claim``."""
    from research_companion.claim_audit import audit_claim
    from research_companion.locator import Locator, LocatorKind

    rows = []
    for c in cases:
        paper_id = f"bench:{c.line}"
        locator = Locator(paper_id=paper_id, kind=LocatorKind.QUOTE, char_start=0,
                          char_end=len(c.passage), quote=c.passage)
        result = audit_claim(c.claim, locator, load_text=lambda _pid, p=c.passage: p, llm=llm)
        conclusive = not result.is_inconclusive
        if not conclusive:
            outcome = "inconclusive"
        elif c.label == "not_supported":
            outcome = "detected" if result.is_adverse else "missed"
        else:
            outcome = "falsely_accused" if result.is_adverse else "accepted"
        rows.append({"line": c.line, "label": c.label, "type": c.type, "claim": c.claim,
                     "verdict": result.outcome.value, "conclusive": conclusive,
                     "outcome": outcome, "reason": result.reason})
    return rows


def summarize(rows: list[dict]) -> dict:
    from research_companion.claim_audit import AuditOutcome

    verdicts = [o.value for o in AuditOutcome]
    confusion = {lbl: {v: 0 for v in verdicts} for lbl in LABELS}
    for r in rows:
        confusion[r["label"]][r["verdict"]] += 1

    def side(label: str) -> dict:
        lr = [r for r in rows if r["label"] == label]
        conclusive = [r for r in lr if r["conclusive"]]
        flagged = sum(1 for r in conclusive if r["verdict"] == AuditOutcome.NOT_SUPPORTED.value)
        return {"total": len(lr), "conclusive": len(conclusive),
                "inconclusive": len(lr) - len(conclusive), "judged_not_supported": flagged}

    ns, sup = side("not_supported"), side("supported")
    ns["detection_rate"] = rate(ns["judged_not_supported"], ns["conclusive"])
    sup["false_accusation_rate"] = rate(sup["judged_not_supported"], sup["conclusive"])

    groups: dict[tuple[str, str], dict] = {}
    for r in rows:
        g = groups.setdefault((r["type"], r["label"]), {
            "type": r["type"], "label": r["label"], "total": 0, "conclusive": 0,
            "inconclusive": 0, "judged_not_supported": 0})
        g["total"] += 1
        if not r["conclusive"]:
            g["inconclusive"] += 1
            continue
        g["conclusive"] += 1
        g["judged_not_supported"] += r["verdict"] == AuditOutcome.NOT_SUPPORTED.value
    per_type = []
    for (_t, lbl), g in sorted(groups.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        g["rate_name"] = "detection_rate" if lbl == "not_supported" else "false_accusation_rate"
        g["rate"] = rate(g["judged_not_supported"], g["conclusive"])
        per_type.append(g)

    return {
        "cases_run": len(rows),
        "confusion_matrix": confusion,
        "not_supported": ns,
        "supported": sup,
        "inconclusive": {"total": ns["inconclusive"] + sup["inconclusive"],
                         "supported": sup["inconclusive"],
                         "not_supported": ns["inconclusive"]},
        "per_type": per_type,
        "definitions": {
            "detection_rate": "not_supported cases judged NOT_SUPPORTED, over not_supported "
                              "cases with a conclusive verdict",
            "false_accusation_rate": "supported cases judged NOT_SUPPORTED, over supported "
                                     "cases with a conclusive verdict",
            "inconclusive": "the audit could not conclude (model error, unclear, passage too "
                            "short); excluded from both rates",
        },
    }


def evaluate(path: str | Path, llm: Callable[[str], str] | None, *,
             limit: int | None = None) -> dict:
    cases, skipped = load_cases(path)
    run = cases[:limit] if limit else cases
    rows = run_cases(run, llm)
    return {"file": str(path), "limit": limit, "usable_rows": len(cases),
            "skipped": skipped, "metrics": summarize(rows), "rows": rows}


def format_summary(result: dict) -> str:
    m = result["metrics"]
    ns, sup, inc = m["not_supported"], m["supported"], m["inconclusive"]
    out = [f"Claim-audit benchmark: {result['file']}",
           f"Cases run: {m['cases_run']} of {result['usable_rows']} usable"
           + (f" (--limit {result['limit']})" if result.get("limit") else ""),
           f"Rows skipped as malformed: {len(result['skipped'])}"]
    for s in result["skipped"][:10]:
        out.append(f"  line {s['line']}: {s['error']}")
    out += [f"Inconclusive (audit could not conclude): {inc['total']} "
            f"({inc['supported']} supported, {inc['not_supported']} not_supported) "
            "-- excluded from both rates",
            "",
            f"Not-supported claims: {ns['total']}, {ns['conclusive']} conclusive",
            f"  Detection rate:        {fmt_rate(ns['judged_not_supported'], ns['conclusive'])}",
            f"Supported claims: {sup['total']}, {sup['conclusive']} conclusive",
            f"  False-accusation rate: {fmt_rate(sup['judged_not_supported'], sup['conclusive'])}",
            "",
            "Per type"]
    for g in m["per_type"]:
        name = "detection" if g["label"] == "not_supported" else "false accusation"
        out.append(f"  {g['type'][:30]:<31}{g['label']:<14}{name} "
                   f"{fmt_rate(g['judged_not_supported'], g['conclusive'])}"
                   + (f", {g['inconclusive']} inconclusive" if g["inconclusive"] else ""))
    return "\n".join(out)


def _resolve_llm(provider: str | None, model: str | None) -> Callable[[str], str]:
    """The live model, JSON mode, as the Lab's claim-audit endpoint uses."""
    from research_companion import llm

    return llm.text_callable(provider, model, json_mode=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m research_companion.eval.claim_audit_bench",
        description="Measure the claim audit on a labelled claim/passage file.")
    parser.add_argument("file", help="labelled JSONL file")
    parser.add_argument("--limit", type=int, default=None, metavar="N",
                        help="run only the first N usable cases (one model call each)")
    parser.add_argument("--provider", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--json", action="store_true", help="print the full result as JSON")
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")
    try:
        llm = _resolve_llm(args.provider, args.model)
        result = evaluate(args.file, llm, limit=args.limit)
    except BenchFormatError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False) if args.json
          else format_summary(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
