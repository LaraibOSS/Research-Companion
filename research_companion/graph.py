"""Cross-paper knowledge graph construction.

Reads each paper's cached extraction, normalises entity names, deduplicates
across papers, and emits a NetworkX graph + persists to graph.json.

Schema:
    Node types:
        paper    — one node per paper, attrs: title, authors, year, source_url
        concept  — one node per unique normalised concept name across all papers
        method   — one per unique normalised method
        dataset  — one per unique normalised dataset
        claim    — one per claim text (papers usually don't share claims; rarely merged)
        result   — one per (metric, value, dataset) tuple
    Edge relations:
        contains       paper -> concept/method/dataset/claim/result
        uses           method -> dataset (when a result links them)
        cites          paper -> paper (from related_work, only when title resolves to a known paper)
        evaluates_on   paper -> dataset (via results)
        co_mentioned   concept <-> concept (when both appear in same paper, weight = paper count)
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any

import networkx as nx
from networkx.readwrite import json_graph

from research_companion.prompts import extraction_prompt_sha256
from research_companion.store import (
    PaperMetadata,
    graph_json_path,
    list_papers,
    load_extraction,
    load_sections,
    load_strength,
)

# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

def _norm(name: str) -> str:
    """Normalise an entity name to a comparison key.

    'Graph RAG' / 'graphrag' / 'GraphRAG' -> 'graphrag'
    'BM25' / 'bm25' -> 'bm25'
    """
    s = name.lower().strip()
    s = re.sub(r"[\s\-_]+", "", s)
    s = re.sub(r"[^a-z0-9]", "", s)
    return s


def _node_id(kind: str, norm_key: str) -> str:
    return f"{kind}::{norm_key}"


def _safe_str(v: Any) -> str:
    return str(v) if v is not None else ""


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

def build_graph(papers: list[PaperMetadata] | None = None) -> nx.Graph:
    """Build the cross-paper knowledge graph from cached extractions.

    If `papers` is None, loads all papers from the store.
    Papers without a cached extraction (matching the current prompt SHA) are skipped
    with a printed warning.
    """
    G: nx.Graph = nx.Graph()
    papers = papers if papers is not None else list_papers()
    prompt_sha = extraction_prompt_sha256()

    # Track entity-name aliases: norm_key -> canonical display name.
    # Canonical name = the first non-normalised name we saw.
    canonical: dict[tuple[str, str], str] = {}

    # Track which papers mention which concept (for co_mentioned edges).
    concept_to_papers: dict[str, set[str]] = defaultdict(set)

    skipped: list[str] = []

    for meta in papers:
        ext = load_extraction(meta.paper_id, prompt_sha=prompt_sha)
        if ext is None:
            skipped.append(meta.paper_id)
            continue

        # Paper node.
        paper_attrs: dict[str, Any] = dict(
            kind="paper",
            label=meta.title,
            authors=meta.authors,
            year=meta.year,
            source_url=meta.source_url,
        )
        # Optional: sections enrichment.
        sections_payload = load_sections(meta.paper_id)
        if sections_payload is not None:
            paper_attrs["sections"] = [
                {"id": s["section_id"], "title": s["title"], "level": s["level"]}
                for s in sections_payload.get("sections", [])
            ]
        # Optional: strength enrichment.
        strength_payload = load_strength(meta.paper_id)
        if strength_payload is not None:
            paper_attrs["strength_band"] = strength_payload.get("band", "")
            paper_attrs["strength_color"] = strength_payload.get("color", "")
        G.add_node(meta.paper_id, **paper_attrs)

        # Concepts.
        for c in ext.get("concepts", []):
            name = _safe_str(c.get("name"))
            if not name:
                continue
            key = _norm(name)
            if not key:
                continue
            nid = _node_id("concept", key)
            canonical.setdefault(("concept", key), name)
            G.add_node(
                nid,
                kind="concept",
                label=canonical[("concept", key)],
                definition=_safe_str(c.get("definition")),
            )
            G.add_edge(meta.paper_id, nid, relation="contains",
                       section=c.get("section", None))
            concept_to_papers[nid].add(meta.paper_id)

        # Methods.
        for m in ext.get("methods", []):
            name = _safe_str(m.get("name"))
            if not name:
                continue
            key = _norm(name)
            if not key:
                continue
            nid = _node_id("method", key)
            canonical.setdefault(("method", key), name)
            G.add_node(
                nid,
                kind="method",
                label=canonical[("method", key)],
                description=_safe_str(m.get("description")),
            )
            G.add_edge(meta.paper_id, nid, relation="contains",
                       section=m.get("section", None))

        # Datasets.
        for d in ext.get("datasets", []):
            name = _safe_str(d.get("name"))
            if not name:
                continue
            key = _norm(name)
            if not key:
                continue
            nid = _node_id("dataset", key)
            canonical.setdefault(("dataset", key), name)
            G.add_node(
                nid,
                kind="dataset",
                label=canonical[("dataset", key)],
                description=_safe_str(d.get("description")),
            )
            G.add_edge(meta.paper_id, nid, relation="contains",
                       section=d.get("section", None))

        # Claims (rarely shared across papers; we still merge by exact text).
        for cl in ext.get("claims", []):
            text = _safe_str(cl.get("text")).strip()
            if not text:
                continue
            key = _norm(text)[:64]  # hash-ish key on the text
            if not key:
                continue
            nid = _node_id("claim", key)
            G.add_node(nid, kind="claim", label=text[:120], full_text=text)
            G.add_edge(meta.paper_id, nid, relation="contains",
                       section=cl.get("section", None))

        # Results — link paper to dataset (evaluates_on) and method (uses) when possible.
        for r in ext.get("results", []):
            metric = _safe_str(r.get("metric"))
            value = _safe_str(r.get("value"))
            dataset = _safe_str(r.get("dataset"))
            if not (metric and value):
                continue
            ds_key = _norm(dataset)
            ds_nid = _node_id("dataset", ds_key) if ds_key else None
            if ds_nid and not G.has_node(ds_nid):
                # Result references a dataset not in the datasets list — add as a stub.
                canonical.setdefault(("dataset", ds_key), dataset)
                G.add_node(ds_nid, kind="dataset", label=dataset, description="")
            result_nid = _node_id("result", _norm(f"{metric}-{value}-{dataset}"))
            G.add_node(
                result_nid,
                kind="result",
                label=f"{metric}={value}" + (f" on {dataset}" if dataset else ""),
                metric=metric,
                value=value,
                dataset=dataset,
            )
            G.add_edge(meta.paper_id, result_nid, relation="contains",
                       section=r.get("section", None))
            if ds_nid:
                if not G.has_edge(meta.paper_id, ds_nid):
                    G.add_edge(meta.paper_id, ds_nid, relation="evaluates_on")
                G.add_edge(result_nid, ds_nid, relation="on")

        # related_work -> cites edges (only when the cited title resolves to a known paper title).
        # In v0.1 we use a fuzzy check: lowercased substring match on existing paper titles.
        for ref in ext.get("related_work", []):
            ref_str = _safe_str(ref).strip()
            if not ref_str:
                continue
            target = _resolve_citation(ref_str, papers)
            if target is not None and target != meta.paper_id:
                G.add_edge(meta.paper_id, target, relation="cites")

    # co_mentioned edges: when 2 concepts share >= 2 papers.
    concept_ids = list(concept_to_papers.keys())
    for i, a in enumerate(concept_ids):
        for b in concept_ids[i + 1:]:
            shared = concept_to_papers[a] & concept_to_papers[b]
            if len(shared) >= 2:
                G.add_edge(a, b, relation="co_mentioned", weight=len(shared))

    if skipped:
        print(f"[research-companion] skipped {len(skipped)} papers without cached extraction "
              f"(run `research-companion build` after `research-companion add` to extract first)")

    return G


def _resolve_citation(ref: str, papers: list[PaperMetadata]) -> str | None:
    """Best-effort resolution of a related_work string to a paper_id in our store.

    v0.1 strategy: lowercased substring containment in either direction. Cheap and OK.
    Returns None if no match.
    """
    ref_l = ref.lower()
    for p in papers:
        title_l = (p.title or "").lower()
        if not title_l:
            continue
        if title_l in ref_l or ref_l in title_l:
            return p.paper_id
    return None


# ---------------------------------------------------------------------------
# Section subgraph helper
# ---------------------------------------------------------------------------

def serialize_graph(G: nx.Graph, *, seq: int = 0) -> dict:
    """Serialize a NetworkX graph to the canonical node/edge wire format.

    Returns::

        {
            "seq":   int,
            "nodes": [{"id", "kind", "label", "sections", "strength", "attrs"}, ...],
            "edges": [{"from", "to", "relation", "weight"}, ...],
        }

    This is the shared serializer used by GET /api/graph (lab_api) and
    views.view_graph (views.py).  Moving it to graph.py avoids import cycles
    (graph.py imports neither lab_api nor views; both can import graph freely).
    """
    from research_companion import store as _store

    nodes = []
    for nid, data in G.nodes(data=True):
        kind = data.get("kind", "")
        attrs = {k: v for k, v in data.items()
                 if k not in ("kind", "label", "strength_band", "strength_color")}

        # sections attr: paper nodes use the store; entity nodes derive from
        # contains-edges in G.
        if kind == "paper":
            sections_payload = _store.load_sections(nid)
            if sections_payload is not None:
                sec_ids = [s["section_id"] for s in sections_payload.get("sections", [])]
            else:
                sec_ids = []
        else:
            sec_ids_set: set[str] = set()
            for neighbor in G.neighbors(nid):
                edge_data = G.edges[neighbor, nid]
                if edge_data.get("relation") == "contains":
                    sec_val = edge_data.get("section")
                    if sec_val:
                        sec_ids_set.add(sec_val)
            sec_ids = sorted(sec_ids_set)

        # strength attr for paper nodes
        strength = None
        if kind == "paper":
            band = data.get("strength_band")
            color = data.get("strength_color")
            if band or color:
                strength = {"band": band or "", "color": color or ""}
            else:
                sp = _store.load_strength(nid)
                if sp is not None:
                    strength = {
                        "band": sp.get("band", ""),
                        "color": sp.get("color", ""),
                    }

        nodes.append({
            "id": nid,
            "kind": kind,
            "label": data.get("label", nid),
            "sections": sec_ids,
            "strength": strength,
            "attrs": attrs,
        })

    edges = []
    for u, v, edata in G.edges(data=True):
        edges.append({
            "from": u,
            "to": v,
            "relation": edata.get("relation", ""),
            "weight": edata.get("weight", 1),
        })

    return {"seq": seq, "nodes": nodes, "edges": edges}


def section_subgraph(G: nx.Graph, paper_id: str, section_id: str) -> nx.Graph:
    """Return a subgraph copy with the paper node + neighbours whose contains-edge
    from this paper carries section == section_id, plus all edges among included nodes.

    - Unknown paper_id -> empty graph.
    - Unknown / no-match section_id -> graph with just the paper node (if present).
    """
    if paper_id not in G.nodes:
        return nx.Graph()

    included = {paper_id}
    for nbr in G.neighbors(paper_id):
        edge_data = G.edges[paper_id, nbr]
        if edge_data.get("relation") == "contains" and edge_data.get("section") == section_id:
            included.add(nbr)

    return G.subgraph(included).copy()


# ---------------------------------------------------------------------------
# Graph delta helper
# ---------------------------------------------------------------------------

def graph_delta(old: nx.Graph, new: nx.Graph) -> dict:
    """Return nodes and edges present in *new* but not in *old*.

    Returns:
        {
            "nodes_added": [{"id", "kind", "label"}, ...],  # sorted by id
            "edges_added": [{"source", "target", "relation"}, ...],  # sorted by (source, target, relation)
        }

    Node identity: node id string.
    Edge identity: frozenset({u, v}) + relation attribute value.
    """
    old_node_ids: set[str] = set(old.nodes())
    new_node_ids: set[str] = set(new.nodes())

    added_node_ids = sorted(new_node_ids - old_node_ids)
    nodes_added = [
        {
            "id": nid,
            "kind": new.nodes[nid].get("kind", ""),
            "label": new.nodes[nid].get("label", ""),
        }
        for nid in added_node_ids
    ]

    # Build set of (frozenset, relation) for old edges.
    old_edge_keys: set[tuple[frozenset, str]] = {
        (frozenset((u, v)), d.get("relation", ""))
        for u, v, d in old.edges(data=True)
    }

    edges_added_raw = []
    for u, v, d in new.edges(data=True):
        relation = d.get("relation", "")
        key = (frozenset((u, v)), relation)
        if key not in old_edge_keys:
            edges_added_raw.append((u, v, relation))

    # Deterministic sort: by (source, target, relation).
    edges_added_raw.sort(key=lambda t: (t[0], t[1], t[2]))
    edges_added = [
        {"source": u, "target": v, "relation": rel}
        for u, v, rel in edges_added_raw
    ]

    return {"nodes_added": nodes_added, "edges_added": edges_added}


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def save_graph(G: nx.Graph, path=None) -> None:
    p = path or graph_json_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json_graph.node_link_data(G, edges="links")
    except TypeError:
        # Older networkx (<3.4) doesn't support the `edges` kwarg.
        data = json_graph.node_link_data(G)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def load_graph(path=None) -> nx.Graph:
    p = path or graph_json_path()
    if not p.exists():
        return nx.Graph()
    data = json.loads(p.read_text(encoding="utf-8"))
    # networkx >= 3.6 writes an "edges" key by default; our writer pins "links",
    # but tolerate either so stores written by other tool versions still load.
    edges_key = "links" if "links" in data else "edges"
    try:
        return json_graph.node_link_graph(data, edges=edges_key)
    except TypeError:
        return json_graph.node_link_graph(data)


def graph_stats(G: nx.Graph) -> dict[str, int]:
    by_kind: dict[str, int] = defaultdict(int)
    for _, data in G.nodes(data=True):
        by_kind[data.get("kind", "unknown")] += 1
    by_relation: dict[str, int] = defaultdict(int)
    for _, _, d in G.edges(data=True):
        by_relation[d.get("relation", "unknown")] += 1
    return {
        "nodes_total": G.number_of_nodes(),
        "edges_total": G.number_of_edges(),
        **{f"node_{k}": v for k, v in by_kind.items()},
        **{f"edge_{k}": v for k, v in by_relation.items()},
    }
