"""Deterministic grouping of a flat prior-art list into clusters.

Clusters = connected components of a paper-similarity graph (Jaccard over
keyword sets ≥ threshold). networkx is already a dependency. Pure; no network.
Optional LLM labeling lives in build_taxonomy (degrades to a keyword label).
"""
from __future__ import annotations

import re
from collections import Counter

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


_LABEL_PROMPT = """Name this group of related papers in 2-5 words. Return ONLY the name.

Papers:
{titles}
"""


def _shared_terms(papers: list[dict], idxs: list[int]) -> list[str]:
    counter: Counter[str] = Counter()
    for i in idxs:
        counter.update(_keywords(f"{papers[i].get('title', '')} {papers[i].get('abstract', '')}"))
    return [w for w, _ in counter.most_common(5)]


def _keyword_label(terms: list[str]) -> str:
    return terms[0].title() if terms else "Related work"


def build_taxonomy(papers: list[dict], *, llm=None) -> list[dict]:
    if not papers:
        return []
    clusters = cluster_papers(papers)
    # Collapse fallback: a single component or all-singletons is not a useful tree.
    if len(clusters) == 1 or all(len(c) == 1 for c in clusters):
        terms = _shared_terms(papers, list(range(len(papers))))
        label = "Related work"
        if llm is not None:
            titles = "\n".join(f"- {p.get('title', '')}" for p in papers)
            try:
                got = str(llm(_LABEL_PROMPT.format(titles=titles))).strip().splitlines()[0].strip()
                if got:
                    label = got[:80]
            except Exception:
                pass  # keep keyword label on any LLM failure
        return [{"label": label, "shared_terms": terms, "papers": [_paper_ref(p) for p in papers]}]
    out = []
    for idxs in clusters:
        terms = _shared_terms(papers, idxs)
        label = _keyword_label(terms)
        if llm is not None:
            titles = "\n".join(f"- {papers[i].get('title', '')}" for i in idxs)
            try:
                got = str(llm(_LABEL_PROMPT.format(titles=titles))).strip().splitlines()[0].strip()
                if got:
                    label = got[:80]
            except Exception:
                pass  # keep keyword label on any LLM failure
        out.append({"label": label, "shared_terms": terms,
                    "papers": [_paper_ref(papers[i]) for i in idxs]})
    return out


def _paper_ref(p: dict) -> dict:
    return {"title": p.get("title", ""), "year": p.get("year"), "id": p.get("id", "")}
