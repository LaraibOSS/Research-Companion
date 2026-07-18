"""Deterministic grouping of a flat prior-art list into clusters.

Clusters = connected components of a paper-similarity graph (Jaccard over
keyword sets ≥ threshold). networkx is already a dependency. Pure; no network.
Optional LLM labeling lives in label_clusters (degrades to a keyword label).
"""
from __future__ import annotations

import re

import networkx as nx

_STOP = {
    "the", "a", "an", "of", "for", "and", "or", "to", "in", "on", "with", "via",
    "using", "based", "we", "our", "this", "that", "is", "are", "from", "by",
}
_WORD = re.compile(r"[a-z0-9]+")


def _keywords(text: str) -> set[str]:
    return {w for w in _WORD.findall((text or "").lower()) if len(w) >= 3 and w not in _STOP}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def cluster_papers(papers: list[dict], *, threshold: float = 0.12) -> list[list[int]]:
    """Partition papers into clusters (lists of indices) by keyword-overlap
    connected components. Deterministic: node order and output follow input order."""
    kws = [_keywords(f"{p.get('title', '')} {p.get('abstract', '')}") for p in papers]
    g = nx.Graph()
    g.add_nodes_from(range(len(papers)))
    for i in range(len(papers)):
        for j in range(i + 1, len(papers)):
            if _jaccard(kws[i], kws[j]) >= threshold:
                g.add_edge(i, j)
    # sorted() keeps output deterministic regardless of networkx set ordering.
    return [sorted(comp) for comp in sorted(nx.connected_components(g), key=lambda c: min(c))]
