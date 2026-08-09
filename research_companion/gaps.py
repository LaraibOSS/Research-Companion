"""Gap extraction and resolution mapping for Research Companion v0.3.

"Which gaps did earlier papers leave open, and does MY draft address them?"

Pipeline:
1. extract_gaps(paper_id) — find limitation/future-work sections, call LLM once,
   verify quotes, cache per-paper in papers/<dir>/gaps.json.
2. resolve_gaps() — for each verified gap from paper P (year y), find candidate
   papers with year > y (or same year, different id) plus the draft.
   Deterministic prefilter via rank_units; below sim_threshold -> open (no LLM).
   Above threshold -> one LLM call; sanitize + honesty-downgrade unverified evidence.
   Cache at store level in gap_resolution.json.
3. gaps_overview() — assemble the GET /api/gaps shape.
4. gaps_for_suggestions() — compute relevance flags for suggestions engine.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from research_companion.rebuttal.verify import _norm, verify_quote

# ---------------------------------------------------------------------------
# Section filter regex
# ---------------------------------------------------------------------------

_GAP_SECTION_RE = re.compile(r"(limitation|future work|discussion|conclusion)", re.I)


# ---------------------------------------------------------------------------
# GapError
# ---------------------------------------------------------------------------

class GapError(Exception):
    """Raised by extract_gaps on unrecoverable parse failures."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _relevance_score(top: dict | None) -> float:
    """Map a rank_units top result to a mode-independent relevance in [0, 1].

    ``rank_units`` scores are scaled differently per mode: hybrid scores are
    min-max fused into [0, 1], while degraded (bm25-only, no HF token) scores
    are raw, unbounded BM25. Comparing a single ``sim_threshold`` against both
    meant toggling the HF token silently changed the gap->suggestion gating
    scale, not just recall. We saturate the raw bm25 score via ``s / (s + 1)``
    so the threshold has consistent meaning in either mode; hybrid scores pass
    through unchanged.
    """
    if not top:
        return 0.0
    if top.get("mode") == "hybrid":
        return float(top.get("score", 0.0))
    raw = float(top.get("score", 0.0))
    return raw / (raw + 1.0) if raw > 0.0 else 0.0


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _gap_id(paper_id: str, statement: str) -> str:
    """Stable gap ID: gap_<sha256(paper_id + '|' + _norm(statement))[:12]>."""
    raw = paper_id + "|" + _norm(statement)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    return f"gap_{digest}"


def _papers_sha(paper_ids: list[str]) -> str:
    """SHA256 of sorted paper IDs joined by comma."""
    joined = ",".join(sorted(paper_ids))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _build_units_for_papers(paper_ids: list[str]) -> list[dict]:
    """Build section units for a specific set of paper IDs (for prefilter)."""
    from research_companion.qa import build_section_index
    all_units = build_section_index()
    return [u for u in all_units if u.get("paper_id") in set(paper_ids)]


# ---------------------------------------------------------------------------
# extract_gaps
# ---------------------------------------------------------------------------

def extract_gaps(
    paper_id: str,
    *,
    llm: Callable[[str], str],
    force: bool = False,
) -> dict:
    """Extract gaps from a single paper. Caches result in papers/<id>/gaps.json.

    Returns dict with keys:
        prompt_sha256, computed_at, no_gap_sections (bool), gaps (list)

    Each gap has:
        gap_id, statement, kind, evidence (dict with quote/verified/match)

    Raises GapError on malformed LLM JSON (so extract_all can catch + skip).
    """
    from research_companion import store
    from research_companion.prompts import format_gap_prompt, gap_prompt_sha256
    from research_companion.store import load_gaps, save_gaps

    sha = gap_prompt_sha256()

    # Cache hit
    if not force:
        cached = load_gaps(paper_id, prompt_sha=sha)
        if cached is not None:
            return cached

    # Load metadata + sections
    meta = store.PaperMetadata.load(paper_id)
    if meta is None:
        raise GapError(f"Unknown paper_id: {paper_id!r}")

    sections_payload = store.load_sections(paper_id)
    if sections_payload is None:
        # No sections available — treat as no_gap_sections
        payload: dict[str, Any] = {
            "prompt_sha256": sha,
            "computed_at": _now_utc(),
            "no_gap_sections": True,
            "gaps": [],
        }
        save_gaps(paper_id, payload)
        return payload

    sections = sections_payload.get("sections", [])

    # Filter sections matching the gap regex
    gap_sections = [s for s in sections if _GAP_SECTION_RE.search(s.get("title", ""))]
    if not gap_sections:
        payload = {
            "prompt_sha256": sha,
            "computed_at": _now_utc(),
            "no_gap_sections": True,
            "gaps": [],
        }
        save_gaps(paper_id, payload)
        return payload

    # Load paper text to slice sections
    text = store.load_text(paper_id)
    if text is None:
        payload = {
            "prompt_sha256": sha,
            "computed_at": _now_utc(),
            "no_gap_sections": True,
            "gaps": [],
        }
        save_gaps(paper_id, payload)
        return payload

    # Build gap sections text (cap at 6000 chars)
    gap_text_parts = []
    for s in gap_sections:
        start = s.get("char_start", 0)
        end = s.get("char_end", len(text))
        gap_text_parts.append(text[start:end])
    gap_text = "\n\n".join(gap_text_parts)[:6000]

    # One LLM call
    prompt = format_gap_prompt(title=meta.title, gap_sections_text=gap_text)
    try:
        raw = llm(prompt)
    except Exception as exc:
        raise GapError(f"LLM call failed for {paper_id}: {exc}") from exc

    # Parse defensively
    brace_idx = raw.find("{")
    if brace_idx == -1:
        raise GapError(f"No JSON object found in LLM response for {paper_id}")
    try:
        data = json.loads(raw[brace_idx:])
    except (json.JSONDecodeError, ValueError) as exc:
        raise GapError(f"Invalid JSON from LLM for {paper_id}: {exc}") from exc

    raw_gaps = data.get("gaps")
    if not isinstance(raw_gaps, list):
        raise GapError(f"LLM response missing 'gaps' list for {paper_id}")

    # Process gaps: verify quotes, assign IDs
    processed_gaps = []
    for item in raw_gaps[:5]:  # max 5
        if not isinstance(item, dict):
            continue
        statement = str(item.get("statement", "")).strip()
        kind = str(item.get("kind", "limitation")).strip()
        if kind not in ("limitation", "future_work"):
            kind = "limitation"
        evidence_quote = str(item.get("evidence_quote", "")).strip()

        if not statement:
            continue

        verified, match = verify_quote(evidence_quote, gap_text) if evidence_quote else (False, "")

        gid = _gap_id(paper_id, statement)
        processed_gaps.append({
            "gap_id": gid,
            "statement": statement,
            "kind": kind,
            "evidence": {
                "quote": evidence_quote,
                "verified": verified,
                "match": match,
            },
        })

    payload = {
        "prompt_sha256": sha,
        "computed_at": _now_utc(),
        "no_gap_sections": False,
        "gaps": processed_gaps,
    }
    save_gaps(paper_id, payload)
    return payload


# ---------------------------------------------------------------------------
# extract_all_gaps
# ---------------------------------------------------------------------------

def extract_all_gaps(
    *,
    llm: Callable[[str], str],
    force: bool = False,
    papers: list | None = None,
) -> dict[str, dict]:
    """Run extract_gaps for all (or specified) papers. Skip failures.

    Returns dict mapping paper_id -> gaps payload (only successful ones).
    """
    from research_companion import store

    if papers is None:
        papers = store.list_papers()

    results: dict[str, dict] = {}
    for meta in papers:
        pid = meta.paper_id
        try:
            results[pid] = extract_gaps(pid, llm=llm, force=force)
        except (GapError, Exception):  # noqa: BLE001
            # Skip failures silently; caller can check which IDs are missing
            continue
    return results


# ---------------------------------------------------------------------------
# resolve_gaps
# ---------------------------------------------------------------------------

def resolve_gaps(
    *,
    llm: Callable[[str], str],
    embed_query: Callable[[str], list[float]] | None = None,
    force: bool = False,
    sim_threshold: float = 0.35,
) -> dict:
    """Resolve all verified gaps against candidate papers.

    Reads gaps from per-paper cache. Writes store-level gap_resolution.json.
    Returns the full resolution dict.
    """
    from research_companion import store
    from research_companion.prompts import gap_prompt_sha256, gap_resolution_prompt_sha256
    from research_companion.qa import build_section_index
    from research_companion.rank import tokenize
    from research_companion.retrieve import rank_units
    from research_companion.store import load_gap_resolution, save_gap_resolution

    gap_sha = gap_prompt_sha256()
    res_sha = gap_resolution_prompt_sha256()

    all_papers = store.list_papers()
    paper_ids = [m.paper_id for m in all_papers]
    p_sha = _papers_sha(paper_ids)

    # Check staleness
    if not force:
        cached = load_gap_resolution()
        if cached is not None and (
            cached.get("gap_prompt_sha256") == gap_sha
            and cached.get("resolution_prompt_sha256") == res_sha
            and cached.get("papers_sha256") == p_sha
        ):
            return cached

    # Build paper year map and draft
    draft_id = store.get_draft_paper_id()
    paper_year: dict[str, int | None] = {m.paper_id: m.year for m in all_papers}

    # Build all section units (for prefilter)
    all_units = build_section_index()

    # Collect all verified gaps from all papers
    resolutions: dict[str, dict] = {}  # gap_id -> resolution record

    for meta in all_papers:
        pid = meta.paper_id
        gaps_payload = store.load_gaps(pid, prompt_sha=gap_sha)
        if gaps_payload is None:
            continue
        if gaps_payload.get("no_gap_sections"):
            continue

        gaps = gaps_payload.get("gaps", [])
        p_year = paper_year.get(pid)

        for gap in gaps:
            # Only process verified gaps
            evidence = gap.get("evidence", {})
            if not evidence.get("verified", False):
                continue

            gid = gap["gap_id"]
            statement = gap["statement"]

            # Find candidate papers: year > p_year OR (same year, different id) PLUS draft
            candidates: set[str] = set()
            if draft_id is not None:
                candidates.add(draft_id)

            for cand_meta in all_papers:
                cid = cand_meta.paper_id
                if cid == pid:
                    continue
                c_year = paper_year.get(cid)
                if p_year is None or c_year is None:
                    # Papers with unknown years are conservatively included as candidates
                    # to prevent silent exclusion when publication metadata is incomplete
                    candidates.add(cid)
                elif c_year > p_year or c_year == p_year:
                    candidates.add(cid)

            if not candidates:
                resolutions[gid] = {
                    "status": "open",
                    "resolved_by": None,
                    "rationale": "No candidate papers found.",
                    "evidence": {"quote": "", "verified": False},
                    "checked_papers": [],
                }
                continue

            # Prefilter: rank_units against candidate papers only
            cand_units = [u for u in all_units if u.get("paper_id") in candidates]
            if not cand_units:
                resolutions[gid] = {
                    "status": "open",
                    "resolved_by": None,
                    "rationale": "No section units for candidate papers.",
                    "evidence": {"quote": "", "verified": False},
                    "checked_papers": list(candidates),
                }
                continue

            q_tokens = tokenize(statement)
            ranked = rank_units(
                statement,
                q_tokens,
                cand_units,
                k=3,
                embed_query=embed_query,
            )

            best_score = _relevance_score(ranked[0] if ranked else None)

            if best_score < sim_threshold:
                # Below threshold: no LLM call — status open
                resolutions[gid] = {
                    "status": "open",
                    "resolved_by": None,
                    "rationale": f"No sufficiently similar content found (best score {best_score:.3f} < {sim_threshold}).",
                    "evidence": {"quote": "", "verified": False},
                    "checked_papers": list(candidates),
                }
                continue

            # Build candidate excerpts from top-3 ranked units
            excerpt_parts = []
            for r in ranked[:3]:
                unit = r["unit"]
                snippet = unit.get("text", "")[:600]
                excerpt_parts.append(f"[{unit.get('paper_id', '?')}]: {snippet}")
            candidate_excerpts = "\n\n".join(excerpt_parts)

            # One LLM call
            from research_companion.prompts import format_gap_resolution_prompt

            prompt = format_gap_resolution_prompt(
                gap_statement=statement,
                candidate_excerpts=candidate_excerpts,
            )
            try:
                raw = llm(prompt)
            except Exception:  # noqa: BLE001
                resolutions[gid] = {
                    "status": "open",
                    "resolved_by": None,
                    "rationale": "LLM call failed.",
                    "evidence": {"quote": "", "verified": False},
                    "checked_papers": list(candidates),
                }
                continue

            # Parse
            brace_idx = raw.find("{")
            try:
                res_data = json.loads(raw[brace_idx:]) if brace_idx != -1 else {}
            except (json.JSONDecodeError, ValueError):
                res_data = {}

            status = res_data.get("status", "open")
            if status not in ("addressed", "partially", "open"):
                status = "open"
            resolved_by = res_data.get("resolved_by")
            rationale = str(res_data.get("rationale", ""))
            ev_quote = str(res_data.get("evidence_quote", ""))

            # Sanitize resolved_by: must be a real candidate id or null
            if resolved_by is not None and resolved_by not in candidates:
                resolved_by = None

            # Verify evidence quote against excerpts
            ev_verified = False
            if ev_quote:
                ev_verified, _ = verify_quote(ev_quote, candidate_excerpts)

            # Honesty downgrade: addressed + unverified -> partially
            if status == "addressed" and ev_quote and not ev_verified:
                status = "partially"

            resolutions[gid] = {
                "status": status,
                "resolved_by": resolved_by,
                "rationale": rationale,
                "evidence": {"quote": ev_quote, "verified": ev_verified},
                "checked_papers": list(candidates),
            }

    result = {
        "gap_prompt_sha256": gap_sha,
        "resolution_prompt_sha256": res_sha,
        "papers_sha256": p_sha,
        "computed_at": _now_utc(),
        "resolutions": resolutions,
    }
    save_gap_resolution(result)
    return result


# ---------------------------------------------------------------------------
# gaps_overview
# ---------------------------------------------------------------------------

def gaps_overview() -> dict:
    """Build the GET /api/gaps shape.

    Returns:
        {
            "papers": [{paper_id, title, year, gaps: [{gap_id, statement, kind,
                        evidence: {quote, verified, match},
                        resolution: {...} | {"status": "open"}}]}],
            "draft_addresses": [gap_ids where resolved_by == draft],
            "stale": bool
        }
    """
    from research_companion import store
    from research_companion.prompts import gap_prompt_sha256, gap_resolution_prompt_sha256

    gap_sha = gap_prompt_sha256()
    res_sha = gap_resolution_prompt_sha256()

    all_papers = store.list_papers()
    paper_ids = [m.paper_id for m in all_papers]
    p_sha = _papers_sha(paper_ids)

    resolution_payload = store.load_gap_resolution()
    resolutions: dict[str, dict] = {}
    stale = True

    if resolution_payload is not None:
        resolutions = resolution_payload.get("resolutions", {})
        stale = not (
            resolution_payload.get("gap_prompt_sha256") == gap_sha
            and resolution_payload.get("resolution_prompt_sha256") == res_sha
            and resolution_payload.get("papers_sha256") == p_sha
        )

    draft_id = store.get_draft_paper_id()
    draft_addresses: list[str] = []
    papers_out: list[dict] = []

    for meta in all_papers:
        pid = meta.paper_id
        gaps_payload = store.load_gaps(pid, prompt_sha=gap_sha)
        if gaps_payload is None:
            continue
        if gaps_payload.get("no_gap_sections"):
            continue

        gaps = gaps_payload.get("gaps", [])
        if not gaps:
            continue

        gaps_out: list[dict] = []
        for gap in gaps:
            gid = gap["gap_id"]
            resolution = resolutions.get(gid, {"status": "open"})

            if (draft_id is not None
                    and resolution.get("resolved_by") == draft_id):
                draft_addresses.append(gid)

            gaps_out.append({
                "gap_id": gid,
                "statement": gap["statement"],
                "kind": gap["kind"],
                "evidence": gap["evidence"],
                "resolution": resolution,
            })

        if gaps_out:
            papers_out.append({
                "paper_id": pid,
                "title": meta.title,
                "year": meta.year,
                "gaps": gaps_out,
            })

    return {
        "papers": papers_out,
        "draft_addresses": draft_addresses,
        "stale": stale,
    }


# ---------------------------------------------------------------------------
# gaps_for_suggestions
# ---------------------------------------------------------------------------

def gaps_for_suggestions(
    *,
    sim_threshold: float = 0.35,
    embed_query: Callable[[str], list[float]] | None = None,
) -> list[dict]:
    """Compute relevance flags for the suggestions engine.

    Returns list of:
        {gap_id, statement, relevant: bool, addressed_by_draft: bool}

    relevant = resolution status in (open, partially) AND prefilter similarity
               vs draft units >= sim_threshold.
    addressed_by_draft = resolution.resolved_by == draft id.
    """
    from research_companion import store
    from research_companion.qa import build_section_index
    from research_companion.rank import tokenize
    from research_companion.retrieve import rank_units

    gap_sha = None
    try:
        from research_companion.prompts import gap_prompt_sha256
        gap_sha = gap_prompt_sha256()
    except Exception:  # noqa: BLE001
        pass

    draft_id = store.get_draft_paper_id()
    resolution_payload = store.load_gap_resolution()
    resolutions: dict[str, dict] = {}
    if resolution_payload is not None:
        resolutions = resolution_payload.get("resolutions", {})

    all_papers = store.list_papers()

    # Collect all gaps
    all_gap_items: list[dict] = []
    for meta in all_papers:
        pid = meta.paper_id
        gaps_payload = store.load_gaps(pid, prompt_sha=gap_sha)
        if gaps_payload is None:
            continue
        if gaps_payload.get("no_gap_sections"):
            continue
        for gap in gaps_payload.get("gaps", []):
            all_gap_items.append({
                "gap_id": gap["gap_id"],
                "statement": gap["statement"],
                "paper_id": pid,
            })

    if not all_gap_items:
        return []

    # Build draft units for relevance check
    draft_units: list[dict] = []
    if draft_id is not None:
        try:
            all_units = build_section_index()
            draft_units = [u for u in all_units if u.get("paper_id") == draft_id]
        except Exception:  # noqa: BLE001
            draft_units = []

    result: list[dict] = []
    for item in all_gap_items:
        gid = item["gap_id"]
        statement = item["statement"]
        resolution = resolutions.get(gid, {"status": "open"})

        status = resolution.get("status", "open")
        resolved_by = resolution.get("resolved_by")
        addressed_by_draft = (draft_id is not None and resolved_by == draft_id)

        # Compute relevance: needs open/partially AND similarity to draft >= threshold
        relevant = False
        if status in ("open", "partially") and draft_units:
            try:
                q_tokens = tokenize(statement)
                ranked = rank_units(
                    statement,
                    q_tokens,
                    draft_units,
                    k=1,
                    embed_query=embed_query,
                )
                best_score = _relevance_score(ranked[0] if ranked else None)
                relevant = best_score >= sim_threshold
            except Exception:  # noqa: BLE001
                relevant = False

        result.append({
            "gap_id": gid,
            "statement": statement,
            "relevant": relevant,
            "addressed_by_draft": addressed_by_draft,
        })

    return result


# ---------------------------------------------------------------------------
# Gap synthesis — cluster verified gaps into cross-corpus themes
# ---------------------------------------------------------------------------
#
# synthesize_gaps() pipeline:
#   1. _collect_verified_gaps (pure)  -- flatten gaps_overview() to verified gaps
#   2. one GAP_SYNTHESIS_PROMPT call  -- LLM groups near-duplicate gaps into themes
#   3. _assemble_themes (pure)        -- attach citations/status/type, drop invented ids
#   4. rank_gap_themes (pure)         -- deterministic score, stable sort desc
#
# Honesty: only verified gaps are ever offered to the LLM; any gap_id the LLM
# returns that isn't in the collected verified set is dropped (never invented
# into a citation); a theme left with zero valid members is dropped entirely.

_FWS_TYPES = {"method", "resources", "evaluation", "application", "problem", "other"}
_THEME_OPEN_WEIGHT = {"open": 2.0, "partial": 1.0, "addressed": 0.0}
_THEME_RECENCY_BASE_YEAR = 2000


def _collect_verified_gaps(overview: dict) -> list[dict]:
    """Flatten gaps_overview() to VERIFIED gaps only.

    Returns a list of {gap_id, statement, kind, paper_id, title, year, status}.
    Unverified gaps (evidence.verified is False) are dropped — synthesis must
    only ever see quote-verified gaps. status comes from the gap's resolution
    (default "open" when no resolution record exists yet).
    """
    out: list[dict] = []
    for paper in overview.get("papers", []):
        pid = paper.get("paper_id")
        title = paper.get("title", "")
        year = paper.get("year")
        for gap in paper.get("gaps", []):
            evidence = gap.get("evidence") or {}
            if not evidence.get("verified", False):
                continue
            resolution = gap.get("resolution") or {"status": "open"}
            out.append({
                "gap_id": gap["gap_id"],
                "statement": gap["statement"],
                "kind": gap.get("kind", "limitation"),
                "paper_id": pid,
                "title": title,
                "year": year,
                "status": resolution.get("status", "open"),
            })
    return out


def _assemble_themes(cluster_result: dict, index: dict[str, dict]) -> list[dict]:
    """Turn raw LLM theme groups into citation-backed theme records (no score yet).

    *cluster_result* is the parsed GAP_SYNTHESIS_PROMPT JSON:
        {"themes": [{"title", "bullet", "fws_type", "gap_ids": [...]}]}
    *index* maps gap_id -> the corresponding item from _collect_verified_gaps.

    Any gap_id in a theme's gap_ids that is not a key of *index* is dropped
    (honesty: the LLM groups gaps, it never invents one); a theme left with
    zero valid members after that filter is dropped entirely. theme_id is
    derived from the FINAL (filtered, sorted) member gap_ids, so it is
    reproducible from the assembled membership alone.
    """
    themes_out: list[dict] = []
    for raw in (cluster_result or {}).get("themes", []) or []:
        if not isinstance(raw, dict):
            continue
        gap_ids = [gid for gid in (raw.get("gap_ids") or []) if gid in index]
        if not gap_ids:
            continue

        members = [index[gid] for gid in gap_ids]

        citations: list[dict] = []
        seen_papers: set[str] = set()
        for m in members:
            if m["paper_id"] in seen_papers:
                continue
            seen_papers.add(m["paper_id"])
            citations.append({"paper_id": m["paper_id"], "title": m["title"], "year": m["year"]})

        frequency = len(citations)
        years = [c["year"] for c in citations if c["year"] is not None]
        recency = max(years) if years else None

        statuses = {m["status"] for m in members}
        if "open" in statuses:
            status = "open"
        elif "partially" in statuses:
            status = "partial"
        else:
            status = "addressed"

        kind_counts = Counter(m["kind"] for m in members)
        top_count = max(kind_counts.values())
        tied = sorted(k for k, c in kind_counts.items() if c == top_count)
        dominant_kind = "limitation" if "limitation" in tied else tied[0]

        raw_fws = str(raw.get("fws_type", "other")).strip().lower()
        fws_type = raw_fws if raw_fws in _FWS_TYPES else "other"

        theme_id = "theme_" + hashlib.sha256(
            "|".join(sorted(gap_ids)).encode("utf-8")
        ).hexdigest()[:12]

        themes_out.append({
            "theme_id": theme_id,
            "title": str(raw.get("title", "")).strip() or "Untitled theme",
            "bullet": str(raw.get("bullet", "")).strip(),
            "fws_type": fws_type,
            "type": dominant_kind,
            "citations": citations,
            "status": status,
            "frequency": frequency,
            "recency": recency,
            "gap_ids": gap_ids,
        })
    return themes_out


def rank_gap_themes(themes: list[dict]) -> list[dict]:
    """Attach a deterministic `score` to each theme and sort descending, stable.

    score = 3.0*frequency + 0.1*(recency - 2000) [0 if recency is None] + open_weight
    where open_weight is 2.0 for status=="open", 1.0 for "partial", 0.0 for
    "addressed"/anything else. Does not mutate the input dicts (returns new
    dicts with `score` added). Python's sort is stable, so themes with an
    identical score keep their original relative order.
    """
    scored: list[dict] = []
    for t in themes:
        recency = t.get("recency")
        recency_weight = 0.1 * (recency - _THEME_RECENCY_BASE_YEAR) if recency is not None else 0.0
        open_weight = _THEME_OPEN_WEIGHT.get(t.get("status"), 0.0)
        score = round(3.0 * (t.get("frequency") or 0) + recency_weight + open_weight, 4)
        scored.append({**t, "score": score})
    return sorted(scored, key=lambda t: -t["score"])
