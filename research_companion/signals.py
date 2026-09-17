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

    CHECKED = "checked"          # ran to completion and produced a conclusion
    NOT_CHECKED = "not_checked"  # never attempted (feature off, no key, skipped)
    DEGRADED = "degraded"        # attempted, could not produce a valid conclusion
    NOT_APPLICABLE = "not_applicable"  # does not conceptually apply to this artifact
    UNKNOWN = "unknown"          # state cannot be reconstructed (deserialisation only)


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
    CheckStatus.NOT_APPLICABLE,
    CheckStatus.UNKNOWN,
})

#: Statuses that cost the reader effort. NOT_APPLICABLE is deliberately absent:
#: a check that cannot apply to this artifact is not an outstanding task, and
#: putting it in a "needs review" pile would defeat the point of the status.
NEEDS_ATTENTION_STATUSES = frozenset({
    CheckStatus.NOT_CHECKED,
    CheckStatus.DEGRADED,
    CheckStatus.UNKNOWN,
})


class Reason(str, Enum):
    """WHY a check did not conclude — kept separate from the status.

    Status is the epistemic state the UI reasons about; reason is operational
    diagnostics. Folding these together grows CheckStatus into PARSE_FAILED,
    DOWNLOAD_FAILED, NO_TEXT, TIMEOUT... until it is no longer a model of
    anything. Free text cannot be grouped or counted; this can.
    """

    # DEGRADED — attempted, could not finish
    SOURCE_UNAVAILABLE = "source_unavailable"    # outage, rate limit, network
    PARSE_FAILED = "parse_failed"                # unreadable input
    NO_ANCHOR = "no_anchor"                      # nothing locatable to check against
    NO_TEXT = "no_text"                          # nothing extractable from the artifact
    MODEL_ERROR = "model_error"                  # the model call failed or was unusable
    AMBIGUOUS = "ambiguous"                      # ran, could not decide

    # NOT_CHECKED — never attempted
    USER_DISABLED = "user_disabled"              # switched off in settings
    NOT_CONFIGURED = "not_configured"            # no key, no provider
    SKIPPED = "skipped"                          # deliberately not run this pass

    # NOT_APPLICABLE — meaningless for this artifact
    STATISTIC_TYPE_UNSUPPORTED = "statistic_type_unsupported"   # e.g. GRIM on ML results
    NO_SUCH_REQUIREMENT = "no_such_requirement"                 # venue has no such rule
    NOT_RELEVANT = "not_relevant"                               # check does not fit


# --------------------------------------------------------------------------
# Provenance — what was checked, and what it was checked against.
#
# Once every checker emits Signals, evidence stops being "a passage in a paper":
# refcheck cites a catalogue record, novelty cites a query and its results,
# compliance cites a venue rule at a stated version, and overlap cites TWO
# document locations. A single `locator` field cannot carry that, so evidence
# is a small union.
#
# The subject (what was checked) is modelled separately from the evidence (what
# it was checked against). Collapsing them loses the audit trail: "bibliography
# entry 17" and "CrossRef 10.xxxx/xxxx" are not the same fact.
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class DocumentRef:
    """A location inside a document. Wraps locator.py rather than replacing it.

    `locator` holds a serialised research_companion.locator.Locator when one is
    available; signals.py deliberately does not import locator to keep this
    module dependency-free and importable anywhere.
    """

    paper_id: str
    section_id: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    quote: str = ""

    kind = "document"

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "paper_id": self.paper_id,
                "section_id": self.section_id, "char_start": self.char_start,
                "char_end": self.char_end, "quote": self.quote}


@dataclass(frozen=True)
class CatalogueRef:
    """A record in an authoritative bibliographic catalogue."""

    catalogue: str                      # crossref | openalex | arxiv | europepmc
    identifier: str = ""                # doi, arxiv id, pmid
    title: str = ""
    url: str = ""

    kind = "catalogue"

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "catalogue": self.catalogue,
                "identifier": self.identifier, "title": self.title, "url": self.url}


@dataclass(frozen=True)
class VenueRuleRef:
    """A venue requirement, at the version it was checked against.

    A deterministic check is only as trustworthy as the vintage of its rule, so
    the rule version travels with the finding rather than living in a config
    file the reader never sees.
    """

    venue_slug: str
    rule_id: str
    rules_version: str = ""
    source: str = ""                    # official CFP, author kit, ...

    kind = "venue_rule"

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "venue_slug": self.venue_slug,
                "rule_id": self.rule_id, "rules_version": self.rules_version,
                "source": self.source}


@dataclass(frozen=True)
class QueryRef:
    """A search that was actually run.

    Novelty results change with how a contribution is turned into queries, so
    the query strings are part of the evidence, not just the databases.
    """

    query: str
    sources: tuple[str, ...] = ()
    retrieved_at: str = ""              # ISO-8601
    n_results: int | None = None

    kind = "query"

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "query": self.query,
                "sources": list(self.sources), "retrieved_at": self.retrieved_at,
                "n_results": self.n_results}


#: Anything that can stand as a subject or as evidence.
EvidenceRef = DocumentRef | CatalogueRef | VenueRuleRef | QueryRef


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
    #: WHICH CHECKER produced this — not which document the evidence came from.
    #: (Historic name; the evidence source is `evidence_refs`.) Provenance is
    #: part of the claim: "Crossref said no" differs from "a regex matched".
    source: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    #: Why the check did not conclude. Only meaningful on an incomplete status;
    #: structured so failures can be grouped and counted, unlike `detail`.
    reason: Reason | None = None

    #: What was checked (a claim, a bibliography entry, a passage).
    subject: EvidenceRef | None = None
    #: What it was checked against. A tuple because overlap cites two locations.
    evidence_refs: tuple[EvidenceRef, ...] = ()

    #: Reproducibility for HEURISTIC_ADVISORY signals: a model judgement is only
    #: re-checkable if you know what produced it. Deterministic checks may leave
    #: these empty.
    checker_version: str = ""
    prompt_sha: str = ""
    #: ISO-8601. Never auto-filled — an implicit timestamp makes signals
    #: non-comparable and tests non-deterministic.
    checked_at: str = ""

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
        # A completed check has no failure reason. Allowing one invites
        # "CHECKED + PARSE_FAILED", which is two states at once.
        if self.reason is not None and self.check_status is CheckStatus.CHECKED:
            raise SignalError(
                f"{self.name}: check_status=checked cannot carry "
                f"reason={self.reason.value} — a completed check did not fail."
            )
        # NOT_APPLICABLE without a reason is unreadable: the whole point is to
        # say why the check does not apply to THIS artifact.
        if self.check_status is CheckStatus.NOT_APPLICABLE and self.reason is None:
            raise SignalError(
                f"{self.name}: not_applicable must carry a Reason saying why "
                "the check does not apply here."
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

    @property
    def is_adverse(self) -> bool:
        """True only when a completed check established the negative case.

        The counterpart to is_clean, and the only thing that should ever render
        as a problem. Everything incomplete is False: a check that could not
        run has not found anything.
        """
        return (self.check_status is CheckStatus.CHECKED
                and self.finding is Finding.CONTRADICTED)

    @property
    def needs_attention(self) -> bool:
        """Does this cost the reader effort?

        Adverse findings do. So do checks that were requested and could not
        finish. NOT_APPLICABLE does not — nothing is outstanding, which is the
        entire reason that status exists.
        """
        return self.is_adverse or self.check_status in NEEDS_ATTENTION_STATUSES

    def label(self) -> str:
        """Short display label. Never renders an unresolved signal as clean."""
        if self.check_status is CheckStatus.NOT_APPLICABLE:
            # Not a failure and not an outstanding task — this check has no
            # meaning for this artifact, so it must read as neither.
            return "NOT APPLICABLE"
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
            "reason": self.reason.value if self.reason else None,
            "subject": self.subject.to_dict() if self.subject else None,
            "evidence_refs": [r.to_dict() for r in self.evidence_refs],
            "checker_version": self.checker_version,
            "prompt_sha": self.prompt_sha,
            "checked_at": self.checked_at,
            "is_clean": self.is_clean,
            "is_adverse": self.is_adverse,
            "needs_attention": self.needs_attention,
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
                    reason: Reason | None = None,
                    evidence: dict[str, Any] | None = None) -> Signal:
    """The check was attempted but could not complete (outage, rate limit).

    This is the signal that stops an outage being reported either as a clean
    result or as a fabrication.

    Note this is DEGRADED, not NOT_CHECKED: the check was requested and failed
    on a missing prerequisite. A missing anchor belongs here, not in
    :func:`not_checked`.
    """
    return Signal(
        name=name, epistemic_class=EpistemicClass.PROCESS_ATTESTATION,
        check_status=CheckStatus.DEGRADED, finding=Finding.UNRESOLVED,
        detail=detail, source=source, reason=reason, evidence=evidence or {},
    )


def not_checked(name: str, *, detail: str, source: str = "",
                reason: Reason | None = None) -> Signal:
    """The check never ran — feature off, no key, or deliberately skipped."""
    return Signal(
        name=name, epistemic_class=EpistemicClass.PROCESS_ATTESTATION,
        check_status=CheckStatus.NOT_CHECKED, finding=Finding.UNRESOLVED,
        detail=detail, source=source, reason=reason,
    )


def not_applicable(name: str, *, reason: Reason, detail: str,
                   source: str = "") -> Signal:
    """The check has no meaning for this artifact.

    Distinct from both siblings, and the distinction is the point:

    ``not_checked``    we did not run it
    ``could_not_check`` we ran it and it failed
    ``not_applicable``  running it would be meaningless

    GRIM on a machine-learning result is the case — the test applies to means
    of bounded integer items, so its absence is not a gap in the checking. It
    must never be presented as an outstanding task (see `needs_attention`).
    """
    return Signal(
        name=name, epistemic_class=EpistemicClass.PROCESS_ATTESTATION,
        check_status=CheckStatus.NOT_APPLICABLE, finding=Finding.UNRESOLVED,
        detail=detail, source=source, reason=reason,
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
