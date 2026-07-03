"""Validate a paper's bibliography entries against authoritative records.

The authoritative lookup is injected (a callable mapping a Reference to a record
dict or None), so this module is pure and fully testable without network access.
Retriever implementations that hit CrossRef/OpenAlex/S2/arXiv/DBLP live elsewhere.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from papergraph.refcheck import matching

Status = Literal["verified", "suspect", "unverified"]

# Thresholds for the deterministic pre-filters (see NOVELTY_ENGINE_SPEC Component 5).
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
    url: str | None = None
    raw: str = ""


@dataclass
class RefVerdict:
    status: Status
    reasons: list[str] = field(default_factory=list)
    matched: dict | None = None


@dataclass
class BibReport:
    """Result of validating a whole bibliography."""

    entries: list[tuple[Reference, RefVerdict]] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        tally = {"verified": 0, "suspect": 0, "unverified": 0}
        for _, verdict in self.entries:
            tally[verdict.status] += 1
        return tally


# A lookup resolves a Reference to an authoritative record dict, or None if absent.
Lookup = Callable[[Reference], dict | None]


def _identifiers_conflict(claimed: str | None, authoritative: str | None) -> bool:
    """True only when both identifiers are present and differ (case-insensitive)."""
    if not claimed or not authoritative:
        return False
    return claimed.strip().lower() != authoritative.strip().lower()


def validate_reference(ref: Reference, lookup: Lookup) -> RefVerdict:
    record = lookup(ref)
    if record is None:
        return RefVerdict(
            status="unverified",
            reasons=["No matching record found in authoritative sources"],
        )

    reasons: list[str] = []
    if matching.title_similarity(ref.title, record.get("title", "")) < TITLE_MATCH_THRESHOLD:
        reasons.append("Title does not match the authoritative record")
    if ref.authors and (
        matching.author_overlap(ref.authors, record.get("authors", [])) < AUTHOR_OVERLAP_THRESHOLD
    ):
        reasons.append("Fewer than 60% of cited authors match the record")
    if _identifiers_conflict(ref.doi, record.get("doi")):
        reasons.append("Cited DOI conflicts with the authoritative record")
    if _identifiers_conflict(ref.arxiv_id, record.get("arxiv_id")):
        reasons.append("Cited arXiv ID conflicts with the authoritative record")

    status: Status = "verified" if not reasons else "suspect"
    return RefVerdict(status=status, reasons=reasons, matched=record)


def validate_bibliography(refs: list[Reference], lookup: Lookup) -> BibReport:
    """Validate every reference, preserving input order, into a BibReport."""
    return BibReport(entries=[(ref, validate_reference(ref, lookup)) for ref in refs])
