"""Adapters from each checker's native output to :mod:`research_companion.signals`.

Every deterministic checker grew its own result shape — ``verified/suspect/
unverified``, ``ok/finding/skipped``, findings-plus-summary — so the same idea,
*we could not check this*, is expressed differently in each. A consumer wanting
one honest view of a paper has to learn all of them, and any consumer that
forgets one renders "could not check" as a pass.

These functions translate, they do not replace. Each checker keeps its native
output; this adds the canonical view alongside, exactly as ``AuditResult``
already carries both an ``outcome`` and a ``Signal``.

**Propositions, not verdicts.** ``Signal.name`` states what was tested and
``finding`` states whether it holds, so every name here is phrased such that
``SUPPORTED`` means *no problem found* — ``passage_is_original``, not
``overlap_detected``. Otherwise ``CONTRADICTED`` would mean "good" in one
checker and "bad" in another, and no shared renderer could colour it.

**Coverage is deliberately absent.** Report coverage produces "17 of 24
passages cited", a measurement with a denominator rather than a proposition
that can be supported or contradicted. Forcing it in would mean a permanently
``UNRESOLVED`` finding and a value field that is null for every other signal.
It stays a metric.
"""
from __future__ import annotations

from typing import Any

from research_companion.signals import (
    CatalogueRef,
    CheckStatus,
    DocumentRef,
    EpistemicClass,
    Finding,
    Reason,
    Signal,
    could_not_check,
    not_applicable,
    not_checked,
)

# ---------------------------------------------------------------------------
# refcheck
# ---------------------------------------------------------------------------

#: Wording emitted by validate.py when every resolver was unreachable. An
#: outage is not evidence a reference is missing, and the two must not collapse.
_UNREACHABLE = "no bibliographic source could be reached"


def refcheck_signals(report: Any) -> list[Signal]:
    """Signals for a validated bibliography.

    Refcheck answers **two** questions, which its single status flattens into
    one: does the work exist, and do the cited details match the record? A
    ``suspect`` verdict means the work was found — so ``reference_exists`` is
    SUPPORTED — while ``reference_details_match`` is CONTRADICTED. Reporting
    only the first would hide a real finding; only the second would imply the
    reference is fabricated.
    """
    out: list[Signal] = []
    for ref, verdict in getattr(report, "entries", []) or []:
        title = (getattr(ref, "title", "") or "")[:120]
        reasons = list(getattr(verdict, "reasons", []) or [])
        detail = "; ".join(reasons) if reasons else "matched an authoritative record"
        matched = getattr(verdict, "matched", None) or {}
        evidence_refs: tuple[Any, ...] = ()
        if matched:
            evidence_refs = (CatalogueRef(
                catalogue=str(matched.get("source") or "catalogue"),
                identifier=str(matched.get("doi") or matched.get("arxiv_id") or ""),
                title=str(matched.get("title") or ""),
            ),)

        status = getattr(verdict, "status", "")
        if status == "unverified" and any(_UNREACHABLE in r for r in reasons):
            out.append(could_not_check(
                "reference_exists", detail=detail, source="refcheck",
                reason=Reason.SOURCE_UNAVAILABLE,
                evidence={"title": title},
            ))
            continue

        exists = status in ("verified", "suspect")
        out.append(Signal(
            name="reference_exists",
            epistemic_class=EpistemicClass.DETERMINISTIC_FACT,
            check_status=CheckStatus.CHECKED,
            finding=Finding.SUPPORTED if exists else Finding.CONTRADICTED,
            detail=detail if not exists else "found in an authoritative catalogue",
            source="refcheck", evidence={"title": title},
            evidence_refs=evidence_refs,
        ))
        if exists:
            out.append(Signal(
                name="reference_details_match",
                epistemic_class=EpistemicClass.DETERMINISTIC_FACT,
                check_status=CheckStatus.CHECKED,
                finding=Finding.CONTRADICTED if status == "suspect" else Finding.SUPPORTED,
                detail=detail,
                source="refcheck", evidence={"title": title},
                evidence_refs=evidence_refs,
            ))
    return out


# ---------------------------------------------------------------------------
# statcheck / GRIM
# ---------------------------------------------------------------------------

_ADVERSE_STAT = {"inconsistent", "decision_inconsistent", "impossible_mean"}


def statcheck_signals(result: dict, *, paper_id: str = "") -> list[Signal]:
    """Signals for recomputed statistics.

    Nothing found is the interesting case. ``n_tests == 0`` cannot distinguish
    "this paper reports no such statistics" from "it reports them in a form we
    do not parse", so it is NOT_APPLICABLE with a detail that says exactly
    that. What it must never be is silence that reads as a pass.
    """
    findings = list((result or {}).get("findings", []) or [])
    summary = (result or {}).get("summary", {}) or {}
    subject = DocumentRef(paper_id=paper_id) if paper_id else None

    if not findings and not summary.get("n_tests"):
        return [not_applicable(
            "statistics_internally_consistent",
            reason=Reason.NOT_RELEVANT,
            detail=("No parseable statistics were found. This may mean the paper "
                    "reports none, or reports them in a form this checker does "
                    "not parse — it is not a clean bill of health."),
            source="statcheck",
        )]

    out: list[Signal] = []
    for f in findings:
        status = f.get("status", "")
        is_grim = status == "impossible_mean" or f.get("kind") == "grim"
        name = "reported_means_are_possible" if is_grim else "statistics_internally_consistent"
        adverse = status in _ADVERSE_STAT
        out.append(Signal(
            name=name,
            epistemic_class=EpistemicClass.DETERMINISTIC_FACT,
            check_status=CheckStatus.CHECKED,
            finding=Finding.CONTRADICTED if adverse else Finding.SUPPORTED,
            detail=str(f.get("message") or f.get("raw") or status),
            source="statcheck", subject=subject, evidence=dict(f),
        ))
    return out


# ---------------------------------------------------------------------------
# venue compliance
# ---------------------------------------------------------------------------

#: A skipped compliance check is one of two very different facts, and the
#: native output spells both "skipped": the venue has no such rule (nothing is
#: outstanding), or we could not run it (something is). Phrases that mean the
#: former; anything else is treated as the latter, because assuming a check was
#: irrelevant is the more dangerous mistake.
_RULE_ABSENT_PHRASES = (
    "no page limit configured",
    "no abstract word limit",
    "no such requirement",
    "not required by this venue",
)


def compliance_signals(result: dict, *, venue_slug: str = "") -> list[Signal]:
    """Signals for a venue-compliance run."""
    out: list[Signal] = []
    for c in (result or {}).get("checks", []) or []:
        check = str(c.get("check") or "check")
        name = f"complies_with_{check}"
        message = str(c.get("message") or "")
        status = c.get("status")

        if status == "skipped":
            if any(p in message.lower() for p in _RULE_ABSENT_PHRASES):
                out.append(not_applicable(
                    name, reason=Reason.NO_SUCH_REQUIREMENT,
                    detail=message or "this venue has no such requirement",
                    source="compliance",
                ))
            else:
                # Could not run — an outstanding task, not an irrelevant one.
                out.append(not_checked(
                    name, detail=message or "could not be checked",
                    source="compliance", reason=Reason.NOT_CONFIGURED,
                ))
            continue

        out.append(Signal(
            name=name,
            epistemic_class=EpistemicClass.DETERMINISTIC_FACT,
            check_status=CheckStatus.CHECKED,
            finding=Finding.CONTRADICTED if status == "finding" else Finding.SUPPORTED,
            detail=message,
            source="compliance",
            evidence={"severity": c.get("severity"), "detail": c.get("detail", "")},
        ))
    return out


# ---------------------------------------------------------------------------
# self-overlap
# ---------------------------------------------------------------------------

def overlap_signals(result: dict, *, paper_id: str = "") -> list[Signal]:
    """Signals for near-duplicate detection against the rest of the library.

    An empty library produces "no other library papers to compare against",
    which currently reads like a clean result. It is NOT_APPLICABLE: there was
    nothing to compare with, so nothing was established.
    """
    findings = list((result or {}).get("findings", []) or [])
    summary = (result or {}).get("summary", {}) or {}
    subject = DocumentRef(paper_id=paper_id or str(result.get("paper_id") or ""))

    if not summary.get("papers") and not findings:
        return [not_applicable(
            "passage_is_original",
            reason=Reason.NOT_RELEVANT,
            detail=(str(summary.get("text"))
                    or "no other papers in this library to compare against"),
            source="overlap",
        )]

    if not findings:
        return [Signal(
            name="passage_is_original",
            epistemic_class=EpistemicClass.HEURISTIC_ADVISORY,
            check_status=CheckStatus.CHECKED, finding=Finding.SUPPORTED,
            detail="no near-duplicate passages found in this library",
            source="overlap", subject=subject,
        )]

    out: list[Signal] = []
    for f in findings:
        other = str(f.get("paper_id") or f.get("other_paper_id") or "")
        evidence_refs = (DocumentRef(paper_id=other),) if other else ()
        out.append(Signal(
            name="passage_is_original",
            epistemic_class=EpistemicClass.HEURISTIC_ADVISORY,
            check_status=CheckStatus.CHECKED, finding=Finding.CONTRADICTED,
            detail=str(f.get("message")
                       or f"near-duplicate passage found in {other or 'another paper'}"),
            source="overlap", subject=subject, evidence_refs=evidence_refs,
            evidence={"score": f.get("score")},
        ))
    return out
