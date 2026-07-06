"""Tests for research_companion.views — saved-subgraph CRUD module."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import networkx as nx
import pytest

from research_companion.views import (
    ViewError,
    delete_view,
    get_view,
    list_views,
    save_view,
    update_view,
    view_graph,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FIXED_NOW = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
_FIXED_NOW2 = datetime(2026, 1, 15, 12, 0, 1, tzinfo=timezone.utc)

_VALID_SOURCE = {"type": "ask", "query": "What is RAG?"}


# ---------------------------------------------------------------------------
# save / list roundtrip
# ---------------------------------------------------------------------------


def test_save_list_roundtrip():
    v = save_view("My View", source=_VALID_SOURCE, node_ids=["n1", "n2"], now=_FIXED_NOW)
    assert v["name"] == "My View"
    assert v["node_ids"] == ["n1", "n2"]
    assert v["source"] == _VALID_SOURCE
    assert v["pinned"] is False

    views = list_views()
    assert len(views) == 1
    assert views[0]["view_id"] == v["view_id"]


def test_save_multiple_views():
    v1 = save_view("View A", source=_VALID_SOURCE, node_ids=["n1"], now=_FIXED_NOW)
    v2 = save_view("View B", source={"type": "section"}, node_ids=["n2"], now=_FIXED_NOW2)
    views = list_views()
    assert len(views) == 2
    ids = [v["view_id"] for v in views]
    assert v1["view_id"] in ids
    assert v2["view_id"] in ids


def test_list_empty_when_none():
    assert list_views() == []


# ---------------------------------------------------------------------------
# Ordering: pinned first, then created_at desc
# ---------------------------------------------------------------------------


def test_list_pinned_first():
    t1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    t2 = datetime(2026, 1, 2, tzinfo=timezone.utc)
    t3 = datetime(2026, 1, 3, tzinfo=timezone.utc)

    save_view("Earliest unpinned", source=_VALID_SOURCE, node_ids=["x"], now=t1)
    v_pinned = save_view("Pinned", source=_VALID_SOURCE, node_ids=["y"], pinned=True, now=t2)
    save_view("Latest unpinned", source=_VALID_SOURCE, node_ids=["z"], now=t3)

    views = list_views()
    assert views[0]["view_id"] == v_pinned["view_id"]


def test_list_created_at_desc_for_unpinned():
    t1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    t2 = datetime(2026, 1, 2, tzinfo=timezone.utc)
    t3 = datetime(2026, 1, 3, tzinfo=timezone.utc)

    v1 = save_view("First", source=_VALID_SOURCE, node_ids=["a"], now=t1)
    v2 = save_view("Second", source=_VALID_SOURCE, node_ids=["b"], now=t2)
    v3 = save_view("Third", source=_VALID_SOURCE, node_ids=["c"], now=t3)

    views = list_views()
    # Newest first for unpinned
    assert views[0]["view_id"] == v3["view_id"]
    assert views[1]["view_id"] == v2["view_id"]
    assert views[2]["view_id"] == v1["view_id"]


def test_list_pinned_then_unpinned_desc():
    t1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    t2 = datetime(2026, 1, 2, tzinfo=timezone.utc)
    t3 = datetime(2026, 1, 3, tzinfo=timezone.utc)
    t4 = datetime(2026, 1, 4, tzinfo=timezone.utc)

    v_u1 = save_view("Unpinned old", source=_VALID_SOURCE, node_ids=["a"], now=t1)
    save_view("Pinned early", source=_VALID_SOURCE, node_ids=["b"], pinned=True, now=t2)
    v_u2 = save_view("Unpinned new", source=_VALID_SOURCE, node_ids=["c"], now=t3)
    save_view("Pinned late", source=_VALID_SOURCE, node_ids=["d"], pinned=True, now=t4)

    views = list_views()
    assert views[0]["pinned"] is True
    assert views[1]["pinned"] is True
    # Then unpinned, newest first
    assert views[2]["pinned"] is False
    assert views[3]["pinned"] is False
    assert views[2]["view_id"] == v_u2["view_id"]
    assert views[3]["view_id"] == v_u1["view_id"]


# ---------------------------------------------------------------------------
# get_view
# ---------------------------------------------------------------------------


def test_get_view_known():
    v = save_view("Test", source=_VALID_SOURCE, node_ids=["n1"], now=_FIXED_NOW)
    got = get_view(v["view_id"])
    assert got is not None
    assert got["view_id"] == v["view_id"]
    assert got["name"] == "Test"


def test_get_view_unknown_returns_none():
    assert get_view("view_nonexistent") is None


# ---------------------------------------------------------------------------
# Validation: ViewError cases
# ---------------------------------------------------------------------------


def test_save_empty_name_raises():
    with pytest.raises(ViewError):
        save_view("", source=_VALID_SOURCE, node_ids=["n1"])


def test_save_whitespace_only_name_raises():
    with pytest.raises(ViewError):
        save_view("   ", source=_VALID_SOURCE, node_ids=["n1"])


def test_save_empty_node_ids_raises():
    with pytest.raises(ViewError):
        save_view("Valid", source=_VALID_SOURCE, node_ids=[])


def test_save_bad_source_type_raises():
    with pytest.raises(ViewError):
        save_view("Valid", source={"type": "unknown_type"}, node_ids=["n1"])


def test_save_missing_source_type_raises():
    with pytest.raises(ViewError):
        save_view("Valid", source={"query": "no type"}, node_ids=["n1"])


@pytest.mark.parametrize("src_type", ["ask", "section", "manual", "compare"])
def test_save_all_valid_source_types(src_type):
    src = {"type": src_type}
    v = save_view(f"View {src_type}", source=src, node_ids=["n1"], now=_FIXED_NOW)
    assert v["source"]["type"] == src_type


# ---------------------------------------------------------------------------
# ID determinism and collision suffix
# ---------------------------------------------------------------------------


def test_id_determinism_with_injected_now():
    v1 = save_view("My View", source=_VALID_SOURCE, node_ids=["n1"], now=_FIXED_NOW)
    # Delete then re-save same name + same now => same base id
    delete_view(v1["view_id"])
    v2 = save_view("My View", source=_VALID_SOURCE, node_ids=["n2"], now=_FIXED_NOW)
    assert v1["view_id"] == v2["view_id"]


def test_collision_suffix():
    # Save two views with same name and same now
    v1 = save_view("Collision", source=_VALID_SOURCE, node_ids=["n1"], now=_FIXED_NOW)
    v2 = save_view("Collision", source=_VALID_SOURCE, node_ids=["n2"], now=_FIXED_NOW)
    assert v1["view_id"] != v2["view_id"]
    assert v2["view_id"] == v1["view_id"] + "-2"


# ---------------------------------------------------------------------------
# update_view
# ---------------------------------------------------------------------------


def test_update_view_name():
    v = save_view("Old Name", source=_VALID_SOURCE, node_ids=["n1"], now=_FIXED_NOW)
    updated = update_view(v["view_id"], name="New Name")
    assert updated["name"] == "New Name"
    assert get_view(v["view_id"])["name"] == "New Name"


def test_update_view_pin():
    v = save_view("View", source=_VALID_SOURCE, node_ids=["n1"], now=_FIXED_NOW)
    assert v["pinned"] is False
    updated = update_view(v["view_id"], pinned=True)
    assert updated["pinned"] is True


def test_update_view_partial_name_only():
    v = save_view("View", source=_VALID_SOURCE, node_ids=["n1"], now=_FIXED_NOW, pinned=True)
    updated = update_view(v["view_id"], name="Renamed")
    # pinned should be unchanged
    assert updated["pinned"] is True
    assert updated["name"] == "Renamed"


def test_update_view_partial_pinned_only():
    v = save_view("View", source=_VALID_SOURCE, node_ids=["n1"], now=_FIXED_NOW)
    updated = update_view(v["view_id"], pinned=True)
    # name should be unchanged
    assert updated["name"] == "View"
    assert updated["pinned"] is True


def test_update_view_unknown_raises():
    with pytest.raises(ViewError):
        update_view("view_nope", name="X")


def test_update_view_empty_name_raises():
    v = save_view("View", source=_VALID_SOURCE, node_ids=["n1"], now=_FIXED_NOW)
    with pytest.raises(ViewError):
        update_view(v["view_id"], name="")


def test_update_view_whitespace_name_raises():
    v = save_view("View", source=_VALID_SOURCE, node_ids=["n1"], now=_FIXED_NOW)
    with pytest.raises(ViewError):
        update_view(v["view_id"], name="   ")


# ---------------------------------------------------------------------------
# delete_view
# ---------------------------------------------------------------------------


def test_delete_view_true_when_exists():
    v = save_view("View", source=_VALID_SOURCE, node_ids=["n1"], now=_FIXED_NOW)
    result = delete_view(v["view_id"])
    assert result is True
    assert get_view(v["view_id"]) is None


def test_delete_view_false_when_unknown():
    assert delete_view("view_missing") is False


# ---------------------------------------------------------------------------
# source passthrough
# ---------------------------------------------------------------------------


def test_source_optional_fields_pass_through():
    src = {"type": "ask", "query": "my question", "section_id": "s1",
           "paper_ids": ["p1", "p2"]}
    v = save_view("Rich source", source=src, node_ids=["n1"], now=_FIXED_NOW)
    assert v["source"]["query"] == "my question"
    assert v["source"]["section_id"] == "s1"
    assert v["source"]["paper_ids"] == ["p1", "p2"]


# ---------------------------------------------------------------------------
# view_graph
# ---------------------------------------------------------------------------


def _make_graph():
    """Build a simple graph with 4 nodes and 3 edges for testing."""
    G = nx.Graph()
    G.add_node("n1", kind="paper", label="Paper One")
    G.add_node("n2", kind="concept", label="Concept X")
    G.add_node("n3", kind="method", label="Method Y")
    G.add_node("n4", kind="dataset", label="Dataset Z")
    G.add_edge("n1", "n2", relation="contains", weight=1)
    G.add_edge("n2", "n3", relation="co_mentioned", weight=2)
    G.add_edge("n3", "n4", relation="uses", weight=1)
    return G


def test_view_graph_induced_subgraph():
    v = save_view("Sub", source=_VALID_SOURCE, node_ids=["n1", "n2", "n3"], now=_FIXED_NOW)
    G = _make_graph()
    result = view_graph(v["view_id"], graph=G)

    node_ids = {n["id"] for n in result["nodes"]}
    assert node_ids == {"n1", "n2", "n3"}

    # Edge n3->n4 should be excluded (n4 not in subgraph)
    edge_set = {(e["from"], e["to"]) for e in result["edges"]}
    assert ("n3", "n4") not in edge_set and ("n4", "n3") not in edge_set


def test_view_graph_includes_inter_node_edges():
    v = save_view("Sub", source=_VALID_SOURCE, node_ids=["n1", "n2", "n3"], now=_FIXED_NOW)
    G = _make_graph()
    result = view_graph(v["view_id"], graph=G)

    # n1-n2 and n2-n3 edges should be present
    edge_set = {frozenset((e["from"], e["to"])) for e in result["edges"]}
    assert frozenset({"n1", "n2"}) in edge_set
    assert frozenset({"n2", "n3"}) in edge_set


def test_view_graph_missing_node_ids_honest_and_sorted():
    v = save_view("Sub", source=_VALID_SOURCE,
                  node_ids=["n1", "missing_b", "missing_a"], now=_FIXED_NOW)
    G = _make_graph()
    result = view_graph(v["view_id"], graph=G)

    assert result["missing_node_ids"] == ["missing_a", "missing_b"]
    node_ids = {n["id"] for n in result["nodes"]}
    assert "missing_a" not in node_ids
    assert "missing_b" not in node_ids
    assert "n1" in node_ids


def test_view_graph_node_shape():
    v = save_view("Sub", source=_VALID_SOURCE, node_ids=["n1", "n2"], now=_FIXED_NOW)
    G = _make_graph()
    result = view_graph(v["view_id"], graph=G)

    for node in result["nodes"]:
        assert "id" in node
        assert "kind" in node
        assert "label" in node
        assert "sections" in node
        assert "attrs" in node
        # strength is optional but key must exist
        assert "strength" in node


def test_view_graph_edge_shape():
    v = save_view("Sub", source=_VALID_SOURCE, node_ids=["n1", "n2"], now=_FIXED_NOW)
    G = _make_graph()
    result = view_graph(v["view_id"], graph=G)

    for edge in result["edges"]:
        assert "from" in edge
        assert "to" in edge
        assert "relation" in edge
        assert "weight" in edge


def test_view_graph_result_shape():
    v = save_view("Sub", source=_VALID_SOURCE, node_ids=["n1"], now=_FIXED_NOW)
    G = _make_graph()
    result = view_graph(v["view_id"], graph=G)

    assert "nodes" in result
    assert "edges" in result
    assert "view" in result
    assert "missing_node_ids" in result
    assert result["view"]["view_id"] == v["view_id"]


def test_view_graph_unknown_view_raises():
    G = _make_graph()
    with pytest.raises(ViewError):
        view_graph("view_none", graph=G)


def test_view_graph_empty_intersection():
    """All node_ids missing -> empty nodes + all ids in missing_node_ids, no crash."""
    v = save_view("Empty", source=_VALID_SOURCE,
                  node_ids=["ghost1", "ghost2"], now=_FIXED_NOW)
    G = _make_graph()
    result = view_graph(v["view_id"], graph=G)

    assert result["nodes"] == []
    assert result["edges"] == []
    assert sorted(result["missing_node_ids"]) == ["ghost1", "ghost2"]


def test_view_graph_no_crash_empty_graph():
    """Empty graph intersection with no node_ids in G -> no crash."""
    G = nx.Graph()  # empty
    v = save_view("Empty graph", source=_VALID_SOURCE, node_ids=["n1"], now=_FIXED_NOW)
    result = view_graph(v["view_id"], graph=G)

    assert result["nodes"] == []
    assert "n1" in result["missing_node_ids"]


# ---------------------------------------------------------------------------
# Corrupt saved_views.json -> list_views returns [] (never raises)
# ---------------------------------------------------------------------------


def test_corrupt_views_json_returns_empty(isolated_papergraph_dir: Path):
    """Writing garbage JSON to saved_views.json should make list_views return []."""
    p = isolated_papergraph_dir / "saved_views.json"
    p.write_text("INVALID JSON {{{{", encoding="utf-8")

    result = list_views()
    assert result == []


def test_truncated_views_json_returns_empty(isolated_papergraph_dir: Path):
    p = isolated_papergraph_dir / "saved_views.json"
    p.write_text('{"version": 1, "views":', encoding="utf-8")

    result = list_views()
    assert result == []


def test_wrong_type_views_json_returns_empty(isolated_papergraph_dir: Path):
    """If views is not a list, list_views returns []."""
    p = isolated_papergraph_dir / "saved_views.json"
    p.write_text(json.dumps({"version": 1, "views": "not a list"}), encoding="utf-8")

    result = list_views()
    assert result == []
