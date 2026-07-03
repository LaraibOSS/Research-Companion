"""Tests for grounding-passage retrieval (term overlap, deterministic)."""
from __future__ import annotations

from papergraph.rebuttal.retrieve import retrieve_passages

FULLTEXT = """Introduction paragraph about graphs and knowledge.

We evaluate baseline comparison methods against BaselineX with three datasets carefully.

Unrelated paragraph about typography and fonts entirely.
"""


def test_retrieve_ranks_matching_paragraph_first():
    ps = retrieve_passages("Missing baseline comparison against BaselineX", FULLTEXT, k=2)
    assert ps and ps[0].location == "para 2"
    assert "BaselineX" in ps[0].text
    assert ps[0].score > 0


def test_retrieve_returns_empty_when_no_overlap():
    assert retrieve_passages("quantum entanglement spectroscopy", FULLTEXT) == []


def test_retrieve_k_limits():
    ps = retrieve_passages("paragraph about graphs typography datasets", FULLTEXT, k=1)
    assert len(ps) == 1
