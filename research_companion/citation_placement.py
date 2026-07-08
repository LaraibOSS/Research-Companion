"""Citation placement check — is each cited paper in the right draft section?

This is a *draft-quality* signal and is deliberately kept separate from paper
strength scoring (``research_companion/strength.py``), which is left untouched. A
paper's strength describes the paper; placement describes the user's writing.

For numbered citation styles, this module maps each in-text ``[n]`` marker to the
library paper it cites (reusing ``citations_coverage`` for the bibliography ->
library mapping), finds which draft section the marker sits in, and compares that
against where the alignment engine (``alignment.py``) judges the paper most
relevant. It then flags "you cited X in Methods, but it's most relevant to
Related Work".

Scope (v1): numbered bibliographies only. Author-year markers such as
"(Smith et al., 2020)" have no parser and are ambiguous, so drafts without a
numbered bibliography return ``applicable=False`` with a ``reason`` rather than a
misleading empty result.

Note: alignment only ranks a candidate's top-5 lexically-relevant sections, so a
section absent from a candidate's alignment list is *unranked*, not known to be
irrelevant. Classification reflects that (a definite "misplaced" requires a
clearly-relevant section to exist elsewhere).

Statuses:
    well_placed — cited in a section the paper is genuinely relevant to
    misplaced   — cited only where it isn't relevant, while a clearly more
                  relevant section exists elsewhere
    unknown     — cited but never alignment-scored, or no strongly relevant
                  section anywhere
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from research_companion.sections import Section, section_for_offset
from research_companion.store import papergraph_dir

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# A cited section counts as a good home when the paper's alignment relevance
# there meets this bar; a definite "misplaced" requires a relevant section this
# strong to exist somewhere the paper was NOT cited.
WELL_PLACED_MIN = 0.5
MISPLACED_MIN = 0.5

_MIN_ENTRIES = 3  # matches citations_coverage; a numbered bib needs a few entries

# In-text numbered citation markers: [3], [3,4], [3-5], [3, 4, 7].
# Inner group is digits plus separators (comma, whitespace, hyphen, en-dash).
_MARKER_RE = re.compile(r"\[([0-9][0-9,\s–\-]*)\]")

# References/bibliography section title (mirrors citations_coverage).
_REFS_TITLE_RE = re.compile(r"references|bibliograph", re.IGNORECASE)

_now = lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")  # noqa: E731


# ---------------------------------------------------------------------------
# In-text marker parsing
# ---------------------------------------------------------------------------

def _expand_marker(inner: str) -> list[int]:
    """Expand a marker body like "3, 4-6" into [3, 4, 5, 6]. Empty on garbage."""
    nums: list[int] = []
    for part in re.split(r"[,\s]+", inner.strip()):
        if not part:
            continue
        rng = re.match(r"^(\d+)[–\-](\d+)$", part)
        if rng:
            lo, hi = int(rng.group(1)), int(rng.group(2))
            if lo <= hi and hi - lo < 100:  # sane range only
                nums.extend(range(lo, hi + 1))
        elif part.isdigit():
            nums.append(int(part))
    return nums


def _bibliography_is_numbered(block: str) -> bool:
    """True when the References block uses numbered entries ([n] or n.).

    Mirrors the strategy-A/B detection in ``citations_coverage.split_bibliography``
    so we only claim applicability for styles whose in-text ``[n]`` markers line
    up with bibliography ordinals.
    """
    for pat in (r"(?m)^\s*\[(\d{1,3})\]", r"(?m)^\s*(\d{1,3})\.\s+\S"):
        marks = [int(m.group(1)) for m in re.finditer(pat, block)]
        if len(marks) >= _MIN_ENTRIES and marks[0] <= 5:
            increasing = sum(1 for a, b in zip(marks, marks[1:]) if b > a)
            if len(marks) == 1 or increasing >= (len(marks) - 1) * 0.7:
                return True
    return False


def _refs_char_start(sections_payload: dict | None) -> int | None:
    """Char offset where the References section begins, or None if not found.

    Returns the LAST refs-like section's ``char_start`` so body scanning can
    exclude the bibliography (whose own ``[n]`` entry markers must not be counted
    as in-text citations).
    """
    if not sections_payload or not isinstance(sections_payload.get("sections"), list):
        return None
    start: int | None = None
    for s in sections_payload["sections"]:
        if not isinstance(s, dict):
            continue
        if _REFS_TITLE_RE.search(str(s.get("title", ""))):
            try:
                start = int(s["char_start"])  # last one wins
            except (KeyError, ValueError, TypeError):
                continue
    return start


# ---------------------------------------------------------------------------
# Persistence (mirrors citations_coverage)
# ---------------------------------------------------------------------------

def placement_path() -> Path:
    return papergraph_dir() / "citation_placement.json"


def load_placement() -> dict | None:
    p = placement_path()
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def save_placement(payload: dict) -> Path:
    p = placement_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)
    return p


def empty_placement(draft_paper_id: str | None) -> dict:
    """Valid-but-empty payload (no draft set / draft has no text). Not persisted."""
    return _base_payload(
        draft_paper_id,
        None,
        applicable=False,
        reason="No draft is set." if draft_paper_id is None else "The draft has no text yet.",
    )


def _base_payload(
    draft_id: str | None, text: str | None, *, applicable: bool, reason: str,
) -> dict:
    return {
        "version": 1,
        "draft_paper_id": draft_id,
        "draft_text_sha256": hashlib.sha256(text.encode()).hexdigest() if text else None,
        "applicable": applicable,
        "reason": reason,
        "computed_at": _now(),
        "placements": [],
        "counts": {"total": 0, "well_placed": 0, "misplaced": 0, "unknown": 0},
    }


def _recount(payload: dict) -> None:
    counts = {"total": 0, "well_placed": 0, "misplaced": 0, "unknown": 0}
    for pl in payload["placements"]:
        counts["total"] += 1
        counts[pl["status"]] = counts.get(pl["status"], 0) + 1
    payload["counts"] = counts


def is_stale(payload: dict | None, draft_id: str | None) -> bool:
    """True when the cached placement no longer describes the current draft text."""
    if payload is None or draft_id is None:
        return True
    if payload.get("draft_paper_id") != draft_id:
        return True
    from research_companion.store import load_text
    text = load_text(draft_id) or ""
    return payload.get("draft_text_sha256") != hashlib.sha256(text.encode()).hexdigest()


# ---------------------------------------------------------------------------
# compute_placement (offline)
# ---------------------------------------------------------------------------

def _section_titles(cited_sections: list[dict]) -> str:
    return ", ".join(cs["title"] for cs in cited_sections) or "an unlabelled section"


def compute_placement(draft_id: str) -> dict:
    """Compute + persist the citation-placement report for a draft. Offline.

    Reuses citations_coverage for the bibliography->library mapping and
    store.load_alignment for per-section relevance. Never hits the network.
    """
    from research_companion import citations_coverage as cc
    from research_companion import store

    text = store.load_text(draft_id)
    if not text:
        return empty_placement(draft_id)

    sections_payload = store.load_sections(draft_id)
    sections = [
        Section(**s) for s in (sections_payload or {}).get("sections", [])
        if isinstance(s, dict)
    ]

    # Bibliography -> library mapping (reused, computed if stale).
    coverage = cc.load_coverage()
    if cc.is_stale(coverage, draft_id):
        coverage = cc.compute_coverage(draft_id)

    if coverage.get("source") != "bibliography":
        payload = _base_payload(
            draft_id, text, applicable=False,
            reason="The draft has no parsed numbered bibliography. Placement "
                   "checking supports numbered [n] citation styles only.",
        )
        save_placement(payload)
        return payload

    block = cc.find_references_block(text, sections_payload)
    if not block or not _bibliography_is_numbered(block):
        payload = _base_payload(
            draft_id, text, applicable=False,
            reason="The draft's bibliography is not numbered. Author-year "
                   "citation styles are not supported yet.",
        )
        save_placement(payload)
        return payload

    references = coverage.get("references", [])

    # Scan only the body (everything before the References section).
    refs_start = _refs_char_start(sections_payload)
    body = text[:refs_start] if refs_start is not None else text

    # paper_id -> {section_id: title} where it is cited
    cited: dict[str, dict[str, str]] = {}
    for m in _MARKER_RE.finditer(body):
        nums = _expand_marker(m.group(1))
        if not nums:
            continue
        sec = section_for_offset(sections, m.start())
        for n in nums:
            idx = n - 1  # in-text [1] -> references[0]
            if idx < 0 or idx >= len(references):
                continue
            pid = references[idx].get("matched_paper_id")
            if not pid:
                continue  # cited paper not in library — can't judge placement
            entry = cited.setdefault(pid, {})
            if sec is not None:
                entry[sec.section_id] = sec.title

    papers = {p.paper_id: p for p in store.list_papers()}
    placements: list[dict] = []
    for pid, sec_map in cited.items():
        meta = papers.get(pid)
        paper_title = meta.title if meta else pid
        cited_sections = [{"section_id": sid, "title": t} for sid, t in sec_map.items()]
        cited_ids = set(sec_map.keys())

        alignment = store.load_alignment(pid, draft_paper_id=draft_id)
        best_relevant = None
        if alignment is None:
            status = "unknown"
            detail = "Cited, but not yet scored for relevance against the draft."
        else:
            align_secs = alignment.get("sections", [])
            rel_by_sid = {
                s.get("section_id"): float(s.get("relevance", 0.0)) for s in align_secs
            }
            if align_secs:
                top = max(align_secs, key=lambda s: float(s.get("relevance", 0.0)))
                best_relevant = {
                    "section_id": top.get("section_id"),
                    "title": top.get("section_title", top.get("section_id")),
                    "relevance": round(float(top.get("relevance", 0.0)), 4),
                }
            well = [sid for sid in cited_ids if rel_by_sid.get(sid, 0.0) >= WELL_PLACED_MIN]
            if well:
                status = "well_placed"
                detail = f"Cited in {_section_titles(cited_sections)}, where it is relevant."
            elif (best_relevant and best_relevant["relevance"] >= MISPLACED_MIN
                  and best_relevant["section_id"] not in cited_ids):
                status = "misplaced"
                detail = (f"Cited in {_section_titles(cited_sections)}; "
                          f"most relevant to {best_relevant['title']}.")
            else:
                status = "unknown"
                detail = (f"Cited in {_section_titles(cited_sections)}; "
                          "no strongly relevant section found.")

        placements.append({
            "paper_id": pid,
            "paper_title": paper_title,
            "cited_sections": cited_sections,
            "best_relevant_section": best_relevant,
            "status": status,
            "detail": detail,
        })

    # Stable order: misplaced first (most actionable), then unknown, then well_placed.
    order = {"misplaced": 0, "unknown": 1, "well_placed": 2}
    placements.sort(key=lambda pl: (order.get(pl["status"], 9), pl["paper_title"].lower()))

    payload = _base_payload(draft_id, text, applicable=True, reason="")
    payload["placements"] = placements
    _recount(payload)
    save_placement(payload)
    return payload
