"""Saved-subgraph views: persistent named views over the knowledge graph.

Researchers save the subgraphs their questions produce and reload them later.

File layout: papergraph_dir()/saved_views.json
Payload: {"version": 1, "views": [...]}

Each view dict:
  view_id       str   "view_" + sha256(name + "|" + iso_now)[:8]
  name          str   display name (stripped)
  source        dict  {"type": one of ask/section/manual/compare, ...}
  node_ids      list  node IDs in the subgraph
  pinned        bool
  created_at    str   ISO-8601 UTC timestamp
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from research_companion.store import papergraph_dir

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_VALID_SOURCE_TYPES = {"ask", "section", "manual", "compare"}
_FILE_VERSION = 1


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ViewError(ValueError):
    """Raised when a views operation cannot be completed."""


# ---------------------------------------------------------------------------
# File I/O helpers (same conventions as store.py: indent=2, ensure_ascii=False)
# ---------------------------------------------------------------------------


def _views_path() -> Path:
    return papergraph_dir() / "saved_views.json"


def _load_all() -> list[dict]:
    """Load all views from saved_views.json.

    Returns an empty list if the file is missing, corrupt, or structurally invalid.
    Never raises.
    """
    p = _views_path()
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        views = data.get("views", [])
        if not isinstance(views, list):
            return []
        return views
    except (json.JSONDecodeError, ValueError, AttributeError):
        return []


def _save_all(views: list[dict]) -> None:
    """Persist the views list to saved_views.json."""
    p = _views_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": _FILE_VERSION, "views": views}
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# Node/edge serialization — delegates to the shared serialize_graph in graph.py.
# graph.py imports neither views nor lab_api, so this is cycle-free.
# ---------------------------------------------------------------------------


def _serialize_graph(G: Any, node_ids: list[str]) -> tuple[list[dict], list[dict], list[str]]:
    """Return (nodes, edges, missing_node_ids) for the induced subgraph.

    Only nodes whose IDs appear in node_ids AND in G are included.
    Edges are those both of whose endpoints are in the included set.
    missing_node_ids is sorted.
    """
    from research_companion.graph import serialize_graph as _sg

    included = [nid for nid in node_ids if nid in G.nodes]
    missing = sorted(nid for nid in node_ids if nid not in G.nodes)

    # Induced subgraph preserves all edges between included nodes
    sub = G.subgraph(included)

    serialized = _sg(sub, seq=0)
    return serialized["nodes"], serialized["edges"], missing


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def list_views() -> list[dict]:
    """Return all saved views: pinned first, then created_at descending.

    Returns [] when none exist; never raises.
    """
    views = _load_all()
    pinned = [v for v in views if v.get("pinned")]
    unpinned = [v for v in views if not v.get("pinned")]
    pinned.sort(key=lambda v: v.get("created_at", ""), reverse=True)
    unpinned.sort(key=lambda v: v.get("created_at", ""), reverse=True)
    return pinned + unpinned


def get_view(view_id: str) -> dict | None:
    """Return the view dict for view_id, or None if not found."""
    for v in _load_all():
        if v.get("view_id") == view_id:
            return v
    return None


def save_view(
    name: str,
    *,
    source: dict,
    node_ids: list[str],
    pinned: bool = False,
    now: datetime | None = None,
) -> dict:
    """Create and persist a new saved view.

    Validates:
    - name is non-empty after stripping
    - node_ids is non-empty
    - source["type"] is one of {ask, section, manual, compare}

    view_id = "view_" + sha256(name + "|" + iso_now)[:8].
    On collision, appends "-2".

    Args:
        name:      Display name (will be stripped).
        source:    Dict with at least "type" key.
        node_ids:  Non-empty list of node IDs forming the subgraph.
        pinned:    Whether the view is pinned.
        now:       Injectable datetime for deterministic testing.

    Returns:
        The newly created view dict.

    Raises:
        ViewError: If validation fails.
    """
    name = name.strip()
    if not name:
        raise ViewError("name must be non-empty")
    if not node_ids:
        raise ViewError("node_ids must be non-empty")
    src_type = source.get("type") if isinstance(source, dict) else None
    if src_type not in _VALID_SOURCE_TYPES:
        raise ViewError(
            f"source['type'] must be one of {sorted(_VALID_SOURCE_TYPES)!r}, got {src_type!r}"
        )

    if now is None:
        now = datetime.now(timezone.utc)
    iso_now = now.isoformat()

    # Compute view_id
    raw = f"{name}|{iso_now}"
    base_id = "view_" + hashlib.sha256(raw.encode()).hexdigest()[:8]

    views = _load_all()
    existing_ids = {v.get("view_id") for v in views}

    view_id = base_id
    if view_id in existing_ids:
        view_id = base_id + "-2"

    view: dict[str, Any] = {
        "view_id": view_id,
        "name": name,
        "source": source,
        "node_ids": list(node_ids),
        "pinned": bool(pinned),
        "created_at": iso_now,
    }
    views.append(view)
    _save_all(views)
    return view


def update_view(
    view_id: str,
    *,
    name: str | None = None,
    pinned: bool | None = None,
) -> dict:
    """Partially update a saved view.

    Args:
        view_id: ID of the view to update.
        name:    New name (must be non-empty if provided).
        pinned:  New pinned state.

    Returns:
        The updated view dict.

    Raises:
        ViewError: If view_id not found or name is empty.
    """
    views = _load_all()
    for i, v in enumerate(views):
        if v.get("view_id") == view_id:
            if name is not None:
                name = name.strip()
                if not name:
                    raise ViewError("name must be non-empty")
                v = dict(v)
                v["name"] = name
            if pinned is not None:
                v = dict(v)
                v["pinned"] = bool(pinned)
            views[i] = v
            _save_all(views)
            return v
    raise ViewError(f"No view found with id {view_id!r}")


def delete_view(view_id: str) -> bool:
    """Delete a view by ID.

    Returns:
        True if removed, False if not found.
    """
    views = _load_all()
    new_views = [v for v in views if v.get("view_id") != view_id]
    if len(new_views) == len(views):
        return False
    _save_all(new_views)
    return True


def view_graph(view_id: str, *, graph: Any = None) -> dict:
    """Return the induced subgraph for a saved view.

    Args:
        view_id: ID of the view to render.
        graph:   Injectable graph (nx.Graph). If None, loads from store.

    Returns:
        {
            "nodes": [...],           # node dicts with id/kind/label/sections/strength/attrs
            "edges": [...],           # edge dicts with from/to/relation/weight
            "view": <view dict>,
            "missing_node_ids": [...] # IDs in view.node_ids not found in graph, sorted
        }

    Raises:
        ViewError: If view_id is not found.
    """
    view = get_view(view_id)
    if view is None:
        raise ViewError(f"No view found with id {view_id!r}")

    if graph is None:
        from research_companion.graph import load_graph
        graph = load_graph()

    node_ids = view.get("node_ids", [])
    nodes, edges, missing = _serialize_graph(graph, node_ids)

    return {
        "nodes": nodes,
        "edges": edges,
        "view": view,
        "missing_node_ids": missing,
    }
