"""Deterministic paper strength scoring.

Each paper gets an explainable strength score for color coding in the UI.
Purely deterministic — no LLM. Weighted mean over AVAILABLE signals only,
weights renormalized; every signal reported so the UI can show WHY.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from research_companion import store
from research_companion.store import PaperMetadata


# Canonical constants (exact values — UI depends on them)
SIGNAL_WEIGHTS = {
    "extraction_completeness": 0.30,
    "citation_health": 0.25,
    "alignment": 0.25,
    "recency": 0.20,
}

BANDS = [
    (0.65, "strong", "#3fb950"),
    (0.40, "moderate", "#d29922"),
    (0.0, "weak", "#f0883e"),
]

UNSCORED = ("unscored", "#8b949e")


def _extract_signal_value(
    extraction: dict[str, Any] | None,
) -> tuple[bool, float | None]:
    """Compute extraction_completeness signal.

    Available iff extraction is not None and has the required keys.
    Value = (number of the six keys concepts/methods/datasets/claims/results/related_work
    that are non-empty lists) / 6.

    Returns (available, value).
    """
    if extraction is None:
        return False, None

    # Available iff extraction is not None; value = count of the six keys that
    # are present as non-empty lists, divided by 6.
    required_keys = ["concepts", "methods", "datasets", "claims", "results", "related_work"]

    non_empty_count = 0

    for key in required_keys:
        val = extraction.get(key)
        if isinstance(val, list) and len(val) > 0:
            non_empty_count += 1

    value = non_empty_count / len(required_keys)
    return True, value


def _citation_health_signal(
    refcheck: dict[str, Any] | None,
) -> tuple[bool, float | None]:
    """Compute citation_health signal.

    Available iff refcheck is not None and refcheck.get("total", 0) > 0.
    Value = refcheck["verified"] / refcheck["total"].

    Returns (available, value).
    """
    if refcheck is None:
        return False, None

    total = refcheck.get("total", 0)
    if total == 0:
        return False, None

    verified = refcheck.get("verified", 0)
    value = verified / total
    return True, value


def _alignment_signal(
    alignment: dict[str, Any] | None,
) -> tuple[bool, float | None]:
    """Compute alignment signal.

    Available iff alignment is not None and "score" in alignment.
    Value = alignment["score"].

    Returns (available, value).
    """
    if alignment is None:
        return False, None

    if "score" not in alignment:
        return False, None

    value = alignment["score"]
    return True, value


def _recency_signal(
    year: int | None, now_year: int
) -> tuple[bool, float | None]:
    """Compute recency signal.

    Available iff year is not None.
    Value = 1.0 if year >= now_year - 2; linear from 1.0 at (now_year-2) down to 0.2
    at (now_year-10); clamp to 0.2 below that.

    Formula: value = max(0.2, min(1.0, 1.0 - 0.8 * ((now_year - 2 - year) / 8)))
    for year < now_year - 2.

    Returns (available, value).
    """
    if year is None:
        return False, None

    if year >= now_year - 2:
        return True, 1.0

    diff = now_year - 2 - year
    value = max(0.2, min(1.0, 1.0 - 0.8 * (diff / 8)))
    return True, value


def compute_strength(
    *,
    extraction: dict[str, Any] | None,
    refcheck: dict[str, Any] | None,
    alignment: dict[str, Any] | None,
    year: int | None,
    now_year: int,
) -> dict[str, Any]:
    """Compute paper strength score.

    Args:
        extraction: Extraction dict or None.
        refcheck: Refcheck dict with {verified, total} or None.
        alignment: Alignment dict with {score, ...} or None.
        year: Paper publication year or None.
        now_year: Current year for recency calculation.

    Returns:
        {
            "version": 1,
            "score": <float|None rounded 4dp>,
            "band": str,
            "color": str,
            "signals": {
                name: {"value": <float|None>, "weight": w, "available": bool}
                for all four
            },
            "computed_at": "<UTC ISO>",
        }
    """
    # Compute all four signals
    extract_avail, extract_val = _extract_signal_value(extraction)
    citation_avail, citation_val = _citation_health_signal(refcheck)
    align_avail, align_val = _alignment_signal(alignment)
    recency_avail, recency_val = _recency_signal(year, now_year)

    # Build signals dict with weights
    signals = {
        "extraction_completeness": {
            "value": extract_val,
            "weight": SIGNAL_WEIGHTS["extraction_completeness"],
            "available": extract_avail,
        },
        "citation_health": {
            "value": citation_val,
            "weight": SIGNAL_WEIGHTS["citation_health"],
            "available": citation_avail,
        },
        "alignment": {
            "value": align_val,
            "weight": SIGNAL_WEIGHTS["alignment"],
            "available": align_avail,
        },
        "recency": {
            "value": recency_val,
            "weight": SIGNAL_WEIGHTS["recency"],
            "available": recency_avail,
        },
    }

    # Count available signals
    available_count = sum(1 for sig in signals.values() if sig["available"])

    # Fewer than 2 available signals -> unscored
    if available_count < 2:
        return {
            "version": 1,
            "score": None,
            "band": UNSCORED[0],
            "color": UNSCORED[1],
            "signals": signals,
            "computed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }

    # Compute weighted score with renormalization
    numerator = 0.0
    denominator = 0.0

    for sig_name, sig_data in signals.items():
        if sig_data["available"]:
            numerator += sig_data["weight"] * sig_data["value"]
            denominator += sig_data["weight"]

    score = numerator / denominator if denominator > 0 else None

    # Round to 4 decimal places
    if score is not None:
        score = round(score, 4)

    # Determine band and color
    band = UNSCORED[0]
    color = UNSCORED[1]

    if score is not None:
        for threshold, band_name, band_color in BANDS:
            if score >= threshold:
                band = band_name
                color = band_color
                break

    return {
        "version": 1,
        "score": score,
        "band": band,
        "color": color,
        "signals": signals,
        "computed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def load_extraction_for_paper(paper_id: str) -> dict[str, Any] | None:
    """Load extraction for a paper.

    Uses the same pattern as graph.py: loads cached extraction matching
    the current prompt SHA.
    """
    from research_companion.prompts import extraction_prompt_sha256

    prompt_sha = extraction_prompt_sha256()
    return store.load_extraction(paper_id, prompt_sha=prompt_sha)


def strength_for_paper(
    paper_id: str, *, refcheck: dict[str, Any] | None = None, now_year: int | None = None
) -> dict[str, Any]:
    """Compute and persist strength for a paper.

    Loads meta (ValueError if unknown), extraction (via load_extraction_for_paper),
    alignment via store.load_alignment (only when a draft is set AND paper is not
    itself the draft); computes now_year from datetime.now(timezone.utc).year when None;
    calls compute_strength; persists via store.save_strength; returns the payload.

    Args:
        paper_id: Paper ID string.
        refcheck: Optional refcheck dict with {verified, total}.
        now_year: Current year for recency. Defaults to datetime.now(timezone.utc).year.

    Returns:
        Strength result dict (same as compute_strength return value).

    Raises:
        ValueError: If paper_id is unknown (no metadata).
    """
    # Load metadata (raises ValueError if unknown)
    meta = PaperMetadata.load(paper_id)
    if meta is None:
        raise ValueError(f"Unknown paper_id: {paper_id!r}")

    # Load extraction
    extraction = load_extraction_for_paper(paper_id)

    # Load alignment only if draft is set AND paper is not itself the draft
    alignment = None
    draft_paper_id = store.get_draft_paper_id()
    if draft_paper_id is not None and draft_paper_id != paper_id:
        alignment = store.load_alignment(paper_id, draft_paper_id=draft_paper_id)

    # Compute now_year if not provided
    if now_year is None:
        now_year = datetime.now(timezone.utc).year

    # Compute strength
    result = compute_strength(
        extraction=extraction,
        refcheck=refcheck,
        alignment=alignment,
        year=meta.year,
        now_year=now_year,
    )

    # Persist
    store.save_strength(paper_id, result)

    return result
