"""Hybrid BM25 + embedding retrieval with exact BM25 degradation.

Fusion = weighted min-max normalization (0.5 BM25 + 0.5 cosine) over a candidate
pool of {units with bm25 > 0} UNION {top-20 by cosine}, so purely semantic matches
(zero keyword overlap) can surface. With no embed_query resolvable — no HF token,
no cached vectors, or an embedding error — ranking degrades to raw BM25 order,
bit-for-bit identical to the pre-hybrid behavior. rank_units never raises for
embedding-related reasons.
"""
from __future__ import annotations

import math
import os
from collections.abc import Callable, Sequence

from research_companion.embed import DEFAULT_EMBED_MODEL
from research_companion.rank import BM25

_COSINE_POOL_TOP_N = 20


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity; 0.0 on zero-norm or length mismatch (never raises)."""
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _auto_embed_query() -> Callable[[str], list[float]] | None:
    """Real single-text query embedder when HF_TOKEN is configured, else None."""
    if not os.environ.get("HF_TOKEN"):
        return None

    def _embed(q: str) -> list[float]:
        from research_companion.embed import hf_embed

        return hf_embed([q])[0]

    return _embed


def _load_unit_vectors(units: list[dict], embed_model: str) -> dict[int, list[float]]:
    """Map unit index -> cached vector, reading each paper's embeddings once."""
    from research_companion.store import load_embeddings

    by_paper: dict[str, dict | None] = {}
    vectors: dict[int, list[float]] = {}
    for i, unit in enumerate(units):
        pid = unit.get("paper_id", "")
        if pid not in by_paper:
            try:
                by_paper[pid] = load_embeddings(pid, embed_model=embed_model)
            except Exception:
                by_paper[pid] = None
        payload = by_paper[pid]
        if not payload:
            continue
        entry = (payload.get("vectors") or {}).get(unit.get("section_id", ""))
        if entry and isinstance(entry.get("vector"), list):
            vectors[i] = entry["vector"]
    return vectors


def _minmax(values: dict[int, float]) -> dict[int, float]:
    """Min-max normalize over the given index->value map; max==min -> all 0.5."""
    if not values:
        return {}
    lo, hi = min(values.values()), max(values.values())
    if hi == lo:
        return {i: 0.5 for i in values}
    span = hi - lo
    return {i: (v - lo) / span for i, v in values.items()}


def rank_units(
    question: str,
    q_tokens: list[str],
    units: list[dict],
    *,
    k: int = 6,
    embed_query: Callable[[str], list[float]] | None = None,
    embed_model: str = DEFAULT_EMBED_MODEL,
    w_bm25: float = 0.5,
    w_cos: float = 0.5,
) -> list[dict]:
    """Rank section units for a question. Returns at most *k* dicts of shape
    {"unit", "score", "bm25", "cosine", "mode"} where mode is "hybrid" or "bm25".
    """
    if not units:
        return []

    bm25_raw = BM25([u.get("tokens", []) for u in units]).score(q_tokens)

    resolved_embed = embed_query if embed_query is not None else _auto_embed_query()

    unit_vectors: dict[int, list[float]] = {}
    q_vector: list[float] | None = None
    if resolved_embed is not None:
        unit_vectors = _load_unit_vectors(units, embed_model)
        if unit_vectors:
            try:
                q_vector = resolved_embed(question)
            except Exception:
                q_vector = None

    hybrid = q_vector is not None and bool(unit_vectors)

    if not hybrid:
        pool = [i for i, s in enumerate(bm25_raw) if s > 0.0]
        pool.sort(key=lambda i: (-bm25_raw[i], i))
        return [
            {"unit": units[i], "score": float(bm25_raw[i]),
             "bm25": float(bm25_raw[i]), "cosine": 0.0, "mode": "bm25"}
            for i in pool[:k]
        ]

    cos_raw = {i: cosine(q_vector, v) for i, v in unit_vectors.items()}
    top_cos = sorted(cos_raw, key=lambda i: (-cos_raw[i], i))[:_COSINE_POOL_TOP_N]
    pool = sorted({i for i, s in enumerate(bm25_raw) if s > 0.0} | set(top_cos))
    if not pool:
        return []

    bm25_n = _minmax({i: bm25_raw[i] for i in pool})
    cos_n = _minmax({i: cos_raw.get(i, 0.0) for i in pool})
    fused = {i: w_bm25 * bm25_n[i] + w_cos * cos_n[i] for i in pool}

    ordered = sorted(pool, key=lambda i: (-fused[i], i))
    return [
        {"unit": units[i], "score": float(fused[i]),
         "bm25": float(bm25_raw[i]), "cosine": float(cos_raw.get(i, 0.0)),
         "mode": "hybrid"}
        for i in ordered[:k]
    ]
