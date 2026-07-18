"""Tests for research_companion.graph — pure construction, no LLM."""
from __future__ import annotations

import json

import networkx as nx

from research_companion import graph, prompts, store


def _seed_paper(paper_id: str, title: str, extraction: dict) -> store.PaperMetadata:
    """Helper: write a paper + its extraction to the store."""
    meta = store.PaperMetadata(
        paper_id=paper_id, title=title, authors=["Alice", "Bob"], year=2024,
        added_at="2026-01-01T00:00:00",
    )
    meta.save()
    store.save_extraction(paper_id, extraction, prompt_sha=prompts.extraction_prompt_sha256())
    return meta


def test_norm_collapses_variants():
    assert graph._norm("Graph RAG") == graph._norm("graphrag") == graph._norm("GraphRAG")
    assert graph._norm("BM25") == graph._norm("bm-25") == graph._norm("bm 25")


def test_build_graph_with_one_paper(sample_extraction: dict):
    _seed_paper("arxiv:2410.00001", "Paper A", sample_extraction)
    G = graph.build_graph()

    assert G.number_of_nodes() > 0
    # Paper node present.
    assert "arxiv:2410.00001" in G.nodes
    assert G.nodes["arxiv:2410.00001"]["kind"] == "paper"

    # Concepts/methods/datasets created and connected to paper.
    concept_ids = [n for n, d in G.nodes(data=True) if d.get("kind") == "concept"]
    assert len(concept_ids) == 2
    method_ids = [n for n, d in G.nodes(data=True) if d.get("kind") == "method"]
    assert len(method_ids) == 2
    dataset_ids = [n for n, d in G.nodes(data=True) if d.get("kind") == "dataset"]
    assert len(dataset_ids) >= 1  # 1 dataset, plus possibly stub from result

    for cid in concept_ids:
        assert G.has_edge("arxiv:2410.00001", cid)
        assert G.edges["arxiv:2410.00001", cid]["relation"] == "contains"


def test_build_graph_merges_duplicate_concepts():
    """Two papers each mention 'GraphRAG' — graph has ONE GraphRAG node, two contains edges."""
    extraction_a = {
        "concepts": [], "methods": [{"name": "GraphRAG", "description": "X"}],
        "datasets": [], "claims": [], "results": [], "related_work": [],
    }
    extraction_b = {
        "concepts": [], "methods": [{"name": "graphrag", "description": "Y"}],
        "datasets": [], "claims": [], "results": [], "related_work": [],
    }
    _seed_paper("arxiv:2410.00001", "Paper A", extraction_a)
    _seed_paper("arxiv:2410.00002", "Paper B", extraction_b)

    G = graph.build_graph()
    method_ids = [n for n, d in G.nodes(data=True) if d.get("kind") == "method"]
    assert len(method_ids) == 1, f"expected merged GraphRAG, got {method_ids}"
    mid = method_ids[0]
    # Both papers connect to the same method node.
    assert G.has_edge("arxiv:2410.00001", mid)
    assert G.has_edge("arxiv:2410.00002", mid)
    # Canonical label is whichever we saw first ("GraphRAG", not "graphrag").
    assert G.nodes[mid]["label"] == "GraphRAG"


def test_entity_nodes_carry_paper_provenance():
    """Every entity node tracks the sorted set of contributing paper_ids + count."""
    ext_a = {
        "concepts": [{"name": "RAG", "definition": "..."}],
        "methods": [{"name": "GraphRAG", "description": "X"}],
        "datasets": [{"name": "HotpotQA", "description": "..."}],
        "claims": [], "results": [], "related_work": [],
    }
    ext_b = {
        "concepts": [{"name": "RAG", "definition": "..."}],
        "methods": [{"name": "graphrag", "description": "Y"}],
        "datasets": [], "claims": [], "results": [], "related_work": [],
    }
    # Seed out of order to prove the papers list is sorted, not insertion-ordered.
    _seed_paper("arxiv:2410.00002", "Paper B", ext_b)
    _seed_paper("arxiv:2410.00001", "Paper A", ext_a)

    G = graph.build_graph()

    # Concept + method shared by both papers -> both ids, sorted.
    concept_id = graph._node_id("concept", graph._norm("RAG"))
    assert G.nodes[concept_id]["papers"] == ["arxiv:2410.00001", "arxiv:2410.00002"]
    assert G.nodes[concept_id]["paper_count"] == 2
    method_id = graph._node_id("method", graph._norm("GraphRAG"))
    assert G.nodes[method_id]["papers"] == ["arxiv:2410.00001", "arxiv:2410.00002"]
    assert G.nodes[method_id]["paper_count"] == 2

    # Single-paper dataset.
    dataset_id = graph._node_id("dataset", graph._norm("HotpotQA"))
    assert G.nodes[dataset_id]["papers"] == ["arxiv:2410.00001"]
    assert G.nodes[dataset_id]["paper_count"] == 1

    # Paper nodes carry no provenance attrs (additive to entities only).
    assert "paper_count" not in G.nodes["arxiv:2410.00001"]
    assert "papers" not in G.nodes["arxiv:2410.00001"]


def test_serialize_graph_carries_entity_provenance(sample_extraction: dict):
    """serialize_graph bundles papers/paper_count into each entity node's attrs."""
    _seed_paper("arxiv:2410.00001", "Paper A", sample_extraction)
    G = graph.build_graph()
    data = graph.serialize_graph(G)

    entity = next(n for n in data["nodes"] if n["kind"] == "concept")
    assert entity["attrs"]["paper_count"] == 1
    assert entity["attrs"]["papers"] == ["arxiv:2410.00001"]

    paper = next(n for n in data["nodes"] if n["kind"] == "paper")
    assert "paper_count" not in paper["attrs"]
    assert "papers" not in paper["attrs"]


def test_build_graph_co_mentioned_edges():
    """Two concepts appearing in 2+ papers get a co_mentioned edge."""
    ext = {
        "concepts": [
            {"name": "Knowledge graph", "definition": "..."},
            {"name": "RAG", "definition": "..."},
        ],
        "methods": [], "datasets": [], "claims": [], "results": [], "related_work": [],
    }
    _seed_paper("arxiv:2410.00001", "A", ext)
    _seed_paper("arxiv:2410.00002", "B", ext)

    G = graph.build_graph()
    co_edges = [(u, v) for u, v, d in G.edges(data=True) if d.get("relation") == "co_mentioned"]
    assert len(co_edges) == 1
    weight = G.edges[co_edges[0]]["weight"]
    assert weight == 2  # appeared together in 2 papers


def test_cites_edges_from_related_work():
    """When related_work mentions a paper title we already have, add a 'cites' edge."""
    ext_a = {
        "concepts": [], "methods": [], "datasets": [], "claims": [], "results": [],
        "related_work": ["GraphRAG by Edge et al."],
    }
    ext_b = {
        "concepts": [], "methods": [], "datasets": [], "claims": [], "results": [],
        "related_work": [],
    }
    _seed_paper("arxiv:2410.00001", "A new paper using GraphRAG", ext_a)
    _seed_paper("arxiv:2410.00002", "GraphRAG by Edge et al.", ext_b)

    G = graph.build_graph()
    cite_edges = [(u, v) for u, v, d in G.edges(data=True) if d.get("relation") == "cites"]
    assert len(cite_edges) == 1
    # Edge from A to B (A cites B).
    assert {"arxiv:2410.00001", "arxiv:2410.00002"} == {cite_edges[0][0], cite_edges[0][1]}


def test_save_load_graph_roundtrip(sample_extraction: dict):
    _seed_paper("arxiv:2410.00001", "Paper A", sample_extraction)
    G1 = graph.build_graph()
    graph.save_graph(G1)
    G2 = graph.load_graph()
    assert G1.number_of_nodes() == G2.number_of_nodes()
    assert G1.number_of_edges() == G2.number_of_edges()


def test_graph_stats(sample_extraction: dict):
    _seed_paper("arxiv:2410.00001", "Paper A", sample_extraction)
    G = graph.build_graph()
    stats = graph.graph_stats(G)
    assert stats["nodes_total"] > 0
    assert stats["node_paper"] == 1
    assert stats["node_concept"] >= 1
    assert stats["node_method"] >= 1
    assert "edge_contains" in stats


def test_load_graph_reads_edges_keyed_file(tmp_path):
    """networkx >= 3.6 defaults node-link JSON to an "edges" key; load_graph must
    read such files instead of KeyError-ing (CI runs a newer networkx than dev)."""
    p = tmp_path / "graph.json"
    p.write_text(json.dumps({
        "directed": False, "multigraph": False, "graph": {},
        "nodes": [{"id": "a"}, {"id": "b"}],
        "edges": [{"source": "a", "target": "b"}],
    }), encoding="utf-8")
    G = graph.load_graph(p)
    assert G.number_of_nodes() == 2
    assert G.has_edge("a", "b")


def test_load_graph_corrupt_json_returns_empty(tmp_path):
    """A corrupt/legacy graph.json must degrade to an empty graph, not raise.

    The ingest graph stage reads the prior graph as its delta baseline; a bad
    migrated graph.json in 'Main' would otherwise throw and fail the ingest."""
    p = tmp_path / "graph.json"
    p.write_text("not valid json }{", encoding="utf-8")
    G = graph.load_graph(p)
    assert G.number_of_nodes() == 0
    assert G.number_of_edges() == 0


def test_list_papers_tie_break_is_deterministic():
    """Equal added_at must not fall back to filesystem iteration order (differs
    by OS): ties break by paper_id ascending, so first-seen labels are stable."""
    for pid in ("arxiv:2410.00002", "arxiv:2410.00001", "arxiv:2410.00003"):
        store.PaperMetadata(
            paper_id=pid, title=pid, authors=["A"], year=2024,
            added_at="2026-01-01T00:00:00",
        ).save()
    ids = [m.paper_id for m in store.list_papers()]
    assert ids == ["arxiv:2410.00001", "arxiv:2410.00002", "arxiv:2410.00003"]


def test_serialize_includes_polarity_when_present():
    G = nx.Graph()
    G.add_node("p:a", kind="paper")
    G.add_node("p:b", kind="paper")
    G.add_edge("p:a", "p:b", relation="cites", polarity="support")
    G.add_edge("p:a", "p:b")  # same pair; ensure attr persists
    payload = graph.serialize_graph(G)
    edge = [e for e in payload["edges"] if e.get("relation") == "cites"][0]
    assert edge["polarity"] == "support"


def test_serialize_includes_evidence_when_present():
    G = nx.Graph()
    G.add_node("p:a", kind="paper")
    G.add_node("p:b", kind="paper")
    G.add_edge("p:a", "p:b", relation="cites", polarity="support", evidence="We build on this.")
    payload = graph.serialize_graph(G)
    edge = [e for e in payload["edges"] if e.get("relation") == "cites"][0]
    assert edge["evidence"] == "We build on this."


def test_serialize_omits_evidence_when_absent():
    G = nx.Graph()
    G.add_node("p:a", kind="paper")
    G.add_node("p:b", kind="paper")
    G.add_edge("p:a", "p:b", relation="cites", polarity="support")
    payload = graph.serialize_graph(G)
    edge = [e for e in payload["edges"] if e.get("relation") == "cites"][0]
    assert "evidence" not in edge


def test_stats_break_cites_down_by_polarity():
    G = nx.Graph()
    G.add_node("a", kind="paper")
    G.add_node("b", kind="paper")
    G.add_node("c", kind="paper")
    G.add_edge("a", "b", relation="cites", polarity="contrast")
    G.add_edge("a", "c", relation="cites")  # untyped
    stats = graph.graph_stats(G)
    assert stats.get("edge_cites_contrast") == 1
