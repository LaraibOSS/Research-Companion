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
