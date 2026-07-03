"""Tests for reviewer-comment segmentation heuristics."""
from __future__ import annotations

from papergraph.rebuttal.segment import segment_reviews

REVIEW = """Reviewer 1

1. The paper is missing a comparison against baseline X entirely.
2) Notation in section 3 is unclear and inconsistent throughout.

Reviewer 2

- The claimed novelty overlaps with He et al. substantially here.

The evaluation section needs statistical significance tests included.
"""


def test_segment_numbered_and_bulleted_and_paragraphs():
    concerns = segment_reviews(REVIEW)
    ids = [c.concern_id for c in concerns]
    assert ids == ["R1.1", "R1.2", "R2.1", "R2.2"]
    assert concerns[0].reviewer == "R1"
    assert "baseline X" in concerns[0].text
    assert concerns[2].reviewer == "R2"
    assert "He et al." in concerns[2].text
    assert "significance tests" in concerns[3].text


def test_segment_no_headers_defaults_single_reviewer():
    concerns = segment_reviews("First concern paragraph is long enough to count.\n\n"
                               "Second concern paragraph is also long enough here.")
    assert [c.concern_id for c in concerns] == ["R1.1", "R1.2"]


def test_segment_short_fragment_merges_into_previous():
    concerns = segment_reviews("1. A sufficiently long first concern sentence here.\n\nOk.")
    assert len(concerns) == 1
    assert "Ok." in concerns[0].text


def test_segment_empty_input():
    assert segment_reviews("   \n\n ") == []
