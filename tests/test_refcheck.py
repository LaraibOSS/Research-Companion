"""Tests for research_companion.refcheck — deterministic reference validation.

No network calls; the authoritative-lookup function is injected.
"""
from __future__ import annotations

from research_companion.refcheck import matching
from research_companion.refcheck.validate import (
    Reference,
    validate_bibliography,
    validate_reference,
)


def test_author_overlap_exact_last_names():
    claimed = ["Jane Doe", "John Smith"]
    authoritative = ["Jane Doe", "John Smith"]
    assert matching.author_overlap(claimed, authoritative) == 1.0


def test_author_overlap_matches_on_last_name_with_initial():
    # "J. Smith" in the bibliography should match "John Smith" in the record.
    assert matching.author_overlap(["J. Smith"], ["John Smith"]) == 1.0


def test_author_overlap_partial():
    claimed = ["Jane Doe", "Wrong Person"]
    authoritative = ["Jane Doe", "John Smith"]
    assert matching.author_overlap(claimed, authoritative) == 0.5


def test_author_overlap_empty_claimed_is_zero():
    assert matching.author_overlap([], ["Jane Doe"]) == 0.0


def test_title_similarity_identical_ignoring_case_and_punctuation():
    a = "Attention Is All You Need"
    b = "attention is all you need."
    assert matching.title_similarity(a, b) == 1.0


def test_title_similarity_ignores_whitespace_runs():
    assert matching.title_similarity("Graph  RAG", "Graph RAG") == 1.0


def test_title_similarity_low_for_different_titles():
    score = matching.title_similarity(
        "Attention Is All You Need", "A Survey of Reinforcement Learning"
    )
    assert score < 0.5


def test_title_similarity_high_for_near_match():
    score = matching.title_similarity(
        "Deep Residual Learning for Image Recognition",
        "Deep Residual Learning for Image Recognition (v2)",
    )
    assert score > 0.8


# --- validate_reference -----------------------------------------------------

def _record(**kw):
    base = {"title": "", "authors": [], "year": None, "doi": None, "arxiv_id": None}
    base.update(kw)
    return base


def _const(record):
    """Build a lookup that ignores its argument and always returns `record`."""
    def _lookup(ref):
        return record
    return _lookup


def test_validate_reference_verified_on_title_and_author_match():
    ref = Reference(title="Attention Is All You Need", authors=["Ashish Vaswani"])
    lookup = _const(_record(title="Attention Is All You Need", authors=["Ashish Vaswani"]))
    verdict = validate_reference(ref, lookup)
    assert verdict.status == "verified"
    assert verdict.reasons == []


def test_validate_reference_unverified_when_no_record_found():
    ref = Reference(title="A Paper That Does Not Exist", authors=["Nobody"])
    lookup = _const(None)
    verdict = validate_reference(ref, lookup)
    assert verdict.status == "unverified"
    assert any("no matching record" in reason.lower() for reason in verdict.reasons)


def test_validate_reference_verified_when_no_authors_claimed():
    # A title-only reference (common after parsing) must not be penalized for
    # authors it never claimed — only the title is checked.
    ref = Reference(title="Attention Is All You Need")
    lookup = _const(_record(title="Attention Is All You Need", authors=["Ashish Vaswani"]))
    verdict = validate_reference(ref, lookup)
    assert verdict.status == "verified"
    assert verdict.reasons == []


def test_validate_reference_suspect_on_low_author_overlap():
    ref = Reference(title="Attention Is All You Need", authors=["Wrong Author"])
    lookup = _const(_record(title="Attention Is All You Need", authors=["Ashish Vaswani"]))
    verdict = validate_reference(ref, lookup)
    assert verdict.status == "suspect"
    assert any("author" in reason.lower() for reason in verdict.reasons)


def test_validate_reference_suspect_on_title_mismatch():
    ref = Reference(title="A Totally Different Title", authors=["Ashish Vaswani"])
    lookup = _const(_record(title="Attention Is All You Need", authors=["Ashish Vaswani"]))
    verdict = validate_reference(ref, lookup)
    assert verdict.status == "suspect"
    assert any("title" in reason.lower() for reason in verdict.reasons)


def test_validate_reference_suspect_on_doi_conflict():
    # Title and authors match, but the cited DOI contradicts the record's DOI.
    ref = Reference(
        title="Attention Is All You Need",
        authors=["Ashish Vaswani"],
        doi="10.1234/wrong",
    )
    lookup = _const(_record(
        title="Attention Is All You Need",
        authors=["Ashish Vaswani"],
        doi="10.5555/correct",
    ))
    verdict = validate_reference(ref, lookup)
    assert verdict.status == "suspect"
    assert any("doi" in reason.lower() for reason in verdict.reasons)


def test_validate_reference_suspect_on_arxiv_conflict():
    ref = Reference(
        title="Attention Is All You Need",
        authors=["Ashish Vaswani"],
        arxiv_id="1706.03762",
    )
    lookup = _const(_record(
        title="Attention Is All You Need",
        authors=["Ashish Vaswani"],
        arxiv_id="9999.99999",
    ))
    verdict = validate_reference(ref, lookup)
    assert verdict.status == "suspect"
    assert any("arxiv" in reason.lower() for reason in verdict.reasons)


# --- validate_bibliography (batch entry point) ------------------------------

def test_validate_bibliography_aggregates_counts_and_entries():
    verified = Reference(title="Attention Is All You Need", authors=["Ashish Vaswani"])
    suspect = Reference(title="Attention Is All You Need", authors=["Wrong Author"])
    missing = Reference(title="Nonexistent Paper", authors=["Nobody"])

    def lookup(r):
        if r.title == "Nonexistent Paper":
            return None
        return _record(title="Attention Is All You Need", authors=["Ashish Vaswani"])

    report = validate_bibliography([verified, suspect, missing], lookup)

    assert len(report.entries) == 3
    assert report.counts() == {"verified": 1, "suspect": 1, "unverified": 1}
    # entries pair each reference with its verdict, preserving input order
    assert report.entries[0][0] is verified
    assert report.entries[0][1].status == "verified"


def test_validate_bibliography_empty_is_all_zero_counts():
    report = validate_bibliography([], lambda r: None)
    assert report.entries == []
    assert report.counts() == {"verified": 0, "suspect": 0, "unverified": 0}
