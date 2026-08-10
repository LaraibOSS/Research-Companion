"""Tests for research_companion.directions and its DIRECTIONS_PROMPT triad.

Pipeline under test (mirrors research_companion/gaps.py's synthesize_gaps
shape): _collect_grounding (pure) -> one DIRECTIONS_PROMPT call ->
_assemble_directions (pure, drops invented citation keys) -> rank_directions
(pure, deterministic score, stable sort) -> synthesize_directions
(orchestrator).
"""

from __future__ import annotations

import json

import networkx as nx

# ---------------------------------------------------------------------------
# DIRECTIONS_PROMPT triad (feat/brainstorm-directions, Task 1)
# ---------------------------------------------------------------------------

def test_directions_prompt_sha256_is_stable_and_64_hex_chars():
    from research_companion.prompts import directions_prompt_sha256
    sha = directions_prompt_sha256()
    assert sha == directions_prompt_sha256()
    assert len(sha) == 64
    int(sha, 16)  # raises ValueError if not hex


def test_format_directions_prompt_substitutes_topic_and_grounding_block():
    from research_companion.prompts import format_directions_prompt
    rendered = format_directions_prompt(
        topic="graph neural networks for code",
        grounding_block="- [p:arxiv:2401.00001] Some Paper (2024).",
    )
    assert "graph neural networks for code" in rendered
    assert "[p:arxiv:2401.00001] Some Paper (2024)." in rendered
    assert "<<TOPIC>>" not in rendered
    assert "<<GROUNDING_BLOCK>>" not in rendered


# ---------------------------------------------------------------------------
# _underexplored_concepts
# ---------------------------------------------------------------------------

def _concept_graph(counts: dict[str, int]) -> nx.Graph:
    """Build a minimal graph with one concept node per (name, paper_count)."""
    G = nx.Graph()
    for name, count in counts.items():
        G.add_node(f"concept::{name}", kind="concept", label=name, paper_count=count)
    return G


def test_underexplored_concepts_empty_graph_returns_empty():
    from research_companion.directions import _underexplored_concepts
    assert _underexplored_concepts(nx.Graph()) == []
    assert _underexplored_concepts(None) == []


def test_underexplored_concepts_ignores_zero_and_non_concept_nodes():
    from research_companion.directions import _underexplored_concepts
    G = _concept_graph({"a": 1, "b": 0})
    G.add_node("paper::x", kind="paper", label="X")
    out = _underexplored_concepts(G)
    names = [c["name"] for c in out]
    assert "a" in names
    assert "b" not in names  # paper_count 0 is not eligible
    assert "X" not in names  # not a concept node


def test_underexplored_concepts_returns_bottom_third_by_paper_count_stable():
    from research_companion.directions import _underexplored_concepts
    # 9 concepts, paper_count 1..9 -> bottom third = 3 lowest.
    G = _concept_graph({f"c{i}": i for i in range(1, 10)})
    out = _underexplored_concepts(G)
    assert [c["name"] for c in out] == ["c1", "c2", "c3"]
    assert [c["paper_count"] for c in out] == [1, 2, 3]


def test_underexplored_concepts_capped_at_cap():
    from research_companion.directions import _underexplored_concepts
    # 30 concepts, all paper_count=1 -> bottom third = 10, capped at cap=5.
    G = _concept_graph({f"c{i}": 1 for i in range(30)})
    out = _underexplored_concepts(G, cap=5)
    assert len(out) == 5


def test_underexplored_concepts_ties_broken_by_name_for_determinism():
    from research_companion.directions import _underexplored_concepts
    G = _concept_graph({"zeta": 1, "alpha": 1, "beta": 1})
    out = _underexplored_concepts(G)
    assert [c["name"] for c in out] == ["alpha", "beta", "zeta"]
