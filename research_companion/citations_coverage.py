"""Citation coverage — the draft's bibliography as ground truth for the library.

Parses the draft's References section (offline), matches every cited paper
against the library, and records which missing ones are downloadable. The
result drives the Citations panel, the "Add missing cited papers" action, and
the holistic-analysis disclaimer banner.

Pipeline (all offline unless noted):
    find_references_block -> split_bibliography -> parse_reference_string
    -> match_reference_to_library -> compute_coverage (persisted)
    -> resolve_missing (NETWORK, explicit job only)

Statuses:
    in_library  — matched a library paper (id first, then title containment)
    available   — not in library, but has a downloadable id (parsed or resolved)
    unchecked   — title-only; network resolution has not run
    unresolved  — resolution ran and found no confident match
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from research_companion.refcheck.matching import _last_name, normalize_title, title_similarity
from research_companion.refcheck.parse import parse_reference_string
from research_companion.refcheck.retrieval import (
    _crossref_search,
    _openalex_search,
    parse_crossref_item,
    parse_openalex_item,
)
from research_companion.refcheck.validate import Reference
from research_companion.store import PaperMetadata, make_arxiv_id, papergraph_dir

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REFS_HEADING_RE = re.compile(
    r"^\s*(?:\d+\.?\s+)?(references|bibliography)\s*$", re.IGNORECASE)
_SECTION_TITLE_RE = re.compile(r"references|bibliograph", re.IGNORECASE)
_AFTER_REFS_HEADING_RE = re.compile(
    r"^\s*(?:\d+\.?\s+)?(appendix|appendices|acknowledg\w*|supplementary)\b",
    re.IGNORECASE)

_MIN_ENTRIES = 3
_MIN_ENTRY_LEN = 20
_MAX_ENTRY_LEN = 1000
_MAX_ENTRIES = 300
_MIN_CONTAINMENT_TITLE = 15   # normalized chars; shorter titles risk false hits
_TITLE_SIM_THRESHOLD = 0.9
_RESOLVE_SIM_THRESHOLD = 0.75

_now = lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")  # noqa: E731


# ---------------------------------------------------------------------------
# 1. Locate the References block
# ---------------------------------------------------------------------------

def find_references_block(text: str, sections_payload: dict | None = None) -> str | None:
    """Slice the References/Bibliography block out of the draft text.

    Prefers the sections payload (char offsets into the same text); falls back
    to scanning for a bare heading line. Returns None when no block is found.
    """
    if sections_payload and isinstance(sections_payload.get("sections"), list):
        candidates = [
            s for s in sections_payload["sections"]
            if isinstance(s, dict) and _SECTION_TITLE_RE.search(str(s.get("title", "")))
        ]
        if candidates:
            sec = candidates[-1]  # LAST refs-like section
            try:
                block = text[int(sec["char_start"]):int(sec["char_end"])]
            except (KeyError, ValueError, TypeError):
                block = ""
            if block.strip():
                # Drop the heading line itself if present
                lines = block.splitlines()
                if lines and _REFS_HEADING_RE.match(lines[0]):
                    lines = lines[1:]
                return "\n".join(lines).strip() or None

    # Raw-text fallback: LAST short line that is exactly a refs heading
    lines = text.splitlines()
    heading_idx = None
    for i, line in enumerate(lines):
        if len(line) < 40 and _REFS_HEADING_RE.match(line):
            heading_idx = i
    if heading_idx is None:
        return None
    end_idx = len(lines)
    for j in range(heading_idx + 1, len(lines)):
        if len(lines[j]) < 40 and _AFTER_REFS_HEADING_RE.match(lines[j]):
            end_idx = j
            break
    block = "\n".join(lines[heading_idx + 1:end_idx]).strip()
    return block or None


# ---------------------------------------------------------------------------
# 2. Split the block into entries
# ---------------------------------------------------------------------------

def _roughly_ascending(nums: list[int]) -> bool:
    """True when the marker numbers look like entry numbers, not page noise."""
    if not nums:
        return False
    if nums[0] > 5:  # bibliographies start at 1 (tolerate a couple of misses)
        return False
    increasing = sum(1 for a, b in zip(nums, nums[1:], strict=False) if b > a)
    return len(nums) == 1 or increasing >= (len(nums) - 1) * 0.7


def _finish(parts: list[str]) -> list[str]:
    out = []
    for p in parts:
        entry = " ".join(line.strip() for line in p.splitlines() if line.strip())
        if _MIN_ENTRY_LEN <= len(entry) <= _MAX_ENTRY_LEN:
            out.append(entry)
    return out[:_MAX_ENTRIES]


def split_bibliography(block: str) -> list[str]:
    """Split a References block into individual entries.

    Strategies in order (each must yield >= 3 plausible entries):
    bracket-numbered [n] -> dot-numbered n. -> blank-line blocks ->
    year-anchored accumulation. Returns [] when nothing works.
    """
    if not block or not block.strip():
        return []

    # A: bracket-numbered
    marks = list(re.finditer(r"(?m)^\s*\[(\d{1,3})\]", block))
    if len(marks) >= _MIN_ENTRIES and _roughly_ascending([int(m.group(1)) for m in marks]):
        parts = [block[m.start():marks[i + 1].start() if i + 1 < len(marks) else len(block)]
                 for i, m in enumerate(marks)]
        entries = _finish(parts)
        if len(entries) >= _MIN_ENTRIES:
            return entries

    # B: dot-numbered
    marks = list(re.finditer(r"(?m)^\s*(\d{1,3})\.\s+\S", block))
    if len(marks) >= _MIN_ENTRIES and _roughly_ascending([int(m.group(1)) for m in marks]):
        parts = [block[m.start():marks[i + 1].start() if i + 1 < len(marks) else len(block)]
                 for i, m in enumerate(marks)]
        entries = _finish(parts)
        if len(entries) >= _MIN_ENTRIES:
            return entries

    # C: blank-line blocks
    parts = re.split(r"\n\s*\n", block)
    if len(parts) >= _MIN_ENTRIES:
        entries = _finish(parts)
        if len(entries) >= _MIN_ENTRIES:
            return entries

    # D: year-anchored accumulation — break after a line that ends an entry
    # containing a 19xx/20xx year and terminating punctuation.
    parts, current = [], []
    for line in block.splitlines():
        if not line.strip():
            continue
        current.append(line)
        joined = " ".join(current)
        if re.search(r"\b(19|20)\d{2}\b", joined) and line.rstrip().endswith("."):
            parts.append(joined)
            current = []
    if current:
        parts.append(" ".join(current))
    entries = _finish(parts)
    return entries if len(entries) >= _MIN_ENTRIES else []


# ---------------------------------------------------------------------------
# 3. Bibliography entries for a draft (with related-work fallback)
# ---------------------------------------------------------------------------

def extract_bibliography_entries(draft_id: str) -> tuple[list[str], str]:
    """Return (entries, source) for the draft: bibliography | related_work | none."""
    from research_companion.store import load_extraction, load_sections, load_text

    text = load_text(draft_id)
    if text:
        block = find_references_block(text, load_sections(draft_id))
        if block:
            entries = split_bibliography(block)
            if len(entries) >= _MIN_ENTRIES:
                return entries, "bibliography"

    # Fallback: the LLM extraction's related_work strings
    try:
        from research_companion.prompts import extraction_prompt_sha256
        ext = load_extraction(draft_id, prompt_sha=extraction_prompt_sha256())
    except Exception:  # noqa: BLE001
        ext = None
    if ext:
        rw = [str(x).strip() for x in ext.get("related_work", []) if str(x).strip()]
        if rw:
            return rw[:_MAX_ENTRIES], "related_work"

    return [], "none"


# ---------------------------------------------------------------------------
# 4. Library matching
# ---------------------------------------------------------------------------

_ENUM_PREFIX_RE = re.compile(r"^\s*(?:\[\d{1,3}\]|\(\d{1,3}\)|\d{1,3}\.)\s*")
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_ETAL_RE = re.compile(r"\bet\s+al\b", re.IGNORECASE)


def _ref_first_surname(ref: Reference) -> str | None:
    """First-author surname from a reference's raw label, normalized.

    These refs are author+year labels ("Neumann et al. 2019") with no real
    title/id. Strip leading enumeration, then take the head before "et al",
    the first comma, or the year, and normalize its first token via
    `_last_name`. Hyphenated names ("Segura-Bedmar") stay whole; org names
    yield a non-person token that simply won't equal any library surname.
    """
    raw = _ENUM_PREFIX_RE.sub("", ref.raw or "").strip()
    if not raw:
        return None
    cut = len(raw)
    for m in (_YEAR_RE.search(raw), _ETAL_RE.search(raw)):
        if m:
            cut = min(cut, m.start())
    comma = raw.find(",")
    if comma != -1:
        cut = min(cut, comma)
    head = raw[:cut].split()
    if not head:
        return None
    return _last_name(head[0]) or None


def match_reference_to_library(
    ref: Reference, papers: list[PaperMetadata],
) -> tuple[str, str] | None:
    """Match a parsed reference against library papers.

    Order matters: parsed ids are authoritative; then CONTAINMENT of the clean
    library title in the raw entry (parse leaves authors/venue in ref.title, so
    naive similarity against clean titles rarely fires); similarity last.
    """
    if ref.arxiv_id:
        want = make_arxiv_id(ref.arxiv_id).lower()
        for p in papers:
            if p.paper_id.lower() == want:
                return p.paper_id, "arxiv_id"
    if ref.doi:
        want = f"doi:{ref.doi}".lower()
        for p in papers:
            if p.paper_id.lower() == want:
                return p.paper_id, "doi"

    norm_raw = normalize_title(ref.raw)
    for p in papers:
        norm_lib = normalize_title(p.title)
        if len(norm_lib) >= _MIN_CONTAINMENT_TITLE and norm_lib in norm_raw:
            return p.paper_id, "title_containment"

    for p in papers:
        if title_similarity(ref.title, p.title) >= _TITLE_SIM_THRESHOLD:
            return p.paper_id, "title_similarity"

    # Author+year: conservative last resort for bare "Surname et al. YEAR"
    # labels. Requires BOTH exact year equality AND normalized first-author
    # surname equality; never loosen.
    if ref.year is not None:
        ref_sn = _ref_first_surname(ref)
        if ref_sn:
            for p in papers:
                if p.year == ref.year and p.authors:
                    lib_sn = _last_name(p.authors[0])
                    if lib_sn and lib_sn == ref_sn:
                        return p.paper_id, "author_year"

    return None


# ---------------------------------------------------------------------------
# 5. Persistence
# ---------------------------------------------------------------------------

def coverage_path() -> Path:
    return papergraph_dir() / "citations_coverage.json"


def load_coverage() -> dict | None:
    p = coverage_path()
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def save_coverage(payload: dict) -> Path:
    p = coverage_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)
    return p


def empty_coverage(draft_paper_id: str | None) -> dict:
    return {
        "version": 1,
        "draft_paper_id": draft_paper_id,
        "draft_text_sha256": None,
        "source": "none",
        "computed_at": _now(),
        "resolved_at": None,
        "references": [],
        "counts": {"total": 0, "in_library": 0, "available": 0,
                   "unchecked": 0, "unresolved": 0},
    }


def _recount(payload: dict) -> None:
    counts = {"total": 0, "in_library": 0, "available": 0,
              "unchecked": 0, "unresolved": 0}
    for r in payload["references"]:
        counts["total"] += 1
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    payload["counts"] = counts


# ---------------------------------------------------------------------------
# 6. compute_coverage (offline)
# ---------------------------------------------------------------------------

def compute_coverage(draft_id: str) -> dict:
    """Parse + library-match the draft's bibliography; persist and return.

    Never hits the network. Resolution results from a previous run are carried
    over by exact raw-string match so paid lookups are never discarded.
    A draft with no text yet returns source:"none" WITHOUT caching.
    """
    from research_companion.store import list_papers, load_text

    text = load_text(draft_id)
    entries, source = extract_bibliography_entries(draft_id)
    if source == "none":
        return empty_coverage(draft_id)

    prev = load_coverage()
    prev_by_raw: dict[str, dict] = {}
    if prev and prev.get("draft_paper_id") == draft_id:
        prev_by_raw = {r["raw"]: r for r in prev.get("references", [])
                       if isinstance(r, dict) and "raw" in r}

    papers = list_papers()
    refs_out = []
    for idx, raw in enumerate(entries):
        ref = parse_reference_string(raw)
        rec = {
            "index": idx,
            "raw": raw,
            "title": ref.title,
            "year": ref.year,
            "doi": ref.doi,
            "arxiv_id": ref.arxiv_id,
            "status": "unchecked",
            "matched_paper_id": None,
            "match_kind": None,
            "resolved": None,
            "add_target": None,
        }
        m = match_reference_to_library(ref, papers)
        if m:
            rec["status"] = "in_library"
            rec["matched_paper_id"], rec["match_kind"] = m
        elif ref.arxiv_id or ref.doi:
            rec["status"] = "available"
            rec["add_target"] = ref.arxiv_id or ref.doi
        else:
            # Carry over a previous network resolution for this exact entry
            old = prev_by_raw.get(raw)
            if old and old.get("resolved"):
                rec["resolved"] = old["resolved"]
                rec["add_target"] = old.get("add_target")
                rec["status"] = "available" if rec["add_target"] else "unresolved"
            elif old and old.get("status") == "unresolved":
                rec["status"] = "unresolved"
        refs_out.append(rec)

    payload = {
        "version": 1,
        "draft_paper_id": draft_id,
        "draft_text_sha256": hashlib.sha256((text or "").encode()).hexdigest(),
        "source": source,
        "computed_at": _now(),
        "resolved_at": (prev or {}).get("resolved_at")
        if prev and prev.get("draft_paper_id") == draft_id else None,
        "references": refs_out,
    }
    _recount(payload)
    save_coverage(payload)
    return payload


def is_stale(payload: dict | None, draft_id: str | None) -> bool:
    """True when the cached coverage no longer describes the current draft text."""
    if payload is None or draft_id is None:
        return True
    if payload.get("draft_paper_id") != draft_id:
        return True
    from research_companion.store import load_text
    text = load_text(draft_id) or ""
    return payload.get("draft_text_sha256") != hashlib.sha256(text.encode()).hexdigest()


# ---------------------------------------------------------------------------
# 7. Network resolution (explicit job only)
# ---------------------------------------------------------------------------

def resolve_reference(
    ref: Reference,
    *,
    crossref_search: Callable = _crossref_search,
    openalex_search: Callable = _openalex_search,
    parse_cr: Callable = parse_crossref_item,
    parse_oa: Callable = parse_openalex_item,
) -> dict | None:
    """Resolve a title-only reference to an authoritative record — CONSERVATIVE.

    A false positive downloads the wrong paper, so acceptance requires either
    the candidate title contained in the raw entry with the year within ±1,
    or high title similarity with exact year agreement.
    """
    def _accept(cand: dict) -> bool:
        title = cand.get("title") or ""
        norm_cand = normalize_title(title)
        if len(norm_cand) >= _MIN_CONTAINMENT_TITLE and norm_cand in normalize_title(ref.raw):
            cy, ry = cand.get("year"), ref.year
            return cy is None or ry is None or abs(cy - ry) <= 1
        if title_similarity(title, ref.title) >= _RESOLVE_SIM_THRESHOLD:
            return cand.get("year") is not None and cand.get("year") == ref.year
        return False

    try:
        for item in crossref_search(ref.raw):
            cand = parse_cr(item)
            if _accept(cand):
                return cand
    except Exception:  # noqa: BLE001 — network errors must not kill the job
        pass
    try:
        for item in openalex_search(ref.raw):
            cand = parse_oa(item)
            if _accept(cand):
                return cand
    except Exception:  # noqa: BLE001
        pass
    return None


def resolve_missing(payload: dict, *, resolver: Callable = resolve_reference) -> dict:
    """Resolve every 'unchecked' entry; flip to available/unresolved; persist."""
    for rec in payload["references"]:
        if rec["status"] != "unchecked":
            continue
        ref = Reference(
            title=rec.get("title") or rec["raw"], authors=[],
            year=rec.get("year"), doi=rec.get("doi"),
            arxiv_id=rec.get("arxiv_id"), url=None, raw=rec["raw"])
        record = resolver(ref)
        if record and (record.get("arxiv_id") or record.get("doi")):
            rec["resolved"] = {
                "title": record.get("title"), "year": record.get("year"),
                "doi": record.get("doi"), "arxiv_id": record.get("arxiv_id"),
            }
            rec["add_target"] = record.get("arxiv_id") or record.get("doi")
            rec["status"] = "available"
        else:
            rec["status"] = "unresolved"
    payload["resolved_at"] = _now()
    _recount(payload)
    save_coverage(payload)
    return payload
