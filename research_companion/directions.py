"""Research Directions synthesis (Brainstorm slice 2b).

"Given a topic + the papers already in view (library ∪ 2a discovery) + the
concept graph + open gaps, what should this researcher actually work on
next?" — an ideation agent that turns that context into a ranked list of
grounded, citation-backed research directions. Every direction is grounded
ONLY in the supplied papers/concepts/gaps; the LLM groups/suggests, it
never fabricates a reference.

Pipeline (mirrors gaps.py's synthesize_gaps shape):
    1. _collect_grounding (pure)   -- build the citeable index + LLM grounding block
    2. one DIRECTIONS_PROMPT call  -- LLM over-generates candidate directions
    3. _assemble_directions (pure) -- attach citations, drop invented keys
    4. rank_directions (pure)      -- deterministic score, stable sort desc

Deliberately synchronous/ephemeral (like discover.py's search, NOT gaps.py's
disk-cached job): directions are a function of a free-text topic + transient
2a discovery seeds, which change every search, so there is no corpus-SHA
cache to key on. See
docs/superpowers/specs/2026-08-10-brainstorm-directions-design.md.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any

from research_companion.rebuttal.verify import _norm

_DIRECTION_TYPES = {
    "extend_method", "new_application", "underexplored_concept",
    "open_gap", "cross_pollination", "other",
}
_DIRECTION_TYPE_WEIGHT = {
    "open_gap": 2.0,
    "underexplored_concept": 1.5,
    "cross_pollination": 1.0,
}
_DIRECTIONS_RECENCY_BASE_YEAR = 2000


# ---------------------------------------------------------------------------
# _underexplored_concepts
# ---------------------------------------------------------------------------

def _underexplored_concepts(graph: Any, *, cap: int = 15) -> list[dict]:
    """Concept nodes from *graph* with the lowest `paper_count` (low
    frequency ~= underexplored) -- the only existing per-concept frequency
    signal (graph.py's entity-provenance pass); no centrality/sparse-region
    computation exists, so this is the pure derivation for it.

    Only nodes with `kind == "concept"` and `paper_count >= 1` are eligible.
    Of those, the bottom third by paper_count (ties broken by name for a
    stable, deterministic order) is returned, capped at *cap* entries.
    Empty when *graph* is None/empty or has no eligible concept nodes.

    Returns [{"name": str, "paper_count": int}, ...].
    """
    if graph is None:
        return []
    candidates: list[dict] = []
    for nid, data in graph.nodes(data=True):
        if data.get("kind") != "concept":
            continue
        count = data.get("paper_count")
        if not isinstance(count, int) or count < 1:
            continue
        name = data.get("label") or nid
        candidates.append({"name": name, "paper_count": count})
    if not candidates:
        return []
    candidates.sort(key=lambda c: (c["paper_count"], c["name"]))
    n = max(1, len(candidates) // 3)
    threshold = candidates[min(n, len(candidates)) - 1]["paper_count"]
    selected = [c for c in candidates if c["paper_count"] <= threshold]
    return selected[:cap]


# ---------------------------------------------------------------------------
# Identity helpers (mirrors lab_api.py's _dedup_discovered / _library_identity_ids)
# ---------------------------------------------------------------------------

def _paper_identity_rec(item: dict) -> dict:
    """Extract a connectors.identity-style rec {doi, arxiv_id, pmid, pmcid}
    from either a library_papers item (namespaced `paper_id`, e.g.
    "arxiv:2401.00001"/"doi:..."/"pmid:..."/"pmcid:...") or a 2a discovery
    seed dict (raw doi/arxiv_id/pmid/pmcid fields, DiscoveredPaper.to_dict()
    shape). Unrecognized/local/s2-only ids resolve to an empty rec (no
    namespaced id) -- dedup then falls back to a title token.
    """
    if "paper_id" in item:
        pid = str(item.get("paper_id") or "")
        if pid.startswith("doi:"):
            return {"doi": pid.removeprefix("doi:")}
        if pid.startswith("arxiv:"):
            return {"arxiv_id": pid.removeprefix("arxiv:")}
        if pid.startswith("pmid:"):
            return {"pmid": pid.removeprefix("pmid:")}
        if pid.startswith("pmcid:"):
            return {"pmcid": pid.removeprefix("pmcid:")}
        return {}
    return {
        "doi": item.get("doi"),
        "arxiv_id": item.get("arxiv_id"),
        "pmid": item.get("pmid"),
        "pmcid": item.get("pmcid"),
    }


def _dedup_papers(papers: list[dict]) -> list[dict]:
    """Union of library_papers + seeds, deduped by identity
    (connectors.identity.alt_ids, same DOI>PMID>PMCID>arXiv>title precedence
    as 2a's lab_api._dedup_discovered). FIRST occurrence wins -- callers pass
    library_papers before seeds, so a library copy is kept over a duplicate
    2a seed. Order-preserving; skips non-dict items.
    """
    from research_companion.connectors.identity import alt_ids

    id_to_token: dict[str, str] = {}
    chosen: dict[str, dict] = {}
    order: list[str] = []

    for p in papers:
        if not isinstance(p, dict):
            continue
        rec = _paper_identity_rec(p)
        ids = alt_ids(rec)
        token = None
        for i in ids:
            if i in id_to_token:
                token = id_to_token[i]
                break
        if token is None:
            token = next(iter(ids)) if ids else f"title:{str(p.get('title') or '').lower().strip()}"
        for i in ids:
            id_to_token[i] = token

        if token not in chosen:
            chosen[token] = p
            order.append(token)

    return [chosen[t] for t in order]


def _paper_citation_key(item: dict) -> str:
    """Stable `p:<identity>` citation key for a (post-dedup) paper item,
    using connectors.identity.canonical_id (DOI > PMID > PMCID > arXiv >
    title-hash precedence) so the key is deterministic regardless of merge
    order.
    """
    from research_companion.connectors.identity import canonical_id

    rec = _paper_identity_rec(item)
    rec = {**rec, "title": item.get("title", "")}
    return f"p:{canonical_id(rec)}"


# ---------------------------------------------------------------------------
# _collect_grounding
# ---------------------------------------------------------------------------

def _collect_grounding(
    topic: str,
    seeds: list[dict],
    *,
    library_papers: list[dict],
    graph: Any,
    gap_synthesis: dict | None,
) -> tuple[str, dict[str, dict]]:
    """Build the LLM grounding block + index of citeable items with stable
    citation keys. Pure -- no network/LLM. *topic* is accepted for symmetry
    with the orchestrator but is not itself grounding content (it goes into
    the prompt separately via <<TOPIC>>).

    Returns (grounding_block, index) where index maps a stable key
    (`p:<identity>` / `c:<concept-norm>` / `g:<theme_id>`) to a dict
    describing that citeable item:
        paper:   {"kind": "paper", "title", "year", "paper_id" (None for a
                  seed not in the library), "abstract", "concepts"}
        concept: {"kind": "concept", "name", "paper_count"}
        gap:     {"kind": "gap", "theme_id", "title", "bullet"}

    grounding_block is "" when index is empty.
    """
    index: dict[str, dict] = {}
    lines: list[str] = []

    papers = _dedup_papers(list(library_papers) + list(seeds))
    for p in papers:
        key = _paper_citation_key(p)
        if key in index:
            continue
        title = str(p.get("title") or "").strip() or "Untitled"
        year = p.get("year")
        abstract = str(p.get("abstract") or "").strip()
        raw_concepts = p.get("concepts") or []
        concept_names = [
            c if isinstance(c, str) else str((c or {}).get("name", ""))
            for c in raw_concepts
        ]
        concept_names = [c for c in concept_names if c]
        index[key] = {
            "kind": "paper",
            "title": title,
            "year": year,
            "paper_id": p.get("paper_id"),
            "abstract": abstract,
            "concepts": concept_names,
        }
        extra = f" Concepts: {', '.join(concept_names)}." if concept_names else ""
        abstract_bit = f" {abstract[:300]}" if abstract else ""
        lines.append(
            f"- [{key}] {title} ({year if year is not None else 'n.d.'}).{abstract_bit}{extra}"
        )

    for c in _underexplored_concepts(graph):
        key = f"c:{_norm(c['name'])}"
        if key in index:
            continue
        index[key] = {"kind": "concept", "name": c["name"], "paper_count": c["paper_count"]}
        plural = "s" if c["paper_count"] != 1 else ""
        lines.append(
            f"- [{key}] Underexplored concept: {c['name']} "
            f"(appears in only {c['paper_count']} paper{plural} in this library)."
        )

    themes = (gap_synthesis or {}).get("themes", []) if gap_synthesis else []
    for theme in themes:
        if not isinstance(theme, dict) or theme.get("status") not in ("open", "partial"):
            continue
        theme_id = theme.get("theme_id")
        if not theme_id:
            continue
        key = f"g:{theme_id}"
        if key in index:
            continue
        title = str(theme.get("title") or "Untitled theme").strip()
        bullet = str(theme.get("bullet") or title).strip()
        index[key] = {"kind": "gap", "theme_id": theme_id, "title": title, "bullet": bullet}
        lines.append(f"- [{key}] Open gap: {bullet}")

    return "\n".join(lines), index

