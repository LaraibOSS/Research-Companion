"""Deterministic research timeline builder.

Builds a timeline from the existing knowledge graph + paper years:
which concepts/methods/datasets appeared when, which paper introduced each,
and how they recur across years.

This module is a pure function over its inputs — no I/O when graph+papers
are injected, never raises on an empty or malformed graph.
"""
from __future__ import annotations

from typing import Any

_ENTITY_KINDS: frozenset[str] = frozenset({"concept", "method", "dataset"})


def build_timeline(
    *,
    min_appearances: int = 1,
    max_tracks: int = 50,
    graph: Any = None,
    papers: Any = None,
) -> dict:
    """Build a deterministic research timeline from the knowledge graph.

    Parameters
    ----------
    min_appearances:
        Minimum number of papers (with a year) that must mention an entity for it
        to appear as a track.  Default 1 — include everything that appears at least
        once.
    max_tracks:
        Hard cap on the number of tracks returned.  When the cap is hit the
        ``truncated_tracks`` key in the result is set to the number of tracks that
        were dropped.
    graph:
        Injectable NetworkX graph (for tests / offline use).  When None the live
        graph is loaded via ``research_companion.graph.load_graph()``.
    papers:
        Injectable list of ``PaperMetadata``-like objects (for tests).  When None
        ``research_companion.store.list_papers()`` is called.

    Returns
    -------
    dict with exact shape::

        {
            "years": [int, ...],               # sorted unique years, ascending
            "papers_per_year": [{"year": int, "count": int}, ...],  # ascending
            "tracks": [
                {
                    "kind": str,               # concept | method | dataset
                    "label": str,
                    "first_seen": int,
                    "introduced_by": str,      # paper_id
                    "appearances": [{"paper_id": str, "year": int}, ...]  # asc (year, paper_id)
                },
                ...
            ],
            "skipped_papers_without_year": int,
            "truncated_tracks": int,
        }
    """
    # ------------------------------------------------------------------ #
    # 1. Load defaults if not injected                                    #
    # ------------------------------------------------------------------ #
    if graph is None:
        from research_companion.graph import load_graph
        graph = load_graph()
    if papers is None:
        from research_companion.store import list_papers
        papers = list_papers()

    # ------------------------------------------------------------------ #
    # 2. Build paper_id -> (year, added_at) map; count skipped            #
    # ------------------------------------------------------------------ #
    paper_year: dict[str, int] = {}
    paper_added_at: dict[str, str] = {}
    skipped_papers_without_year = 0

    for meta in papers:
        year = getattr(meta, "year", None)
        added_at = getattr(meta, "added_at", "") or ""
        pid = getattr(meta, "paper_id", None)
        if pid is None:
            continue
        if year is None:
            skipped_papers_without_year += 1
        else:
            paper_year[pid] = int(year)
            paper_added_at[pid] = added_at

    # ------------------------------------------------------------------ #
    # 3. papers_per_year from ALL papers with years                       #
    # ------------------------------------------------------------------ #
    year_counts: dict[int, int] = {}
    for y in paper_year.values():
        year_counts[y] = year_counts.get(y, 0) + 1
    papers_per_year = [
        {"year": y, "count": year_counts[y]}
        for y in sorted(year_counts)
    ]

    # ------------------------------------------------------------------ #
    # 4. Enumerate entity nodes + their appearances                       #
    # ------------------------------------------------------------------ #
    # entity_node_id -> list of (paper_id, year)
    entity_appearances: dict[str, list[tuple[str, int]]] = {}
    entity_kind: dict[str, str] = {}
    entity_label: dict[str, str] = {}

    try:
        nodes_data = list(graph.nodes(data=True))
    except Exception:
        nodes_data = []

    for node_id, attrs in nodes_data:
        kind = attrs.get("kind", "")
        if kind not in _ENTITY_KINDS:
            continue
        entity_kind[node_id] = kind
        entity_label[node_id] = attrs.get("label", str(node_id))
        entity_appearances[node_id] = []

    # Walk contains edges from papers to entity nodes
    try:
        edges_data = list(graph.edges(data=True))
    except Exception:
        edges_data = []

    for u, v, edge_attrs in edges_data:
        relation = edge_attrs.get("relation", "")
        if relation != "contains":
            continue
        # Edges may go either direction in NetworkX undirected graphs;
        # the paper is whichever endpoint has kind=="paper".
        paper_id: str | None = None
        entity_id: str | None = None

        u_kind = _get_node_kind(graph, u)
        v_kind = _get_node_kind(graph, v)

        if u_kind == "paper" and v_kind in _ENTITY_KINDS:
            paper_id = u
            entity_id = v
        elif v_kind == "paper" and u_kind in _ENTITY_KINDS:
            paper_id = v
            entity_id = u
        else:
            continue

        if paper_id not in paper_year:
            # Paper has no year — skip this appearance
            continue
        if entity_id not in entity_appearances:
            continue

        year = paper_year[paper_id]
        entity_appearances[entity_id].append((paper_id, year))

    # ------------------------------------------------------------------ #
    # 5. Build tracks                                                      #
    # ------------------------------------------------------------------ #
    raw_tracks: list[dict] = []

    for node_id, appearances in entity_appearances.items():
        if len(appearances) < min_appearances:
            continue

        # Deduplicate appearances: same paper may produce duplicate edges
        seen: set[tuple[str, int]] = set()
        unique_appearances: list[tuple[str, int]] = []
        for pid, yr in appearances:
            key = (pid, yr)
            if key not in seen:
                seen.add(key)
                unique_appearances.append((pid, yr))

        if len(unique_appearances) < min_appearances:
            continue

        # Determine first_seen and introduced_by (deterministic tie-break)
        first_seen_year = min(yr for _, yr in unique_appearances)
        candidates = [
            (pid, paper_added_at.get(pid, ""), pid)
            for pid, yr in unique_appearances
            if yr == first_seen_year
        ]
        # Sort: (added_at asc, paper_id lex asc) — earlier added_at wins; lex tie-break
        candidates.sort(key=lambda t: (t[1], t[2]))
        introduced_by = candidates[0][0]

        # Sort appearances ascending by (year, paper_id)
        sorted_appearances = sorted(unique_appearances, key=lambda t: (t[1], t[0]))
        appearances_list = [{"paper_id": pid, "year": yr} for pid, yr in sorted_appearances]

        raw_tracks.append({
            "kind": entity_kind[node_id],
            "label": entity_label[node_id],
            "first_seen": first_seen_year,
            "introduced_by": introduced_by,
            "appearances": appearances_list,
        })

    # ------------------------------------------------------------------ #
    # 6. Sort tracks: (first_seen asc, len(appearances) desc, label asc)  #
    # ------------------------------------------------------------------ #
    raw_tracks.sort(
        key=lambda t: (t["first_seen"], -len(t["appearances"]), t["label"])
    )

    # ------------------------------------------------------------------ #
    # 7. Cap tracks                                                        #
    # ------------------------------------------------------------------ #
    truncated_tracks = 0
    if len(raw_tracks) > max_tracks:
        truncated_tracks = len(raw_tracks) - max_tracks
        raw_tracks = raw_tracks[:max_tracks]

    # ------------------------------------------------------------------ #
    # 8. Build years union                                                 #
    # ------------------------------------------------------------------ #
    year_set: set[int] = set(year_counts.keys())
    for track in raw_tracks:
        for app in track["appearances"]:
            year_set.add(app["year"])
    years = sorted(year_set)

    return {
        "years": years,
        "papers_per_year": papers_per_year,
        "tracks": raw_tracks,
        "skipped_papers_without_year": skipped_papers_without_year,
        "truncated_tracks": truncated_tracks,
    }


def _get_node_kind(graph: Any, node_id: str) -> str:
    """Safely retrieve the 'kind' attribute of a graph node."""
    try:
        return graph.nodes[node_id].get("kind", "")
    except (KeyError, Exception):
        return ""
