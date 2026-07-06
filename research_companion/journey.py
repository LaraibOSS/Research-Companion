"""Research-journey engine for Research Companion v0.3.

Tracks draft versions and suggestion-addressing events over time. Provides:
  - load_journey() / save helpers: persistent journey.json
  - log_event(): append a timestamped event
  - record_draft_version(): snapshot paper_id + section/claim counts; no-op if unchanged
  - match_open_suggestions(): conservative deterministic auto-matching on new draft
  - journey_summary(): structured summary for the Home view (F2)
  - fold_counts(): pure helper for counts_over_time — unit-testable directly

Conservative design principle: a suggestion is only marked addressed on
STRONG deterministic evidence or an LLM response whose verbatim evidence quote
verifies against the excerpt. When in doubt, leave open.
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from research_companion.store import papergraph_dir

# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def _journey_path() -> Path:
    return papergraph_dir() / "journey.json"


def _default_journey() -> dict:
    return {"version": 1, "draft_versions": [], "events": []}


def load_journey() -> dict:
    """Load journey.json; return default if missing or corrupt."""
    p = _journey_path()
    if not p.exists():
        return _default_journey()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return _default_journey()
        # Ensure expected keys
        data.setdefault("version", 1)
        data.setdefault("draft_versions", [])
        data.setdefault("events", [])
        return data
    except (json.JSONDecodeError, ValueError):
        return _default_journey()


def _save_journey(journey: dict) -> None:
    p = _journey_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(journey, indent=2, ensure_ascii=False), encoding="utf-8")


def _now_utc(now: datetime | None = None) -> str:
    dt = now or datetime.now(timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# log_event
# ---------------------------------------------------------------------------

def log_event(kind: str, data: dict, *, now: datetime | None = None) -> None:
    """Append {"at", "kind", "data"} to journey events."""
    journey = load_journey()
    journey["events"].append({
        "at": _now_utc(now),
        "kind": kind,
        "data": data,
    })
    _save_journey(journey)


# ---------------------------------------------------------------------------
# record_draft_version
# ---------------------------------------------------------------------------

def record_draft_version(paper_id: str, *, now: datetime | None = None) -> dict | None:
    """Record a new draft version snapshot.

    Returns None (no-op) if paper_id matches the latest version's paper_id.
    Otherwise appends a version record and logs "version_added" event, returning
    the new version dict.
    """
    journey = load_journey()
    versions = journey["draft_versions"]

    # No-op if same paper_id as latest version
    if versions and versions[-1].get("paper_id") == paper_id:
        return None

    # Count sections and claims when available
    n_sections = 0
    n_claims = 0
    try:
        from research_companion.store import load_sections
        sections_payload = load_sections(paper_id)
        if sections_payload:
            n_sections = len(sections_payload.get("sections", []))
    except Exception:  # noqa: BLE001
        pass

    try:
        from research_companion.prompts import extraction_prompt_sha256
        from research_companion.store import load_extraction
        ext = load_extraction(paper_id, prompt_sha=extraction_prompt_sha256())
        if ext:
            n_claims = len(ext.get("claims", []))
    except Exception:  # noqa: BLE001
        pass

    version_num = len(versions) + 1
    now_str = _now_utc(now)
    version_record = {
        "version": version_num,
        "paper_id": paper_id,
        "added_at": now_str,
        "n_sections": n_sections,
        "n_claims": n_claims,
    }

    journey["draft_versions"].append(version_record)
    journey["events"].append({
        "at": now_str,
        "kind": "version_added",
        "data": {
            "version": version_num,
            "paper_id": paper_id,
            "n_sections": n_sections,
            "n_claims": n_claims,
        },
    })
    _save_journey(journey)
    return version_record


# ---------------------------------------------------------------------------
# Conservative per-kind matchers
# ---------------------------------------------------------------------------

_RELATED_SECTION_RE = re.compile(r"related|reference|bibliograph", re.IGNORECASE)
_STOPWORDS = frozenset({
    "the", "a", "an", "of", "in", "on", "to", "for", "and", "or", "is", "are",
    "what", "which", "how", "why", "do", "does", "did", "this", "that", "these",
    "those", "with", "from", "by", "as", "be", "been", "being", "was", "were",
    "it", "its", "they", "them", "their", "there", "here", "we", "you",
})


def _tokenize_lower(s: str) -> list[str]:
    """Lowercase alphanumeric tokens length >= 3."""
    return re.findall(r"[a-z0-9]{3,}", s.lower())


def _token_jaccard(a: str, b: str) -> float:
    """Token-level Jaccard similarity between two strings."""
    ta = set(_tokenize_lower(a))
    tb = set(_tokenize_lower(b))
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _sentence_windows(text: str, window: int = 3) -> list[str]:
    """Split text into sentences and yield overlapping windows of *window* sentences."""
    # Simple sentence split on '. ' or '\n'
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    parts = [p.strip() for p in parts if p.strip()]
    if not parts:
        return [text]
    windows = []
    for i in range(len(parts)):
        chunk = " ".join(parts[i:i + window])
        windows.append(chunk)
    return windows or [text]


def _best_jaccard_vs_text(claim_text: str, draft_text: str) -> float:
    """Return the highest token-Jaccard of claim_text vs any sentence-window."""
    if not draft_text:
        return 0.0
    best = 0.0
    for window in _sentence_windows(draft_text):
        j = _token_jaccard(claim_text, window)
        if j > best:
            best = j
    return best


def _related_section_text(draft_text: str, sections_payload: dict | None) -> str:
    """Extract text from related work / reference / bibliography sections."""
    if sections_payload:
        relevant_parts = []
        for sec in sections_payload.get("sections", []):
            title = sec.get("title", "")
            if _RELATED_SECTION_RE.search(title):
                relevant_parts.append(sec.get("text", ""))
        if relevant_parts:
            return "\n".join(relevant_parts)

    # Fallback: scan raw text for lines near "References" / "Related Work" headings
    lines = draft_text.split("\n")
    capturing = False
    captured: list[str] = []
    for line in lines:
        stripped = line.strip()
        if _RELATED_SECTION_RE.search(stripped) and len(stripped) < 60:
            capturing = True
        elif capturing:
            # Stop at next short heading-like line
            if stripped and len(stripped) < 60 and stripped[0].isupper() and not stripped.endswith("."):
                break
            captured.append(line)
    return "\n".join(captured) if captured else draft_text


def _match_related_work(sug: dict, draft_text: str, sections_payload: dict | None) -> bool:
    """related_work / evidence (paper-sourced): check if candidate title tokens appear in ref sections."""
    source = sug.get("source", {})
    if source.get("type") != "paper":
        return False

    # Get candidate paper title
    candidate_id = source.get("paper_id", "")
    paper_label = candidate_id
    try:
        from research_companion.store import PaperMetadata
        meta = PaperMetadata.load(candidate_id)
        if meta is not None:
            paper_label = meta.title
    except Exception:  # noqa: BLE001
        pass

    # Title tokens: len >= 4, non-stopword
    title_tokens = [
        t for t in _tokenize_lower(paper_label)
        if len(t) >= 4 and t not in _STOPWORDS
    ]
    if not title_tokens:
        return False

    ref_text = _related_section_text(draft_text, sections_payload).lower()
    # Need >= 60% of title tokens to appear in ref text
    found = sum(1 for t in title_tokens if t in ref_text)
    return found / len(title_tokens) >= 0.6


def _match_gap(sug: dict, draft_text: str, sections_payload: dict | None) -> bool:
    """gap: top-5 highest-IDF tokens ALL present in draft text."""
    # Collect corpus (draft sections or just the full text)
    corpus_docs: list[list[str]] = []
    if sections_payload:
        for sec in sections_payload.get("sections", []):
            corpus_docs.append(_tokenize_lower(sec.get("text", "")))
    if not corpus_docs:
        corpus_docs = [_tokenize_lower(draft_text)]

    # Compute DF
    df: dict[str, int] = {}
    n_docs = len(corpus_docs)
    for doc in corpus_docs:
        for t in set(doc):
            df[t] = df.get(t, 0) + 1

    import math

    def _idf(term: str) -> float:
        d = df.get(term, 0)
        return math.log((n_docs + 1) / (d + 1))

    # Get gap statement from the suggestion
    gap_text = sug.get("detail", "") or sug.get("title", "")
    gap_tokens = _tokenize_lower(gap_text)
    if not gap_tokens:
        return False

    # Top-5 highest-IDF tokens
    scored = sorted(gap_tokens, key=lambda t: -_idf(t))
    top5 = scored[:5]

    draft_lower = draft_text.lower()
    return all(t in draft_lower for t in top5)


def _make_claim_candidate(sug: dict, draft_text: str, threshold: float) -> bool:
    """novelty/evidence (lane-sourced): determine if this suggestion is a CANDIDATE for LLM check."""
    source = sug.get("source", {})
    if source.get("type") != "lane":
        return False

    # Claim text from _source_key (raw claim text was used as source_key)
    # Try title and detail to reconstruct claim context
    claim_text = sug.get("_source_key", "") or sug.get("title", "")

    best_sim = _best_jaccard_vs_text(claim_text, draft_text)
    # If best similarity < (1 - threshold), claim was substantially rewritten/removed
    return best_sim < (1.0 - threshold)


# ---------------------------------------------------------------------------
# LLM check helper
# ---------------------------------------------------------------------------

def _llm_check_addressed(
    sug: dict,
    new_draft_id: str,
    draft_text: str,
    sections_payload: dict | None,
    llm: Callable[[str], str],
) -> bool:
    """Use LLM to confirm whether a candidate suggestion was addressed.

    Returns True only if:
    - LLM returns addressed=true
    - evidence quote verifies verbatim against the excerpt

    Any failure (bad JSON, unverified evidence, exception) -> returns False.
    """
    try:
        from research_companion.prompts import format_addressed_check_prompt
        from research_companion.rank import tokenize
        from research_companion.rebuttal.verify import verify_quote
        from research_companion.retrieve import rank_units

        # Build units from sections
        units: list[dict] = []
        if sections_payload:
            for sec in sections_payload.get("sections", []):
                sec_text = sec.get("text", "")
                units.append({
                    "paper_id": new_draft_id,
                    "section_id": sec.get("section_id", ""),
                    "section_title": sec.get("title", ""),
                    "paper_title": "",
                    "text": sec_text,
                    "tokens": tokenize(sec_text),
                })
        if not units:
            # Fallback: single unit from full text
            units = [{
                "paper_id": new_draft_id,
                "section_id": "full",
                "section_title": "Full Text",
                "paper_title": "",
                "text": draft_text[:4000],
                "tokens": tokenize(draft_text[:4000]),
            }]

        query = (sug.get("title", "") + " " + sug.get("detail", "")).strip()
        q_tokens = tokenize(query)
        ranked = rank_units(query, q_tokens, units, k=3, embed_query=None)
        excerpt_parts = [r["unit"]["text"] for r in ranked]
        excerpt = "\n\n---\n\n".join(excerpt_parts)

        # Fallback: when BM25 finds no matches (query tokens absent from units),
        # use the first 3 sections or truncated full text as excerpt.
        if not excerpt:
            excerpt = "\n\n---\n\n".join(u["text"] for u in units[:3]) if units else draft_text[:3000]

        if not excerpt:
            return False

        sug_block = f"Kind: {sug.get('kind', '')}\nTitle: {sug.get('title', '')}\nDetail: {sug.get('detail', '')}"
        prompt = format_addressed_check_prompt(sug_block, excerpt)

        raw = llm(prompt)
        data = json.loads(raw)
        addressed = bool(data.get("addressed", False))
        if not addressed:
            return False

        evidence = data.get("evidence", "")
        if not evidence or not evidence.strip():
            return False

        ok, _ = verify_quote(evidence, excerpt)
        return ok

    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
# match_open_suggestions
# ---------------------------------------------------------------------------

def match_open_suggestions(
    new_draft_id: str,
    *,
    llm: Callable[[str], str] | None = None,
    threshold: float = 0.6,
    now: datetime | None = None,
) -> list[dict]:
    """Match open suggestions against a new draft version.

    For each open suggestion, apply per-kind conservative matchers.
    Returns list of newly-addressed suggestion dicts.
    """
    from research_companion.store import load_sections, load_text
    from research_companion.suggestions import load_suggestions, save_suggestions

    payload = load_suggestions(new_draft_id)
    if payload is None:
        return []

    sugs = payload.get("suggestions", [])
    open_sugs = [s for s in sugs if s.get("status") == "open"]
    if not open_sugs:
        return []

    # Load draft text and sections
    draft_text = load_text(new_draft_id) or ""
    sections_payload = load_sections(new_draft_id)
    now_str = _now_utc(now)

    addressed_ids: set[str] = set()
    addressed_by_map: dict[str, dict] = {}

    for sug in open_sugs:
        kind = sug.get("kind", "")
        sug_id = sug.get("id", "")

        # citation / structure / benchmark: never auto-matched
        if kind in ("citation", "structure", "benchmark"):
            continue

        by_auto = False
        is_candidate = False

        if kind in ("related_work",) or (
            kind == "evidence" and sug.get("source", {}).get("type") == "paper"
        ):
            # Paper-sourced: check title tokens in ref sections
            by_auto = _match_related_work(sug, draft_text, sections_payload)

        elif kind == "gap":
            by_auto = _match_gap(sug, draft_text, sections_payload)

        elif kind in ("novelty", "evidence") and sug.get("source", {}).get("type") == "lane":
            # Lane-sourced claim: check if claim was substantially rewritten
            is_candidate = _make_claim_candidate(sug, draft_text, threshold)
            if is_candidate and llm is not None:
                # Try LLM confirmation
                confirmed = _llm_check_addressed(
                    sug, new_draft_id, draft_text, sections_payload, llm
                )
                if confirmed:
                    by_auto = False  # mark as "llm"
                    addressed_ids.add(sug_id)
                    addressed_by_map[sug_id] = {
                        "by": "llm",
                        "note": "LLM confirmed with verified evidence",
                        "version": payload.get("draft_version", ""),
                    }
                    continue
            # Without LLM or LLM failed: stay open
            continue

        if by_auto:
            addressed_ids.add(sug_id)
            addressed_by_map[sug_id] = {
                "by": "auto",
                "note": f"{kind} match: deterministic rule",
                "version": payload.get("draft_version", ""),
            }

    if not addressed_ids:
        return []

    # Update suggestions in payload
    newly_addressed = []
    for sug in sugs:
        sug_id = sug.get("id", "")
        if sug_id in addressed_ids:
            sug = dict(sug)
            sug["status"] = "addressed"
            sug["addressed_at"] = now_str
            sug["addressed_by"] = addressed_by_map[sug_id]
            newly_addressed.append(sug)

    # Rebuild sugs list
    updated_sugs = []
    addressed_map = {s["id"]: s for s in newly_addressed}
    for sug in sugs:
        sug_id = sug.get("id", "")
        if sug_id in addressed_map:
            updated_sugs.append(addressed_map[sug_id])
        else:
            updated_sugs.append(sug)

    payload["suggestions"] = updated_sugs
    save_suggestions(new_draft_id, payload)

    # Log events
    journey = load_journey()
    for sug in newly_addressed:
        journey["events"].append({
            "at": now_str,
            "kind": "suggestion_addressed",
            "data": {
                "suggestion_id": sug["id"],
                "suggestion_title": sug.get("title", ""),
                "addressed_by": sug["addressed_by"],
                "paper_id": new_draft_id,
            },
        })
    _save_journey(journey)

    return newly_addressed


# ---------------------------------------------------------------------------
# fold_counts — pure helper
# ---------------------------------------------------------------------------

def fold_counts(
    versions: list[dict],
    events: list[dict],
    suggestions: list[dict],
) -> list[dict]:
    """Compute counts_over_time from a fold over events between version markers.

    For each version, returns the cumulative counts of open/addressed/dismissed
    suggestions as of that version based on the current suggestions payload
    (not historical reconstruction — this is an approximation sufficient for
    the Home view timeline).

    Pure function: no I/O.
    """
    if not versions:
        return []

    # Use the current suggestions state as the reference
    result = []
    for ver in versions:
        ver_at = ver.get("added_at", "")
        # Count suggestions based on events up to this version point
        # Simple approach: use current status but tag with version snapshot
        # For the timeline we count how many suggestion_addressed events occurred
        # up to (and including) this version's timestamp.
        addressed_count = 0
        dismissed_count = 0
        for evt in events:
            if evt.get("at", "") > ver_at:
                break
            ek = evt.get("kind", "")
            if ek == "suggestion_addressed":
                addressed_count += 1
            elif ek == "suggestion_dismissed":
                dismissed_count += 1

        total = len(suggestions)
        open_count = max(0, total - addressed_count - dismissed_count)
        result.append({
            "version": ver.get("version"),
            "at": ver_at,
            "open": open_count,
            "addressed": addressed_count,
            "dismissed": dismissed_count,
        })

    return result


# ---------------------------------------------------------------------------
# journey_summary
# ---------------------------------------------------------------------------

def journey_summary() -> dict:
    """Return a structured summary for the Home view.

    Shape:
        {
            "versions": [...],
            "events": [...newest first...],
            "counts_over_time": [{"version", "at", "open", "addressed", "dismissed"}],
            "current": {"open", "addressed", "dismissed"},
        }
    """
    from research_companion.store import get_draft_paper_id
    from research_companion.suggestions import load_suggestions

    journey = load_journey()
    versions = journey.get("draft_versions", [])
    events = journey.get("events", [])

    # Load current suggestions for the configured draft
    suggestions: list[dict] = []
    draft_id = get_draft_paper_id()
    if draft_id is not None:
        payload = load_suggestions(draft_id)
        if payload is not None:
            suggestions = payload.get("suggestions", [])

    current: dict[str, Any] = {
        "open": sum(1 for s in suggestions if s.get("status") == "open"),
        "addressed": sum(1 for s in suggestions if s.get("status") == "addressed"),
        "dismissed": sum(1 for s in suggestions if s.get("status") == "dismissed"),
    }

    counts_over_time = fold_counts(versions, events, suggestions)

    return {
        "versions": versions,
        "events": list(reversed(events)),  # newest first
        "counts_over_time": counts_over_time,
        "current": current,
    }
