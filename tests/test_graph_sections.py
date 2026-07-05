"""Tests for section/strength awareness and delta computation in graph.py.

TDD: tests written first, then implementation added to research_companion/graph.py.
"""
from __future__ import annotations

import pytest

from research_companion import graph, prompts, store


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_paper(paper_id: str, title: str, extraction: dict) -> store.PaperMetadata:
    """Write a paper + its extraction to the store, mirroring test_graph.py pattern."""
    meta = store.PaperMetadata(
        paper_id=paper_id, title=title, authors=["Alice", "Bob"], year=2024,
        added_at="2026-01-01T00:00:00",
    )
    meta.save()
    store.save_extraction(paper_id, extraction, prompt_sha=prompts.extraction_prompt_sha256())
    return meta


def _minimal_extraction(concepts=None, methods=None, section_on_concepts=None) -> dict:
    """Build a minimal valid extraction. section_on_concepts maps concept index -> section_id."""
    cs = concepts or ["Alpha", "Beta"]
    concept_list = []
    for i, name in enumerate(cs):
        entry = {"name": name, "definition": f"Definition of {name}"}
        if section_on_concepts and i < len(section_on_concepts):
            entry["section"] = section_on_concepts[i]
        concept_list.append(entry)
    return {
        "concepts": concept_list,
        "methods": methods or [],
        "datasets": [],
        "claims": [],
        "results": [],
        "related_work": [],
    }


def _sections_payload(section_ids=("sec1", "sec2")) -> dict:
    """Build a minimal sections payload for save_sections()."""
    return {
        "text_sha256": "abc123",
        "version": "1",
        "sections": [
            {"section_id": sid, "title": f"Section {sid}", "level": 1,
             "parent": None, "char_start": 0, "char_end": 100}
            for sid in section_ids
        ],
    }


def _strength_payload(score=0.87, band="strong", color="#4CAF50") -> dict:
    return {"score": score, "band": band, "color": color}


# ---------------------------------------------------------------------------
# 1. build_graph enrichment: sections
# ---------------------------------------------------------------------------

def test_build_graph_paper_node_has_sections_when_sections_json_present():
    """Paper node gets a 'sections' attr when store.load_sections returns a payload."""
    pid = "arxiv:2410.10001"
    _seed_paper(pid, "Paper Sections", _minimal_extraction())
    store.save_sections(pid, _sections_payload(["sec1", "sec2"]))

    G = graph.build_graph()
    node = G.nodes[pid]
    assert "sections" in node, "expected 'sections' attr on paper node"
    sections = node["sections"]
    assert isinstance(sections, list)
    assert len(sections) == 2
    ids = {s["id"] for s in sections}
    assert ids == {"sec1", "sec2"}
    # Check expected keys present
    for s in sections:
        assert "id" in s
        assert "title" in s
        assert "level" in s


def test_build_graph_paper_node_no_sections_attr_when_sections_json_absent():
    """Paper node must NOT have 'sections' key when no sections.json present."""
    pid = "arxiv:2410.10002"
    _seed_paper(pid, "Paper No Sections", _minimal_extraction())
    # No store.save_sections call.

    G = graph.build_graph()
    node = G.nodes[pid]
    assert "sections" not in node, "sections attr must be absent when no sections.json"


# ---------------------------------------------------------------------------
# 2. build_graph enrichment: strength
# ---------------------------------------------------------------------------

def test_build_graph_paper_node_has_strength_when_strength_json_present():
    """Paper node gets strength_band and strength_color when strength.json present."""
    pid = "arxiv:2410.10003"
    _seed_paper(pid, "Paper Strength", _minimal_extraction())
    store.save_strength(pid, _strength_payload(band="strong", color="#4CAF50"))

    G = graph.build_graph()
    node = G.nodes[pid]
    assert "strength_band" in node, "expected 'strength_band' on paper node"
    assert "strength_color" in node, "expected 'strength_color' on paper node"
    assert node["strength_band"] == "strong"
    assert node["strength_color"] == "#4CAF50"


def test_build_graph_paper_node_no_strength_attrs_when_strength_json_absent():
    """strength_band and strength_color must NOT appear when no strength.json present."""
    pid = "arxiv:2410.10004"
    _seed_paper(pid, "Paper No Strength", _minimal_extraction())
    # No store.save_strength call.

    G = graph.build_graph()
    node = G.nodes[pid]
    assert "strength_band" not in node
    assert "strength_color" not in node


# ---------------------------------------------------------------------------
# 3. contains edges carry section ids
# ---------------------------------------------------------------------------

def test_contains_edges_carry_section_from_entity():
    """Each contains-edge from a paper carries section=<entity's section value>."""
    pid = "arxiv:2410.10005"
    ext = _minimal_extraction(
        concepts=["Alpha", "Beta"],
        section_on_concepts=["sec1", "sec2"],
    )
    _seed_paper(pid, "Paper With Sections", ext)

    G = graph.build_graph()
    # Find contains-edges from this paper
    contains_edges = [
        (u, v, d) for u, v, d in G.edges(data=True)
        if (u == pid or v == pid) and d.get("relation") == "contains"
    ]
    assert len(contains_edges) == 2
    sections_on_edges = {d["section"] for _, _, d in contains_edges}
    assert sections_on_edges == {"sec1", "sec2"}


def test_contains_edges_section_none_when_entity_has_no_section_key():
    """Entity dicts without a 'section' key produce section=None on the contains-edge."""
    pid = "arxiv:2410.10006"
    ext = _minimal_extraction(concepts=["Gamma"])  # no section_on_concepts
    _seed_paper(pid, "Paper No Entity Section", ext)

    G = graph.build_graph()
    contains_edges = [
        (u, v, d) for u, v, d in G.edges(data=True)
        if (u == pid or v == pid) and d.get("relation") == "contains"
    ]
    assert len(contains_edges) == 1
    assert contains_edges[0][2]["section"] is None


# ---------------------------------------------------------------------------
# 4. section_subgraph
# ---------------------------------------------------------------------------

def test_section_subgraph_returns_paper_plus_matching_entities():
    """section_subgraph returns the paper node + entities whose contains-edge has matching section."""
    pid = "arxiv:2410.10007"
    ext = _minimal_extraction(
        concepts=["Alpha", "Beta"],
        section_on_concepts=["sec1", "sec2"],
    )
    _seed_paper(pid, "Paper Subgraph", ext)
    G = graph.build_graph()

    sg = graph.section_subgraph(G, pid, "sec1")
    assert pid in sg.nodes
    # Exactly one concept node (Alpha in sec1), paper, = 2 nodes
    concept_nodes = [n for n, d in sg.nodes(data=True) if d.get("kind") == "concept"]
    assert len(concept_nodes) == 1


def test_section_subgraph_excludes_other_sections():
    """Entities from other sections are NOT included in the subgraph."""
    pid = "arxiv:2410.10008"
    ext = _minimal_extraction(
        concepts=["Alpha", "Beta", "Gamma"],
        section_on_concepts=["sec1", "sec1", "sec2"],
    )
    _seed_paper(pid, "Paper Multi Section", ext)
    G = graph.build_graph()

    sg = graph.section_subgraph(G, pid, "sec1")
    concept_nodes = [n for n, d in sg.nodes(data=True) if d.get("kind") == "concept"]
    assert len(concept_nodes) == 2  # Alpha + Beta in sec1


def test_section_subgraph_unknown_section_returns_paper_only():
    """Unknown section_id -> subgraph contains only the paper node."""
    pid = "arxiv:2410.10009"
    ext = _minimal_extraction(concepts=["Alpha"], section_on_concepts=["sec1"])
    _seed_paper(pid, "Paper Unknown Section", ext)
    G = graph.build_graph()

    sg = graph.section_subgraph(G, pid, "nonexistent_section")
    assert pid in sg.nodes
    assert sg.number_of_nodes() == 1


def test_section_subgraph_unknown_paper_returns_empty_graph():
    """Unknown paper_id -> empty graph."""
    pid = "arxiv:2410.10010"
    ext = _minimal_extraction(concepts=["Alpha"], section_on_concepts=["sec1"])
    _seed_paper(pid, "Paper Known", ext)
    G = graph.build_graph()

    sg = graph.section_subgraph(G, "arxiv:9999.99999", "sec1")
    assert sg.number_of_nodes() == 0


def test_section_subgraph_includes_inter_entity_edges():
    """The returned subgraph includes edges among included nodes (not just paper->entity)."""
    # Build two papers that each have the same two concepts so they get a co_mentioned edge.
    pid1 = "arxiv:2410.10011"
    pid2 = "arxiv:2410.10012"
    ext = {
        "concepts": [
            {"name": "CoAlpha", "definition": "...", "section": "sec1"},
            {"name": "CoBeta", "definition": "...", "section": "sec1"},
        ],
        "methods": [], "datasets": [], "claims": [], "results": [], "related_work": [],
    }
    _seed_paper(pid1, "Paper Co A", ext)
    _seed_paper(pid2, "Paper Co B", ext)
    G = graph.build_graph()

    sg = graph.section_subgraph(G, pid1, "sec1")
    # Should have the paper + 2 concepts = 3 nodes, and the co_mentioned edge should appear.
    co_edges = [(u, v, d) for u, v, d in sg.edges(data=True)
                if d.get("relation") == "co_mentioned"]
    assert len(co_edges) >= 1, "expected co_mentioned edge inside subgraph"


# ---------------------------------------------------------------------------
# 5. graph_delta
# ---------------------------------------------------------------------------

def test_graph_delta_empty_when_identical():
    """graph_delta on the same graph returns empty lists."""
    G = graph.build_graph()
    delta = graph.graph_delta(G, G)
    assert delta["nodes_added"] == []
    assert delta["edges_added"] == []


def test_graph_delta_detects_new_nodes_and_edges():
    """graph_delta reports nodes/edges in new but not in old."""
    pid_a = "arxiv:2410.10013"
    _seed_paper(pid_a, "Paper Old", _minimal_extraction(concepts=["Alpha"]))
    old = graph.build_graph()

    pid_b = "arxiv:2410.10014"
    _seed_paper(pid_b, "Paper New", _minimal_extraction(concepts=["Beta"]))
    new = graph.build_graph()

    delta = graph.graph_delta(old, new)
    added_ids = {n["id"] for n in delta["nodes_added"]}
    # pid_b and the Beta concept node should appear
    assert pid_b in added_ids

    added_edge_targets = {(e["source"], e["target"], e["relation"]) for e in delta["edges_added"]}
    # Some contains-edge involving pid_b should be reported
    assert any(pid_b in (s, t) for s, t, _ in added_edge_targets)


def test_graph_delta_does_not_report_unchanged_nodes():
    """Nodes present in old are never reported in nodes_added."""
    pid_a = "arxiv:2410.10015"
    _seed_paper(pid_a, "Paper A", _minimal_extraction(concepts=["Alpha"]))
    old = graph.build_graph()
    new = graph.build_graph()  # same store state

    delta = graph.graph_delta(old, new)
    added_ids = {n["id"] for n in delta["nodes_added"]}
    assert pid_a not in added_ids


def test_graph_delta_new_edge_between_existing_nodes():
    """An edge between pre-existing nodes is still reported if it's new."""
    # Build old graph with two isolated papers (no related_work).
    pid_a = "arxiv:2410.10016"
    pid_b = "arxiv:2410.10017"
    ext_no_cite = {
        "concepts": [], "methods": [], "datasets": [], "claims": [], "results": [],
        "related_work": [],
    }
    _seed_paper(pid_a, "Citing Paper", ext_no_cite)
    _seed_paper(pid_b, "Target Paper", ext_no_cite)
    old = graph.build_graph()

    # Now update pid_a's extraction to cite pid_b.
    ext_cites = {
        "concepts": [], "methods": [], "datasets": [], "claims": [], "results": [],
        "related_work": ["Target Paper"],
    }
    store.save_extraction(pid_a, ext_cites, prompt_sha=prompts.extraction_prompt_sha256())
    new = graph.build_graph()

    delta = graph.graph_delta(old, new)
    added_ids = {n["id"] for n in delta["nodes_added"]}
    # No new nodes; but the cites edge should be new.
    assert pid_a not in added_ids
    assert pid_b not in added_ids
    edge_rels = {e["relation"] for e in delta["edges_added"]}
    assert "cites" in edge_rels


def test_graph_delta_node_entries_have_kind_label():
    """Each node entry in nodes_added has 'id', 'kind', 'label'."""
    pid = "arxiv:2410.10018"
    old = graph.build_graph()
    _seed_paper(pid, "Label Test", _minimal_extraction(concepts=["Zeta"]))
    new = graph.build_graph()

    delta = graph.graph_delta(old, new)
    assert delta["nodes_added"]
    for entry in delta["nodes_added"]:
        assert "id" in entry
        assert "kind" in entry
        assert "label" in entry


def test_graph_delta_sorted_deterministic():
    """graph_delta returns nodes sorted by id, edges sorted by (source, target, relation)."""
    old = graph.build_graph()
    for i in range(3):
        pid = f"arxiv:2410.2000{i}"
        _seed_paper(pid, f"Paper {i}", _minimal_extraction(concepts=[f"Concept{i}"]))
    new = graph.build_graph()

    delta = graph.graph_delta(old, new)
    ids = [n["id"] for n in delta["nodes_added"]]
    assert ids == sorted(ids), "nodes_added must be sorted by id"
    edges_keys = [(e["source"], e["target"], e["relation"]) for e in delta["edges_added"]]
    assert edges_keys == sorted(edges_keys), "edges_added must be sorted by (source, target, relation)"


# ---------------------------------------------------------------------------
# 6. Round-trip: save_graph / load_graph preserves new attrs
# ---------------------------------------------------------------------------

def test_save_load_graph_preserves_sections_and_strength():
    """save_graph / load_graph round-trip preserves sections and strength attrs."""
    pid = "arxiv:2410.10019"
    _seed_paper(pid, "Paper RoundTrip", _minimal_extraction())
    store.save_sections(pid, _sections_payload(["secA", "secB"]))
    store.save_strength(pid, _strength_payload(band="weak", color="#FF0000"))

    G1 = graph.build_graph()
    graph.save_graph(G1)
    G2 = graph.load_graph()

    node1 = G1.nodes[pid]
    node2 = G2.nodes[pid]
    assert node2.get("sections") == node1.get("sections")
    assert node2.get("strength_band") == node1.get("strength_band")
    assert node2.get("strength_color") == node1.get("strength_color")


def test_save_load_graph_preserves_contains_section():
    """save_graph / load_graph preserves section attr on contains-edges."""
    pid = "arxiv:2410.10020"
    ext = _minimal_extraction(concepts=["Alpha"], section_on_concepts=["secX"])
    _seed_paper(pid, "Paper Edge RoundTrip", ext)

    G1 = graph.build_graph()
    graph.save_graph(G1)
    G2 = graph.load_graph()

    contains_g2 = [
        d["section"] for u, v, d in G2.edges(data=True)
        if (u == pid or v == pid) and d.get("relation") == "contains"
    ]
    assert contains_g2 == ["secX"]
