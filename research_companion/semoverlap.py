"""Semantic (paraphrase) near-duplicate detection over passage embeddings.

Complements the lexical shingler in ``overlap.py``: passages are compared by
embedding cosine, catching reworded/translated reuse that shingling misses.
Pure math lives here and receives already-computed vectors, so all tests run
offline with fakes. Opt-in end to end: nothing here runs unless the
``semantic_overlap`` setting (or ``check-overlap --semantic``) asks for it.
"""
from __future__ import annotations

import math

DEFAULT_SEMANTIC_THRESHOLD = 0.83  # MiniLM cosine cutoff for "paraphrase-level"
DEFAULT_SEMANTIC_MIN_CHARS = 200   # chunks shorter than this are too weak to judge


def _numpy():
    """Import numpy if available (transitively present with sentence-transformers)."""
    try:
        import numpy
        return numpy
    except ImportError:
        return None


def _l2_normalize(vec: list[float]) -> list[float] | None:
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0.0:
        return None
    return [x / norm for x in vec]


def _best_matches(
    target_vecs: list[list[float]],
    corpus_vecs: list[list[float]],
) -> list[tuple[int, float]]:
    """(corpus index, cosine) of the best corpus match per target vector.

    Inputs must be L2-normalized (cosine == dot product). Uses a numpy matrix
    multiply when numpy is importable, with an identical-result stdlib fallback.
    """
    np = _numpy()
    if np is not None:
        sims = np.asarray(target_vecs) @ np.asarray(corpus_vecs).T
        idx = sims.argmax(axis=1)
        return [(int(i), float(sims[r, i])) for r, i in enumerate(idx)]
    out: list[tuple[int, float]] = []
    for tv in target_vecs:
        best_i, best_s = 0, -1.0
        for i, cv in enumerate(corpus_vecs):
            s = sum(a * b for a, b in zip(tv, cv, strict=False))
            if s > best_s:
                best_s, best_i = s, i
        out.append((best_i, best_s))
    return out


def _usable(unit: dict, vectors: dict, min_chars: int) -> list[float] | None:
    """Normalized vector for a unit, or None when too short / vectorless / zero."""
    from research_companion.store import embedding_key

    if len(unit.get("text", "")) < min_chars:
        return None
    vec = vectors.get(embedding_key(unit["section_id"], unit.get("chunk_index", 0)))
    if vec is None:
        return None
    return _l2_normalize(vec)


def semantic_near_duplicate_passages(
    target_units: list[dict],
    target_vectors: dict[str, list[float]],
    corpus: list[tuple[str, list[dict], dict[str, list[float]]]],
    *,
    threshold: float = DEFAULT_SEMANTIC_THRESHOLD,
    min_chars: int = DEFAULT_SEMANTIC_MIN_CHARS,
) -> dict:
    """Pure: find target chunks whose embedding paraphrases a corpus chunk.

    Same JSON shape as overlap.near_duplicate_passages; findings additionally
    carry ``method: "semantic"`` and ``matched_section_id``.
    """
    t_units: list[dict] = []
    t_vecs: list[list[float]] = []
    for u in target_units:
        nv = _usable(u, target_vectors, min_chars)
        if nv is not None:
            t_units.append(u)
            t_vecs.append(nv)

    c_refs: list[tuple[str, dict]] = []
    c_vecs: list[list[float]] = []
    for pid, units, vectors in corpus:
        for u in units:
            nv = _usable(u, vectors, min_chars)
            if nv is not None:
                c_refs.append((pid, u))
                c_vecs.append(nv)

    findings: list[dict] = []
    if t_vecs and c_vecs:
        for u, (ci, score) in zip(t_units, _best_matches(t_vecs, c_vecs), strict=True):
            if score >= threshold:
                pid, cu = c_refs[ci]
                findings.append({
                    "matched_paper_id": pid,
                    "score": round(score, 4),
                    "char_start": u["char_start"],
                    "char_end": u["char_end"],
                    "snippet": u["text"][:200],
                    "method": "semantic",
                    "matched_section_id": cu["section_id"],
                })

    by_paper: dict[str, float] = {}
    for f in findings:
        pid = f["matched_paper_id"]
        by_paper[pid] = max(by_paper.get(pid, 0.0), f["score"])

    if not c_vecs:
        text = "no embedded library passages to compare against"
    elif not findings:
        text = "no paraphrase-level near-duplicates found"
    else:
        top = max(by_paper, key=lambda p: by_paper[p])
        text = (f"{len(findings)} passage(s) paraphrase library paper {top} "
                f"(max cosine {round(max(by_paper.values()), 2)})")

    return {
        "findings": findings,
        "summary": {
            "n_passages": len(findings),
            "papers": sorted(by_paper),
            "max_score": round(max(by_paper.values()), 4) if by_paper else 0.0,
            "text": text,
        },
    }


def _ranges_overlap(a: dict, b: dict) -> bool:
    return a["char_start"] < b["char_end"] and b["char_start"] < a["char_end"]


def merge_overlap_results(lexical: dict, semantic: dict) -> dict:
    """Merge a semantic pass into the lexical result (same JSON shape).

    Lexical findings are tagged ``method: "lexical"``. A semantic finding whose
    char range overlaps a LEXICAL finding for the same matched paper is dropped
    (that region is already surfaced); semantic-vs-semantic overlaps are kept.
    ``summary`` is recomputed and gains ``n_semantic``.
    """
    lex = [dict(f, method=f.get("method", "lexical"))
           for f in lexical.get("findings", []) or []]
    sem = [f for f in semantic.get("findings", []) or []
           if not any(lf["matched_paper_id"] == f["matched_paper_id"]
                      and _ranges_overlap(lf, f) for lf in lex)]
    findings = lex + sem

    by_paper: dict[str, float] = {}
    for f in findings:
        pid = f["matched_paper_id"]
        by_paper[pid] = max(by_paper.get(pid, 0.0), f["score"])

    if not findings:
        text = lexical.get("summary", {}).get("text",
                                              "no near-duplicate passages found")
    else:
        top = max(by_paper, key=lambda p: by_paper[p])
        text = (f"{len(findings)} passage(s) near-duplicate library paper {top} "
                f"(max {round(max(by_paper.values()) * 100)}% overlap)")
        if sem:
            text += f" ({len(sem)} paraphrased)"

    return {
        "findings": findings,
        "summary": {
            "n_passages": len(findings),
            "papers": sorted(by_paper),
            "max_score": round(max(by_paper.values()), 4) if by_paper else 0.0,
            "text": text,
            "n_semantic": len(sem),
        },
    }
