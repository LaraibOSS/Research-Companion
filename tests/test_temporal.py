"""Tests for research_companion.temporal — deterministic research timeline builder.

All tests inject graph and papers directly so they require no store I/O.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import networkx as nx

from research_companion.temporal import build_timeline

# ---------------------------------------------------------------------------
# Minimal PaperMetadata-like stub
# ---------------------------------------------------------------------------

@dataclass
class _Meta:
    paper_id: str
    year: int | None = None
    added_at: str = ""
    title: str = ""
    authors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Graph builder helpers
# ---------------------------------------------------------------------------

def _paper_node(G: nx.Graph, paper_id: str, year: int | None = None) -> None:
    G.add_node(paper_id, kind="paper", label=paper_id, year=year)


def _entity_node(G: nx.Graph, node_id: str, kind: str, label: str) -> None:
    G.add_node(node_id, kind=kind, label=label)


def _contains(G: nx.Graph, paper_id: str, entity_id: str) -> None:
    G.add_edge(paper_id, entity_id, relation="contains")


# ---------------------------------------------------------------------------
# Test 1 — basic: two papers sharing a concept
# ---------------------------------------------------------------------------

def test_basic_two_papers_one_concept():
    G = nx.Graph()
    _paper_node(G, "p2020", 2020)
    _paper_node(G, "p2024", 2024)
    _entity_node(G, "concept::transformer", "concept", "Transformer")
    _contains(G, "p2020", "concept::transformer")
    _contains(G, "p2024", "concept::transformer")

    papers = [
        _Meta("p2020", year=2020, added_at="2020-01-01T00:00:00"),
        _Meta("p2024", year=2024, added_at="2024-06-01T00:00:00"),
    ]

    result = build_timeline(graph=G, papers=papers)

    assert result["skipped_papers_without_year"] == 0
    assert result["truncated_tracks"] == 0

    tracks = result["tracks"]
    assert len(tracks) == 1
    t = tracks[0]
    assert t["kind"] == "concept"
    assert t["label"] == "Transformer"
    assert t["first_seen"] == 2020
    assert t["introduced_by"] == "p2020"

    appearances = t["appearances"]
    assert len(appearances) == 2
    assert appearances[0] == {"paper_id": "p2020", "year": 2020}
    assert appearances[1] == {"paper_id": "p2024", "year": 2024}


# ---------------------------------------------------------------------------
# Test 2 — introduced_by tie-break
# ---------------------------------------------------------------------------

def test_introduced_by_tiebreak_same_year_earlier_added_at_wins():
    G = nx.Graph()
    _paper_node(G, "pA", 2022)
    _paper_node(G, "pB", 2022)
    _entity_node(G, "method::sgd", "method", "SGD")
    _contains(G, "pA", "method::sgd")
    _contains(G, "pB", "method::sgd")

    # pB has earlier added_at -> should win
    papers = [
        _Meta("pA", year=2022, added_at="2022-06-15T00:00:00"),
        _Meta("pB", year=2022, added_at="2022-01-01T00:00:00"),
    ]

    result = build_timeline(graph=G, papers=papers)
    assert result["tracks"][0]["introduced_by"] == "pB"


def test_introduced_by_tiebreak_same_year_same_added_at_lexicographic():
    G = nx.Graph()
    _paper_node(G, "pZZZ", 2021)
    _paper_node(G, "pAAA", 2021)
    _entity_node(G, "dataset::mnist", "dataset", "MNIST")
    _contains(G, "pZZZ", "dataset::mnist")
    _contains(G, "pAAA", "dataset::mnist")

    # Same added_at — lex order wins (pAAA < pZZZ)
    papers = [
        _Meta("pZZZ", year=2021, added_at="2021-03-01T00:00:00"),
        _Meta("pAAA", year=2021, added_at="2021-03-01T00:00:00"),
    ]

    result = build_timeline(graph=G, papers=papers)
    assert result["tracks"][0]["introduced_by"] == "pAAA"


# ---------------------------------------------------------------------------
# Test 3 — min_appearances filter and max_tracks cap
# ---------------------------------------------------------------------------

def test_min_appearances_filters_singletons():
    G = nx.Graph()
    _paper_node(G, "p1", 2019)
    _paper_node(G, "p2", 2020)
    _entity_node(G, "concept::bert", "concept", "BERT")
    _entity_node(G, "concept::gpt", "concept", "GPT")
    # BERT appears in both, GPT only in p1
    _contains(G, "p1", "concept::bert")
    _contains(G, "p2", "concept::bert")
    _contains(G, "p1", "concept::gpt")

    papers = [
        _Meta("p1", year=2019, added_at="2019-01-01T00:00:00"),
        _Meta("p2", year=2020, added_at="2020-01-01T00:00:00"),
    ]

    result = build_timeline(graph=G, papers=papers, min_appearances=2)
    track_labels = [t["label"] for t in result["tracks"]]
    assert "BERT" in track_labels
    assert "GPT" not in track_labels


def test_max_tracks_cap_and_truncated_count():
    G = nx.Graph()
    papers_list = []
    for i in range(5):
        pid = f"paper{i}"
        _paper_node(G, pid, 2020 + i)
        papers_list.append(_Meta(pid, year=2020 + i, added_at=f"202{i}-01-01T00:00:00"))
        eid = f"concept::entity{i}"
        _entity_node(G, eid, "concept", f"Entity{i}")
        _contains(G, pid, eid)

    result = build_timeline(graph=G, papers=papers_list, max_tracks=3)
    assert len(result["tracks"]) == 3
    assert result["truncated_tracks"] == 2


# ---------------------------------------------------------------------------
# Test 4 — papers without year
# ---------------------------------------------------------------------------

def test_paper_without_year_excluded_from_appearances_counted_in_skipped():
    G = nx.Graph()
    _paper_node(G, "p_with_year", 2023)
    _paper_node(G, "p_no_year", None)
    _entity_node(G, "method::rnn", "method", "RNN")
    _contains(G, "p_with_year", "method::rnn")
    _contains(G, "p_no_year", "method::rnn")

    papers = [
        _Meta("p_with_year", year=2023, added_at="2023-01-01T00:00:00"),
        _Meta("p_no_year", year=None, added_at="2023-02-01T00:00:00"),
    ]

    result = build_timeline(graph=G, papers=papers)
    assert result["skipped_papers_without_year"] == 1

    # The track for RNN should only include the paper with a year
    rnn_tracks = [t for t in result["tracks"] if t["label"] == "RNN"]
    assert len(rnn_tracks) == 1
    app_paper_ids = [a["paper_id"] for a in rnn_tracks[0]["appearances"]]
    assert "p_with_year" in app_paper_ids
    assert "p_no_year" not in app_paper_ids


def test_entity_only_in_yearless_paper_produces_no_track():
    G = nx.Graph()
    _paper_node(G, "p_no_year", None)
    _entity_node(G, "concept::lonely", "concept", "LonelyConcept")
    _contains(G, "p_no_year", "concept::lonely")

    papers = [_Meta("p_no_year", year=None, added_at="2023-01-01T00:00:00")]

    result = build_timeline(graph=G, papers=papers)
    assert result["skipped_papers_without_year"] == 1
    assert result["tracks"] == []


# ---------------------------------------------------------------------------
# Test 5 — papers_per_year counts and years union
# ---------------------------------------------------------------------------

def test_papers_per_year_counts_all_papers_with_years():
    G = nx.Graph()
    papers_list = [
        _Meta("p1", year=2019, added_at="2019-01-01T00:00:00"),
        _Meta("p2", year=2019, added_at="2019-06-01T00:00:00"),
        _Meta("p3", year=2021, added_at="2021-01-01T00:00:00"),
        _Meta("p_no_year", year=None, added_at="2022-01-01T00:00:00"),
    ]
    # Add paper nodes to graph
    for meta in papers_list:
        _paper_node(G, meta.paper_id, meta.year)

    result = build_timeline(graph=G, papers=papers_list)

    ppy = {entry["year"]: entry["count"] for entry in result["papers_per_year"]}
    assert ppy[2019] == 2
    assert ppy[2021] == 1
    assert 2022 not in ppy  # year-less paper excluded

    assert result["skipped_papers_without_year"] == 1


def test_years_union_includes_appearance_years_and_paper_years():
    """years = union of papers_per_year years + appearance years (ascending)."""
    G = nx.Graph()
    # Paper in 2018 with no entities (so no track), plus entity appearing in 2020/2022
    _paper_node(G, "p2018", 2018)
    _paper_node(G, "p2020", 2020)
    _paper_node(G, "p2022", 2022)
    _entity_node(G, "concept::x", "concept", "X")
    _contains(G, "p2020", "concept::x")
    _contains(G, "p2022", "concept::x")

    papers = [
        _Meta("p2018", year=2018, added_at="2018-01-01T00:00:00"),
        _Meta("p2020", year=2020, added_at="2020-01-01T00:00:00"),
        _Meta("p2022", year=2022, added_at="2022-01-01T00:00:00"),
    ]

    result = build_timeline(graph=G, papers=papers)
    assert result["years"] == [2018, 2020, 2022]


def test_empty_store_returns_all_empty_shape():
    G = nx.Graph()
    result = build_timeline(graph=G, papers=[])

    assert result["years"] == []
    assert result["papers_per_year"] == []
    assert result["tracks"] == []
    assert result["skipped_papers_without_year"] == 0
    assert result["truncated_tracks"] == 0


# ---------------------------------------------------------------------------
# Test 6 — claims and result nodes NEVER become tracks
# ---------------------------------------------------------------------------

def test_claims_and_results_never_become_tracks():
    G = nx.Graph()
    _paper_node(G, "p1", 2020)
    _paper_node(G, "p2", 2021)
    G.add_node("claim::abc", kind="claim", label="Some claim")
    G.add_node("result::xyz", kind="result", label="F1=0.9")
    G.add_node("paper::other", kind="paper", label="Other paper")
    _contains(G, "p1", "claim::abc")
    _contains(G, "p2", "claim::abc")
    _contains(G, "p1", "result::xyz")
    _contains(G, "p2", "result::xyz")

    papers = [
        _Meta("p1", year=2020, added_at="2020-01-01T00:00:00"),
        _Meta("p2", year=2021, added_at="2021-01-01T00:00:00"),
    ]

    result = build_timeline(graph=G, papers=papers)
    # No entity nodes of valid kinds -> no tracks
    assert result["tracks"] == []


# ---------------------------------------------------------------------------
# Test 7 — determinism: same inputs twice -> identical output
# ---------------------------------------------------------------------------

def test_determinism_same_inputs_produce_identical_output():
    G = nx.Graph()
    _paper_node(G, "pA", 2018)
    _paper_node(G, "pB", 2019)
    _paper_node(G, "pC", 2020)
    _entity_node(G, "concept::alpha", "concept", "Alpha")
    _entity_node(G, "method::beta", "method", "Beta")
    _entity_node(G, "dataset::gamma", "dataset", "Gamma")
    _contains(G, "pA", "concept::alpha")
    _contains(G, "pB", "concept::alpha")
    _contains(G, "pB", "method::beta")
    _contains(G, "pC", "method::beta")
    _contains(G, "pA", "dataset::gamma")

    papers = [
        _Meta("pA", year=2018, added_at="2018-01-01T00:00:00"),
        _Meta("pB", year=2019, added_at="2019-03-01T00:00:00"),
        _Meta("pC", year=2020, added_at="2020-06-01T00:00:00"),
    ]

    result1 = build_timeline(graph=G, papers=papers)
    result2 = build_timeline(graph=G, papers=papers)
    assert result1 == result2


# ---------------------------------------------------------------------------
# Test 8 — tracks sort order: first_seen asc, len(appearances) desc, label asc
# ---------------------------------------------------------------------------

def test_tracks_sort_order():
    G = nx.Graph()
    _paper_node(G, "p2000a", 2000)
    _paper_node(G, "p2000b", 2000)
    _paper_node(G, "p2005", 2005)
    _paper_node(G, "p2010", 2010)

    # EntityA: first_seen=2000, 2 appearances
    _entity_node(G, "concept::entitya", "concept", "EntityA")
    _contains(G, "p2000a", "concept::entitya")
    _contains(G, "p2000b", "concept::entitya")

    # EntityB: first_seen=2000, 1 appearance -> should come after EntityA
    _entity_node(G, "concept::entityb", "concept", "EntityB")
    _contains(G, "p2000a", "concept::entityb")

    # EntityC: first_seen=2005, 1 appearance -> comes after 2000 entities
    _entity_node(G, "concept::entityc", "concept", "EntityC")
    _contains(G, "p2005", "concept::entityc")

    papers = [
        _Meta("p2000a", year=2000, added_at="2000-01-01T00:00:00"),
        _Meta("p2000b", year=2000, added_at="2000-06-01T00:00:00"),
        _Meta("p2005", year=2005, added_at="2005-01-01T00:00:00"),
        _Meta("p2010", year=2010, added_at="2010-01-01T00:00:00"),
    ]

    result = build_timeline(graph=G, papers=papers)
    labels = [t["label"] for t in result["tracks"]]

    # EntityA (2000, 2 appearances) before EntityB (2000, 1 appearance)
    assert labels.index("EntityA") < labels.index("EntityB")
    # Both 2000 entities before EntityC (2005)
    assert labels.index("EntityB") < labels.index("EntityC")


# ---------------------------------------------------------------------------
# Test 9 — appearances ascending by (year, paper_id)
# ---------------------------------------------------------------------------

def test_appearances_sorted_ascending_by_year_then_paper_id():
    G = nx.Graph()
    _paper_node(G, "z_paper_2020", 2020)
    _paper_node(G, "a_paper_2020", 2020)
    _paper_node(G, "m_paper_2021", 2021)
    _entity_node(G, "concept::shared", "concept", "Shared")
    _contains(G, "z_paper_2020", "concept::shared")
    _contains(G, "a_paper_2020", "concept::shared")
    _contains(G, "m_paper_2021", "concept::shared")

    papers = [
        _Meta("z_paper_2020", year=2020, added_at="2020-01-01T00:00:00"),
        _Meta("a_paper_2020", year=2020, added_at="2020-02-01T00:00:00"),
        _Meta("m_paper_2021", year=2021, added_at="2021-01-01T00:00:00"),
    ]

    result = build_timeline(graph=G, papers=papers)
    apps = result["tracks"][0]["appearances"]
    # Year 2020 papers first, sorted by paper_id lex within same year
    assert apps[0]["paper_id"] == "a_paper_2020"
    assert apps[1]["paper_id"] == "z_paper_2020"
    assert apps[2]["paper_id"] == "m_paper_2021"
