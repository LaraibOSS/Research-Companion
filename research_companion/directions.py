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


# ---------------------------------------------------------------------------
# _assemble_directions
# ---------------------------------------------------------------------------

def _assemble_directions(llm_result: dict, index: dict[str, dict]) -> list[dict]:
    """Turn raw LLM direction candidates into citation-backed direction
    records (no `score` yet -- that is rank_directions's job; `recency` IS
    computed here since it depends only on the surviving citations).

    *llm_result* is the parsed DIRECTIONS_PROMPT JSON:
        {"directions": [{"title","rationale","direction_type","grounded_in":[...]}]}
    *index* is `_collect_grounding`'s index.

    Any `grounded_in` key not a key of *index* is DROPPED (honesty guard,
    exactly like gaps._assemble_themes drops invented gap_ids -- the LLM
    cites, it never invents a reference). A direction whose citations all
    drop is KEPT (not discarded) with `grounding_count: 0` so ranking sends
    it to the bottom, never silently hidden. A direction with no `title` is
    dropped (nothing to show). `direction_id` = "dir_" +
    sha256(_norm(title))[:12] (same _norm as gaps._gap_id).

    Returns [{"direction_id", "title", "rationale", "direction_type",
    "citations", "grounding_count", "recency"}, ...].
    """
    out: list[dict] = []
    for raw in (llm_result or {}).get("directions", []) or []:
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title", "")).strip()
        if not title:
            continue
        rationale = str(raw.get("rationale", "")).strip()
        raw_type = str(raw.get("direction_type", "other")).strip().lower()
        direction_type = raw_type if raw_type in _DIRECTION_TYPES else "other"

        keys = [k for k in (raw.get("grounded_in") or []) if isinstance(k, str) and k in index]

        citations: list[dict] = []
        grounding_papers: set[str] = set()
        for k in keys:
            item = index[k]
            if item["kind"] == "paper":
                dedup_key = item.get("paper_id") or k
                citations.append({
                    "kind": "paper",
                    "paper_id": item.get("paper_id"),
                    "title": item["title"],
                    "year": item.get("year"),
                })
                grounding_papers.add(dedup_key)
            elif item["kind"] == "concept":
                citations.append({"kind": "concept", "name": item["name"]})
            elif item["kind"] == "gap":
                citations.append({
                    "kind": "gap", "theme_id": item["theme_id"], "title": item["title"],
                })

        years = [c["year"] for c in citations if c.get("kind") == "paper" and c.get("year") is not None]
        recency = max(years) if years else 0

        out.append({
            "direction_id": "dir_" + hashlib.sha256(_norm(title).encode("utf-8")).hexdigest()[:12],
            "title": title,
            "rationale": rationale,
            "direction_type": direction_type,
            "citations": citations,
            "grounding_count": len(grounding_papers),
            "recency": recency,
        })
    return out


# ---------------------------------------------------------------------------
# rank_directions
# ---------------------------------------------------------------------------

def rank_directions(directions: list[dict]) -> list[dict]:
    """Attach a deterministic `score` to each direction and sort descending,
    stable.

    score = 3.0*grounding_count + 0.1*(recency - 2000) + type_weight
    where type_weight is 2.0 for open_gap, 1.5 for underexplored_concept,
    1.0 for cross_pollination, 0.0 otherwise. Does not mutate the input
    dicts (returns new dicts with `score` added). Python's sort is stable,
    so directions with an identical score keep their original (LLM) order.
    """
    scored: list[dict] = []
    for d in directions:
        recency = d.get("recency") or 0
        type_weight = _DIRECTION_TYPE_WEIGHT.get(d.get("direction_type"), 0.0)
        score = round(
            3.0 * (d.get("grounding_count") or 0)
            + 0.1 * (recency - _DIRECTIONS_RECENCY_BASE_YEAR)
            + type_weight,
            4,
        )
        scored.append({**d, "score": score})
    return sorted(scored, key=lambda d: -d["score"])


# ---------------------------------------------------------------------------
# synthesize_directions
# ---------------------------------------------------------------------------

def synthesize_directions(
    topic: str,
    seeds: list[dict],
    *,
    library_papers: list[dict] = (),
    graph: Any = None,
    gap_synthesis: dict | None = None,
    llm: Callable[[str], str] | None = None,
) -> dict:
    """Turn a topic + the papers in view (library ∪ 2a discovery seeds) + the
    concept graph + open gaps into a ranked list of grounded, citation-backed
    research directions.

    Pipeline: pure collect -> one LLM call -> pure assemble -> pure rank.
    Never raises: when there is truly nothing to ground on (no topic text
    AND an empty grounding index), the LLM call is skipped entirely -- a
    topic alone (even with an empty index) still triggers one LLM call,
    since the researcher gave *something* to work from. Any LLM/parse
    failure (including `llm=None`) degrades to an empty directions list
    rather than propagating.

    Returns {"directions": [...], "generated_from_sha":
    directions_prompt_sha256(), "topic": <stripped topic>, "llm_error":
    <str|None>}. `llm_error` is a short message when the LLM call or its JSON
    parse failed (a retryable failure the caller can surface); it stays None
    for a successful call, including one that legitimately yields zero
    directions -- so the caller can tell "the model failed" from "nothing to
    suggest".
    """
    from research_companion.extract import _strip_code_fences
    from research_companion.prompts import (
        directions_prompt_sha256,
        format_directions_prompt,
    )

    sha = directions_prompt_sha256()
    topic_str = str(topic or "").strip()
    grounding_block, index = _collect_grounding(
        topic_str, list(seeds or []),
        library_papers=list(library_papers or []), graph=graph, gap_synthesis=gap_synthesis,
    )

    if not topic_str and not index:
        return {"directions": [], "generated_from_sha": sha, "topic": topic_str, "llm_error": None}

    prompt = format_directions_prompt(topic=topic_str, grounding_block=grounding_block)

    raw_directions: list = []
    llm_error: str | None = None
    try:
        raw = llm(prompt)
        data = json.loads(_strip_code_fences(raw)) if isinstance(raw, str) else raw
        candidate = data.get("directions") if isinstance(data, dict) else None
        if isinstance(candidate, list):
            raw_directions = candidate
    except Exception as exc:
        # Never raise: a valid JSON response with zero directions is a
        # genuine empty result (llm_error stays None); a call/parse failure
        # is a retryable error the caller surfaces to the user. Both keep
        # directions == [].
        raw_directions = []
        llm_error = str(exc) or exc.__class__.__name__

    assembled = _assemble_directions({"directions": raw_directions}, index)
    ranked = rank_directions(assembled)
    return {
        "directions": ranked,
        "generated_from_sha": sha,
        "topic": topic_str,
        "llm_error": llm_error,
    }
