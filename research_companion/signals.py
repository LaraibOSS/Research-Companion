"""Epistemic signal carrier — what a check establishes, and what it cannot.

Every automated check in this tool produces a claim about the world, and those
claims are not all the same kind. Collapsing them is how a research tool starts
lying to its user:

* A resolver returning "no record" is a **fact about the resolver**, not proof
  the work does not exist.
* A rule matching is a **heuristic**, never a finding by itself.
* Having *run* a check is not the same as the check's **result**.

The rule this module exists to enforce:

    A check that did not complete is never rendered as clean.

"Not checked", "degraded" (tried, could not finish) and "unknown" all force
``finding = UNRESOLVED``. An outage is not evidence of absence, and equally not
evidence of fabrication. Both readings are wrong, and the honest output is that
we do not know.

``check_status`` and ``finding`` are deliberately independent: knowing a check
ran tells you nothing about what it found, and the two must be stated
separately so a caller cannot infer one from the other.

Prior art: the epistemic-class contract in ARS (`academic-research-skills`,
CC BY-NC 4.0). The idea is theirs; this is an independent implementation — no
ARS code or text is used here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EpistemicClass(str, Enum):
    """What kind of claim a signal is making."""

    #: What a named resolver/list returned at a recorded time. Says nothing
    #: about whether the underlying work is genuine, sound, or retracted.
    DETERMINISTIC_FACT = "deterministic_fact"

    #: A rule or model matched. Advisory only — never a factual finding alone.
    HEURISTIC_ADVISORY = "heuristic_advisory"

    #: A check was run. NOT the result of that check.
    PROCESS_ATTESTATION = "process_attestation"


class CheckStatus(str, Enum):
    """Whether the check actually completed."""

    CHECKED = "checked"          # ran to completion
    NOT_CHECKED = "not_checked"  # never attempted (feature off, no key, skipped)
    DEGRADED = "degraded"        # attempted but could not finish (outage, rate limit)
    UNKNOWN = "unknown"          # state cannot be determined


class Finding(str, Enum):
    """What the check concluded. UNRESOLVED is a real answer, not a gap."""

    SUPPORTED = "supported"          # the positive case was established
    CONTRADICTED = "contradicted"    # the negative case was established
    UNRESOLVED = "unresolved"        # we do not know


#: Statuses that cannot carry a conclusion. Kept as data so the invariant is
#: stated once and reused by both the constructor and any caller that wants to
#: reason about it.
INCOMPLETE_STATUSES = frozenset({
    CheckStatus.NOT_CHECKED,
    CheckStatus.DEGRADED,
    CheckStatus.UNKNOWN,
})


class SignalError(ValueError):
    """Raised when a signal would misrepresent what is actually known."""


@dataclass(frozen=True)
class Signal:
    """One check's outcome, stated so it cannot be misread as more than it is.

    Construct via the helpers below rather than directly — they make the
    common cases impossible to get wrong.
    """

    name: str
    epistemic_class: EpistemicClass
    check_status: CheckStatus
    finding: Finding
    #: Human-readable reason, shown alongside the label. Required when the
    #: finding is UNRESOLVED so the user learns *why* we do not know.
    detail: str = ""
    #: Who/what produced this (resolver name, rule id, model). Provenance is
    #: part of the claim: "Crossref said no" differs from "a regex matched".
    source: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name:
            raise SignalError("signal name is required")
        # THE invariant: an incomplete check may not carry a conclusion.
        if self.check_status in INCOMPLETE_STATUSES and self.finding is not Finding.UNRESOLVED:
            raise SignalError(
                f"{self.name}: check_status={self.check_status.value} cannot carry "
                f"finding={self.finding.value} — a check that did not complete "
                "establishes nothing. Use Finding.UNRESOLVED."
            )
        if self.finding is Finding.UNRESOLVED and not self.detail:
            raise SignalError(
                f"{self.name}: an unresolved finding must say why "
                "(set `detail`), otherwise the user cannot act on it."
            )

    @property
    def is_clean(self) -> bool:
        """True ONLY when a completed check established the positive case.

        Deliberately conservative: every incomplete status is False. Callers
        rendering a tick, a green badge, or the word "verified" must gate on
        this and nothing else.
        """
        return self.check_status is CheckStatus.CHECKED and self.finding is Finding.SUPPORTED

    @property
    def is_unresolved(self) -> bool:
        return self.finding is Finding.UNRESOLVED

    def label(self) -> str:
        """Short display label. Never renders an unresolved signal as clean."""
        if self.is_unresolved:
            return "NOT CHECKED — UNRESOLVED" if self.check_status is CheckStatus.NOT_CHECKED \
                else "COULD NOT VERIFY — UNRESOLVED"
        # Class is checked BEFORE the finding: a heuristic that matched is still
        # only a heuristic, and must never be labelled as a definitive problem.
        if self.epistemic_class is EpistemicClass.HEURISTIC_ADVISORY:
            return ("HEURISTIC MATCH — ADVISORY" if self.finding is Finding.CONTRADICTED
                    else "NO HEURISTIC MATCH — ADVISORY")
        if self.finding is Finding.CONTRADICTED:
            return "PROBLEM FOUND"
        return "VERIFIED"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "epistemic_class": self.epistemic_class.value,
            "check_status": self.check_status.value,
            "finding": self.finding.value,
            "detail": self.detail,
            "source": self.source,
            "evidence": dict(self.evidence),
            "is_clean": self.is_clean,
            "label": self.label(),
        }


# --------------------------------------------------------------------------
# Constructors — the intended entry points.
# --------------------------------------------------------------------------

def resolved(name: str, *, source: str = "", detail: str = "",
             evidence: dict[str, Any] | None = None) -> Signal:
    """A completed lookup that found what it was looking for."""
    return Signal(
        name=name, epistemic_class=EpistemicClass.DETERMINISTIC_FACT,
        check_status=CheckStatus.CHECKED, finding=Finding.SUPPORTED,
        detail=detail, source=source, evidence=evidence or {},
    )


def not_found(name: str, *, source: str, detail: str = "",
              evidence: dict[str, Any] | None = None) -> Signal:
    """A completed lookup that authoritatively found nothing.

    Only correct when every resolver actually answered. If any resolver was
    unreachable, use :func:`could_not_check` — silence is not an answer.
    """
    return Signal(
        name=name, epistemic_class=EpistemicClass.DETERMINISTIC_FACT,
        check_status=CheckStatus.CHECKED, finding=Finding.CONTRADICTED,
        detail=detail or f"{source} returned no matching record",
        source=source, evidence=evidence or {},
    )


def could_not_check(name: str, *, detail: str, source: str = "",
                    evidence: dict[str, Any] | None = None) -> Signal:
    """The check was attempted but could not complete (outage, rate limit).

    This is the signal that stops an outage being reported either as a clean
    result or as a fabrication.
    """
    return Signal(
        name=name, epistemic_class=EpistemicClass.PROCESS_ATTESTATION,
        check_status=CheckStatus.DEGRADED, finding=Finding.UNRESOLVED,
        detail=detail, source=source, evidence=evidence or {},
    )


def not_checked(name: str, *, detail: str, source: str = "") -> Signal:
    """The check never ran — feature off, no key, or deliberately skipped."""
    return Signal(
        name=name, epistemic_class=EpistemicClass.PROCESS_ATTESTATION,
        check_status=CheckStatus.NOT_CHECKED, finding=Finding.UNRESOLVED,
        detail=detail, source=source,
    )


def heuristic(name: str, *, matched: bool, detail: str, source: str = "",
              evidence: dict[str, Any] | None = None) -> Signal:
    """A rule or model matched (or did not). Advisory — never a fact."""
    return Signal(
        name=name, epistemic_class=EpistemicClass.HEURISTIC_ADVISORY,
        check_status=CheckStatus.CHECKED,
        finding=Finding.CONTRADICTED if matched else Finding.SUPPORTED,
        detail=detail, source=source, evidence=evidence or {},
    )


def all_clean(signals: list[Signal]) -> bool:
    """True only if every signal is clean. An empty list is NOT clean —
    nothing was checked, so nothing was established."""
    return bool(signals) and all(s.is_clean for s in signals)
