"""Tests for cross-reviewer concern grouping."""
from __future__ import annotations

from papergraph.rebuttal.dedup import group_concerns
from papergraph.rebuttal.models import Concern


def _c(cid, text):
    return Concern(concern_id=cid, reviewer=cid.split(".")[0], text=text)


def test_similar_concerns_grouped_across_reviewers():
    concerns = [
        _c("R1.1", "The paper is missing a baseline comparison against X"),
        _c("R2.1", "Missing baseline comparison against method X in evaluation"),
        _c("R2.2", "Figures are far too small to read"),
    ]
    groups = group_concerns(concerns)
    assert ["R1.1", "R2.1"] in groups
    assert ["R2.2"] in groups


def test_all_distinct_yields_singletons():
    concerns = [_c("R1.1", "alpha beta gamma delta"), _c("R1.2", "completely different topic entirely")]
    assert group_concerns(concerns) == [["R1.1"], ["R1.2"]]
