"""VenueFitAgent: judge whether a paper matches a target venue's scope.

Scope/venue mismatch is a leading desk-rejection cause. The agent runs a
two-stage check: a deterministic topic-overlap prefilter (venues.topic_overlap)
grounds an LLM verdict comparing the paper's abstract + contributions against the
venue scope. normalize_verdict() is the pure coercion of the LLM output into a
stable result shape and is unit-tested without any LLM.
"""
from __future__ import annotations

import math

VALID_FITS = ("strong", "moderate", "weak", "out_of_scope")
# Fits that should warn the author of desk-rejection risk.
_RISKY_FITS = {"weak", "out_of_scope"}


def _clamp01(raw: object) -> float:
    try:
        v = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(v):
        return 0.0
    return max(0.0, min(1.0, v))


def _str_list(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(x).strip() for x in raw if str(x).strip()]


def normalize_verdict(
    raw: dict, *, venue_slug: str, venue_name: str, overlap: float,
) -> dict:
    """Coerce a raw LLM venue-fit response into a stable, JSON-safe verdict.

    Unknown/missing ``fit`` values fall back to "out_of_scope". ``overlap`` is
    the deterministic topic_overlap prefilter carried through for transparency.
    """
    fit = raw.get("fit", "")
    if fit not in VALID_FITS:
        fit = "out_of_scope"
    return {
        "venue": venue_slug,
        "venue_name": venue_name,
        "fit": fit,
        "confidence": round(_clamp01(raw.get("confidence", 0.0)), 3),
        "topic_overlap": round(float(overlap), 3),
        "rationale": str(raw.get("rationale", "")),
        "reasons": _str_list(raw.get("reasons")),
        "suggested_alternatives": _str_list(raw.get("suggested_alternatives")),
        "desk_reject_risk": fit in _RISKY_FITS,
    }
