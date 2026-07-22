"""Uncited-paper opportunities — strictly assembled from stored analysis.

Given the active draft, surface library papers that are NOT cited by it and
whose stored alignment says they strengthen/challenge/offer-alternatives to
specific draft sections. No LLM, no network: every field comes from
store.load_alignment / store.load_strength / citations_coverage.compute_coverage.

VERIFIED (task-1 brief flag): compute_coverage's persisted/returned payload
keys its per-reference records under "references" (NOT "records" as the
brief's draft sketch guessed) — see citations_coverage.compute_coverage's
`payload = {..., "references": refs_out, ...}` and every consumer in
lab_api.py (e.g. unlink_draft_citation) reading `payload.get("references")`.
Each record carries a `matched_paper_id` key (None when unmatched), confirmed
by citations_coverage.match_reference_to_library's assignment of
`rec["matched_paper_id"]` and by TestComputeCoverage in
tests/test_citations_coverage.py.
"""
from __future__ import annotations

from research_companion import store
from research_companion.citations_coverage import compute_coverage


def uncited_paper_ids(draft_id: str) -> set[str]:
    """Library paper ids NOT cited by the draft (per stored coverage), minus
    the draft itself. Offline: reads/recomputes citations_coverage only."""
    all_ids = {p.paper_id for p in store.list_papers()}
    cov = compute_coverage(draft_id)
    cited = {
        rec["matched_paper_id"] for rec in cov.get("references", [])
        if rec.get("matched_paper_id")
    }
    return all_ids - cited - {draft_id}


def build_opportunities(draft_id: str | None) -> dict:
    """Per-section suggestions drawn only from uncited papers' stored alignment.

    Mirrors lab_api.get_draft_alignment's per-section assembly, restricted to
    `uncited_paper_ids(draft_id)`. Suggestions per section are sorted by
    relevance descending; sections with zero suggestions are omitted.
    """
    if draft_id is None:
        return {"draft_id": None, "sections": []}

    uncited = uncited_paper_ids(draft_id)
    sections_map: dict[str, dict] = {}

    for meta in store.list_papers():
        if meta.paper_id not in uncited:
            continue
        alignment = store.load_alignment(meta.paper_id, draft_paper_id=draft_id)
        if alignment is None:
            continue
        strength = store.load_strength(meta.paper_id)
        band = strength.get("band") if isinstance(strength, dict) else None

        for sec in alignment.get("sections", []):
            sid = sec.get("section_id", "")
            entry = sections_map.setdefault(sid, {
                "section_id": sid,
                "section_title": sec.get("section_title", sid),
                "suggestions": [],
            })
            entry["suggestions"].append({
                "paper_id": meta.paper_id,
                "title": meta.title,
                "relation": sec.get("relation", ""),
                "relevance": sec.get("relevance", 0.0),
                "rationale": sec.get("rationale", ""),
                "evidence": sec.get("evidence", []),
                "strength_band": band,
            })

    sections = []
    for entry in sections_map.values():
        if not entry["suggestions"]:
            continue
        entry["suggestions"].sort(key=lambda s: s["relevance"], reverse=True)
        sections.append(entry)

    return {"draft_id": draft_id, "sections": sections}
