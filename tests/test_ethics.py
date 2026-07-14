"""Tests for the deterministic ethics-declaration detector."""
from __future__ import annotations

from research_companion.ethics import detect_declarations


def test_detects_funding_and_coi():
    t = ("This work was supported by grant number 123. "
         "The authors declare no conflict of interest.")
    r = detect_declarations(t)
    assert r["declarations"]["funding"] is True
    assert r["declarations"]["conflict_of_interest"] is True
    assert "funding" in r["present"] and "conflict_of_interest" in r["present"]


def test_detects_ethics_and_consent():
    t = ("The study was approved by the Institutional Review Board. "
         "Informed consent was obtained from all participants.")
    r = detect_declarations(t)
    assert r["declarations"]["ethics_approval"] is True
    assert r["declarations"]["informed_consent"] is True


def test_author_contributions():
    r = detect_declarations("Author Contributions: A and B contributed equally.")
    assert r["declarations"]["author_contributions"] is True


def test_missing_expected_lists_only_default_expected():
    # A paper with no declarations at all.
    r = detect_declarations("A purely technical paper body.")
    assert set(r["present"]) == set()
    # Expected-by-default: funding, conflict_of_interest, author_contributions.
    assert set(r["missing_expected"]) == {
        "funding", "conflict_of_interest", "author_contributions"}
    # ethics/consent are absent but NOT flagged as missing_expected.
    assert "ethics_approval" in r["absent"]
    assert "ethics_approval" not in r["missing_expected"]


def test_fully_declared_paper_has_no_missing():
    t = ("Funding: grant 1. The authors declare no competing interest. "
         "Author contributions: equal. Approved by the ethics committee. "
         "Informed consent obtained.")
    r = detect_declarations(t)
    assert r["missing_expected"] == []
    assert set(r["absent"]) == set()


def test_empty_input():
    r = detect_declarations("")
    assert r["present"] == []
    assert len(r["absent"]) == 5
