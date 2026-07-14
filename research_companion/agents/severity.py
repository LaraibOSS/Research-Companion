"""SeverityAgent: rank the review's findings by how badly they threaten acceptance.

The pipeline already surfaces individual signals — novelty verdicts, unverified
evidence, citation health, per-claim confidence — but leaves them unranked, so an
author cannot tell which problem to fix first (OpenJudge Criticality-Verification
pattern). ``rank_findings`` is a pure, deterministic classifier over the existing
lane outputs; ``SeverityAgent`` is the thin blackboard wrapper around it.

Tiers (worst first): ``critical`` > ``major`` > ``minor``.
"""
from __future__ import annotations

from research_companion.agents import events
from research_companion.agents.base import Agent, AgentContext, AgentResult

# Lower number = more severe (used as the primary sort key).
SEVERITY_RANK = {"critical": 0, "major": 1, "minor": 2}

# Confidence bands (ConfidenceAgent scores are in [0, 1]).
_LOW_CONF = 0.4
_MED_CONF = 0.6

# Novelty verdicts that mean the contribution is not actually new.
_OVERLAP_VERDICTS = {"anticipated", "overlaps"}


def _finding(severity: str, category: str, title: str, subject: str, evidence: dict) -> dict:
    return {
        "severity": severity,
        "category": category,
        "title": title,
        "subject": subject,
        "evidence": evidence,
    }


def rank_findings(
    *,
    novelty: dict | None = None,
    citation: dict | None = None,
    confidence: dict | None = None,
) -> list[dict]:
    """Classify and rank review findings by severity.

    Args accept the raw agent result ``data`` dicts (any may be None/empty):
      * novelty:    {"claims": [{text, verdict, evidence_verified, ...}]}
      * citation:   {"counts": {...}, "references": [{title, status, reasons}]}
      * confidence: {"claims": [{text, score, band, ...}]}

    Returns a list of finding dicts, most severe first, each with an assigned
    integer ``rank``. Distinct problems on the same claim are reported separately
    (e.g. an unsupported *and* unoriginal claim yields two findings).
    """
    novelty = novelty or {}
    citation = citation or {}
    confidence = confidence or {}

    findings: list[dict] = []

    # --- Novelty: unsupported and/or unoriginal contributions ----------------
    for claim in novelty.get("claims", []):
        text = str(claim.get("text", ""))
        verdict = str(claim.get("verdict", "novel"))
        verified = bool(claim.get("evidence_verified"))

        if not verified:
            # Unsupported claim; worse when the contribution is also not novel.
            sev = "critical" if verdict in _OVERLAP_VERDICTS else "major"
            findings.append(_finding(
                sev, "unsupported_claim",
                "Claimed contribution has no verifiable evidence in the paper",
                text, {"verdict": verdict}))

        if verdict == "anticipated":
            findings.append(_finding(
                "major", "not_novel",
                "Contribution appears fully anticipated by prior work",
                text, {"verdict": verdict}))
        elif verdict == "overlaps":
            findings.append(_finding(
                "major", "not_novel",
                "Contribution substantially overlaps prior work",
                text, {"verdict": verdict}))
        elif verdict == "incremental":
            findings.append(_finding(
                "minor", "not_novel",
                "Contribution is only incremental over prior work",
                text, {"verdict": verdict}))

    # --- Confidence: low overall confidence per claim ------------------------
    for card in confidence.get("claims", []):
        score = float(card.get("score", 1.0))
        text = str(card.get("text", ""))
        if score < _LOW_CONF:
            findings.append(_finding(
                "major", "low_confidence",
                f"Low overall confidence in this claim ({score:.2f})",
                text, {"score": round(score, 3)}))
        elif score < _MED_CONF:
            findings.append(_finding(
                "minor", "low_confidence",
                f"Moderate confidence in this claim ({score:.2f})",
                text, {"score": round(score, 3)}))

    # --- Citations: unverifiable / mismatched references ---------------------
    for ref in citation.get("references", []):
        status = str(ref.get("status", ""))
        title = str(ref.get("title", ""))
        reasons = ref.get("reasons", [])
        if status == "unverified":
            findings.append(_finding(
                "major", "unverified_reference",
                "Reference could not be found in any database (possible fabrication)",
                title, {"reasons": reasons}))
        elif status == "suspect":
            findings.append(_finding(
                "minor", "suspect_reference",
                "Reference metadata does not match the database record",
                title, {"reasons": reasons}))

    findings.sort(key=lambda f: (
        SEVERITY_RANK.get(f["severity"], 99), f["category"], f["title"]))
    for i, f in enumerate(findings):
        f["rank"] = i
    return findings


def summarize(findings: list[dict]) -> dict[str, int]:
    """Count findings per severity tier (missing tiers reported as 0)."""
    counts = {tier: 0 for tier in SEVERITY_RANK}
    for f in findings:
        sev = f.get("severity", "")
        if sev in counts:
            counts[sev] += 1
    return counts


class SeverityAgent(Agent):
    name = "severity"
    role = "Ranks all findings by severity so authors fix what matters first."
    depends_on = ("citation", "novelty", "confidence")

    async def run(self, ctx: AgentContext) -> AgentResult:
        findings = rank_findings(
            novelty=ctx.data.get("novelty"),
            citation=ctx.data.get("citation"),
            confidence=ctx.data.get("confidence"),
        )
        counts = summarize(findings)
        for f in findings:
            await ctx.bus.publish(events.Finding(
                agent=self.name, kind="ranked_finding",
                summary=f"[{f['severity']}] {f['title']}: {f['subject'][:60]}",
                data=f,
            ))
        await ctx.bus.publish(events.Finding(
            agent=self.name, kind="severity_report",
            summary=(f"{counts['critical']} critical · {counts['major']} major · "
                     f"{counts['minor']} minor"),
            data={"counts": counts},
        ))
        return AgentResult(agent=self.name, ok=True,
                           data={"findings": findings, "counts": counts})
