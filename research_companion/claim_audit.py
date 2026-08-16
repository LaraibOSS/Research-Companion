"""Claim-level citation audit — does the cited source actually say it?

Existing checks answer two easier questions: does the reference **exist**
(``refcheck``), and does a quoted string appear **verbatim** in the source
(``rebuttal.verify``). Neither catches the failure that matters most: a *real*
citation attached to a claim the source never makes. Zhao et al. (arXiv
2605.07723), auditing 111M references, class existence-checking as among the
easiest hallucination-detection problems and the unsupported-claim variant as
the more prevalent, harder one.

**Design stance: minimise false accusations, not misses.** HALLMARK (arXiv
2607.18360) found that for citation verification the false-positive rate — not
recall — decides whether a tool is usable, because at a ~2% base rate a noisy
checker's warnings are mostly wrong and users learn to ignore all of them. So
every uncertain path here resolves to *unverifiable* or *unclear*, never to an
accusation:

============  ==========================================================
outcome       when
============  ==========================================================
SUPPORTED     passage retrieved, model judged it supports the claim
NOT_SUPPORTED passage retrieved, model judged it does not — the only
              adverse verdict, and the model is instructed to avoid it
              unless clear
UNVERIFIABLE  the passage could not be retrieved or judged (no text, fetch
              failure, model error, or the model said "unclear")
ANCHORLESS    the citation carries no locator, so nothing could be checked
NOT_CHECKED   the audit did not run (switched off, or no model configured)
============  ==========================================================

The last three are **not** failures of the citation — they are failures to
check it, and are reported as such. Opt-in and advisory: this module never
blocks output.

Prior art: the claim-audit stage in ARS (`academic-research-skills`,
CC BY-NC 4.0). Independent implementation; no ARS code or text is used.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from research_companion import signals
from research_companion.locator import Locator, resolve

#: Passages shorter than this cannot settle anything — a few words of context
#: is not evidence either way, so we decline rather than guess.
MIN_PASSAGE_CHARS = 40


class AuditOutcome(str, Enum):
    SUPPORTED = "supported"
    NOT_SUPPORTED = "not_supported"
    UNVERIFIABLE = "unverifiable"
    ANCHORLESS = "anchorless"
    NOT_CHECKED = "not_checked"


#: Outcomes that say nothing about the citation's correctness.
INCONCLUSIVE = frozenset({
    AuditOutcome.UNVERIFIABLE,
    AuditOutcome.ANCHORLESS,
    AuditOutcome.NOT_CHECKED,
})


@dataclass(frozen=True)
class AuditResult:
    outcome: AuditOutcome
    reason: str
    claim: str = ""
    passage: str = ""
    signal: signals.Signal | None = None

    @property
    def is_adverse(self) -> bool:
        """True only for the one outcome that criticises the citation."""
        return self.outcome is AuditOutcome.NOT_SUPPORTED

    @property
    def is_inconclusive(self) -> bool:
        return self.outcome in INCONCLUSIVE

    def to_dict(self) -> dict:
        return {
            "outcome": self.outcome.value,
            "reason": self.reason,
            "passage": self.passage,
            "is_adverse": self.is_adverse,
            "is_inconclusive": self.is_inconclusive,
            "signal": self.signal.to_dict() if self.signal else None,
        }


def _result(outcome: AuditOutcome, reason: str, *, claim: str = "",
            passage: str = "") -> AuditResult:
    """Build a result whose signal cannot misrepresent what was established."""
    name = "claim_supported"
    if outcome is AuditOutcome.SUPPORTED:
        sig = signals.resolved(name, source="claim_audit", detail=reason)
    elif outcome is AuditOutcome.NOT_SUPPORTED:
        # A model judgement is a heuristic, never a deterministic fact — the
        # label must say so even when the verdict is adverse.
        sig = signals.heuristic(name, matched=True, detail=reason, source="claim_audit")
    elif outcome is AuditOutcome.NOT_CHECKED:
        sig = signals.not_checked(name, detail=reason, source="claim_audit")
    else:  # UNVERIFIABLE / ANCHORLESS
        sig = signals.could_not_check(name, detail=reason, source="claim_audit")
    return AuditResult(outcome=outcome, reason=reason, claim=claim,
                       passage=passage, signal=sig)


def audit_claim(
    claim: str,
    locator: Locator | None,
    *,
    load_text: Callable[[str], str | None],
    llm: Callable[[str], str] | None = None,
) -> AuditResult:
    """Judge whether the passage a citation points at supports *claim*.

    ``load_text`` maps a paper id to its stored text (the seam tests inject).
    Never raises: every failure becomes an inconclusive outcome with a reason.
    """
    from research_companion.prompts import format_claim_audit_prompt

    claim = (claim or "").strip()
    if not claim:
        return _result(AuditOutcome.NOT_CHECKED, "No claim text to check.")

    if locator is None or not locator.is_anchored:
        return _result(
            AuditOutcome.ANCHORLESS,
            "This citation has no locator, so the source passage could not be "
            "retrieved. Not a finding about the citation itself.",
            claim=claim,
        )

    if llm is None:
        return _result(AuditOutcome.NOT_CHECKED,
                       "Claim auditing is switched off or no model is configured.",
                       claim=claim)

    try:
        fulltext = load_text(locator.paper_id) or ""
    except Exception as exc:  # noqa: BLE001 — a load failure is not a bad citation
        return _result(AuditOutcome.UNVERIFIABLE,
                       f"Could not load the source text ({exc}).", claim=claim)

    passage = resolve(locator, fulltext)
    if len(passage.strip()) < MIN_PASSAGE_CHARS:
        return _result(
            AuditOutcome.UNVERIFIABLE,
            "The anchored passage is too short to establish anything either way.",
            claim=claim, passage=passage,
        )

    prompt = format_claim_audit_prompt(claim=claim, passage=passage)
    try:
        from research_companion.extract import _strip_code_fences

        raw = llm(prompt)
        data = json.loads(_strip_code_fences(raw)) if isinstance(raw, str) else raw
        verdict = str((data or {}).get("verdict", "")).strip().lower()
        reason = str((data or {}).get("reason", "")).strip()
    except Exception as exc:  # noqa: BLE001 — a model failure is not a bad citation
        return _result(AuditOutcome.UNVERIFIABLE,
                       f"The audit could not be completed ({exc}).",
                       claim=claim, passage=passage)

    if verdict == "supported":
        return _result(AuditOutcome.SUPPORTED,
                       reason or "The passage supports this claim.",
                       claim=claim, passage=passage)
    if verdict == "not_supported":
        return _result(
            AuditOutcome.NOT_SUPPORTED,
            reason or "The passage does not establish this claim.",
            claim=claim, passage=passage,
        )
    # "unclear", an unrecognised verdict, or a blank response — all mean the
    # audit did not settle it. Never upgrade that into an accusation.
    return _result(
        AuditOutcome.UNVERIFIABLE,
        reason or "The model could not tell from this passage alone.",
        claim=claim, passage=passage,
    )


def summarize(results: list[AuditResult]) -> dict:
    """Counts for a batch, kept honest: `checked` counts only conclusive
    audits, so an inconclusive run never inflates how much was verified."""
    counts = {o.value: 0 for o in AuditOutcome}
    for r in results:
        counts[r.outcome.value] += 1
    conclusive = counts[AuditOutcome.SUPPORTED.value] + counts[AuditOutcome.NOT_SUPPORTED.value]
    return {
        "counts": counts,
        "total": len(results),
        "checked": conclusive,
        "inconclusive": len(results) - conclusive,
        "adverse": counts[AuditOutcome.NOT_SUPPORTED.value],
    }


# ---------------------------------------------------------------------------
# Runners — audit a whole artifact, one claim at a time
#
# Each returns the same shape: the artifact's own items annotated with an
# `audit` block, plus a summary. Nothing is mutated in place, and a failure on
# one item never aborts the batch (one unreachable source must not blank the
# whole report).
# ---------------------------------------------------------------------------

def _locator_from_citation(cit: dict) -> Locator | None:
    """Build a locator from a stored citation dict.

    Report citations already carry paper/section/char offsets; alignment
    evidence carries a serialized locator. Anything without a usable range
    becomes anchorless rather than a fabricated anchor.
    """
    from research_companion.locator import LocatorKind

    if not isinstance(cit, dict):
        return None
    # alignment evidence: a serialized Locator
    raw = cit.get("locator")
    if isinstance(raw, dict) and raw.get("paper_id"):
        try:
            return Locator(
                paper_id=str(raw["paper_id"]),
                kind=LocatorKind(raw.get("kind", "none")),
                section_id=raw.get("section_id"),
                char_start=raw.get("char_start"),
                char_end=raw.get("char_end"),
                quote=raw.get("quote", "") or "",
            )
        except (ValueError, KeyError):
            return None
    # report citation: paper + section + offsets
    paper_id = str(cit.get("paper_id") or "")
    if not paper_id:
        return None
    start, end = cit.get("char_start"), cit.get("char_end")
    if isinstance(start, int) and isinstance(end, int) and end > start:
        return Locator(paper_id=paper_id, kind=LocatorKind.SECTION,
                       section_id=cit.get("section_id") or None,
                       char_start=start, char_end=end)
    from research_companion.locator import anchorless
    return anchorless(paper_id)


def audit_report(report: dict, *, load_text, llm=None) -> dict:
    """Audit each report answer against the sources it cites.

    The claim under test is the answer text; each citation is checked
    independently, so a single unsupported source does not condemn the answer.
    """
    out_sections = []
    all_results: list[AuditResult] = []
    for sec in (report or {}).get("sections", []) or []:
        if not isinstance(sec, dict):
            continue
        claim = str(sec.get("answer") or "").strip()
        audited = []
        for cit in sec.get("citations", []) or []:
            result = audit_claim(claim, _locator_from_citation(cit),
                                 load_text=load_text, llm=llm)
            all_results.append(result)
            audited.append({**cit, "audit": result.to_dict()})
        out_sections.append({**sec, "citations": audited})
    return {"sections": out_sections, "summary": summarize(all_results)}


def audit_alignment(alignment: dict, *, load_text, llm=None) -> dict:
    """Audit each piece of alignment evidence against its own quoted passage.

    The claim under test is the alignment's rationale — the assertion the tool
    made about the paper — checked against the passage it cited for it.
    """
    out_sections = []
    all_results: list[AuditResult] = []
    for sec in (alignment or {}).get("sections", []) or []:
        if not isinstance(sec, dict):
            continue
        claim = str(sec.get("rationale") or "").strip()
        audited = []
        for ev in sec.get("evidence", []) or []:
            result = audit_claim(claim, _locator_from_citation(ev),
                                 load_text=load_text, llm=llm)
            all_results.append(result)
            audited.append({**ev, "audit": result.to_dict()})
        out_sections.append({**sec, "evidence": audited})
    return {"sections": out_sections, "summary": summarize(all_results)}
