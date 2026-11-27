"""Validate a paper's bibliography entries against authoritative records.

The authoritative lookup is injected (a callable mapping a Reference to a record
dict or None), so this module is pure and fully testable without network access.
Retriever implementations that hit arXiv/CrossRef/OpenAlex/S2 live elsewhere;
PubMed, Europe PMC, and DBLP are opt-in domain connectors.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from research_companion.refcheck import matching

Status = Literal["verified", "suspect", "unverified"]

# Thresholds for the deterministic reference-matching pre-filters.
TITLE_MATCH_THRESHOLD = 0.9
AUTHOR_OVERLAP_THRESHOLD = 0.6


@dataclass
class Reference:
    """A bibliography entry as the citing paper claims it."""

    title: str = ""
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    pmid: str | None = None
    pmcid: str | None = None
    url: str | None = None
    raw: str = ""


@dataclass
class RefVerdict:
    status: Status
    reasons: list[str] = field(default_factory=list)
    matched: dict | None = None
    #: Editorial notices on the MATCHED work: "retraction",
    #: "partial_retraction", "expression_of_concern". Separate from `status`
    #: on purpose: a retracted paper exists and may be cited correctly, so it
    #: is neither "suspect" nor "unverified". It is a different fact.
    notices: list[str] = field(default_factory=list)
    #: True only when the catalogue that matched this reference records
    #: retractions. False means nothing was established either way (arXiv,
    #: a domain connector, or no match), never "not retracted".
    retraction_checked: bool = False


@dataclass
class BibReport:
    """Result of validating a whole bibliography."""

    entries: list[tuple[Reference, RefVerdict]] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        tally = {"verified": 0, "suspect": 0, "unverified": 0}
        for _, verdict in self.entries:
            tally[verdict.status] += 1
        return tally

    def retraction_counts(self) -> dict[str, int]:
        """How many references carry a notice, and over what denominator.

        ``checked`` is the honest denominator: references whose matched
        catalogue records retractions at all. ``flagged`` of ``checked`` is the
        claim; the remainder of the bibliography was not checked for this.
        """
        checked = sum(1 for _, v in self.entries if v.retraction_checked)
        retracted = sum(1 for _, v in self.entries if "retraction" in v.notices)
        flagged = sum(1 for _, v in self.entries if v.notices)
        return {"checked": checked, "flagged": flagged, "retracted": retracted,
                "not_checked": len(self.entries) - checked}


# A lookup resolves a Reference to an authoritative record dict, or None if absent.
Lookup = Callable[[Reference], dict | None]


def _identifiers_conflict(claimed: str | None, authoritative: str | None) -> bool:
    """True only when both identifiers are present and differ (case-insensitive)."""
    if not claimed or not authoritative:
        return False
    return claimed.strip().lower() != authoritative.strip().lower()


def validate_reference(ref: Reference, lookup: Lookup) -> RefVerdict:
    # Distinguish "the sources answered, and none of them has this" from "we
    # could not reach the sources". Both used to surface as the first message,
    # which states as fact something an outage cannot establish.
    from research_companion.refcheck.retrieval import lookup_with_outcome

    outcome = lookup_with_outcome(ref, lookup=lookup)
    record = outcome.record
    if record is None:
        if not outcome.any_reachable:
            return RefVerdict(
                status="unverified",
                reasons=[
                    "Could not verify — no bibliographic source could be "
                    "reached. This is not evidence the reference is missing; "
                    "try again shortly."
                ],
            )
        return RefVerdict(
            status="unverified",
            reasons=["No matching record found in authoritative sources"],
        )

    reasons: list[str] = []
    # Compare against the FULL cited line, not just the parsed title: a
    # reference read from a paper's bibliography carries authors and venue
    # around the title (see matching.title_is_cited).
    cited_text = ref.raw or ref.title
    # Imported here: parse imports Reference from this module.
    from research_companion.refcheck.parse import probable_title
    if not matching.title_is_cited(cited_text, record.get("title", "")):
        reasons.append("Title does not match the authoritative record")
    elif (matching.title_matched_by_containment(cited_text, record.get("title", ""),
                                                probable_title(cited_text))
          and matching.authors_corroborate(cited_text, record.get("authors") or []) is False):
        # The record's title appears inside the cited line, but none of its
        # authors do. A short title is contained in many longer ones, so this
        # is a different work until something else agrees.
        reasons.append("The matched record's title appears in the citation, "
                       "but none of its authors do: it may be a different work")
    if ref.authors and (
        matching.author_overlap(ref.authors, record.get("authors", [])) < AUTHOR_OVERLAP_THRESHOLD
    ):
        reasons.append("Fewer than 60% of cited authors match the record")
    if _identifiers_conflict(ref.doi, record.get("doi")):
        reasons.append("Cited DOI conflicts with the authoritative record")
    if _identifiers_conflict(ref.arxiv_id, record.get("arxiv_id")):
        reasons.append("Cited arXiv ID conflicts with the authoritative record")
    if _identifiers_conflict(ref.pmid, record.get("pmid")):
        reasons.append("Cited PMID conflicts with the authoritative record")

    status: Status = "verified" if not reasons else "suspect"
    return RefVerdict(
        status=status, reasons=reasons, matched=record,
        notices=[str(n) for n in (record.get("notices") or [])],
        retraction_checked=bool(record.get("retraction_checked")),
    )


def validate_bibliography(refs: list[Reference], lookup: Lookup) -> BibReport:
    """Validate every reference, preserving input order, into a BibReport."""
    return BibReport(entries=[(ref, validate_reference(ref, lookup)) for ref in refs])
