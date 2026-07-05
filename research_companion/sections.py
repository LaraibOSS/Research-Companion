"""Section-tree extraction for research papers.

Splits a paper's plain text (produced by pypdf) into a hierarchical section tree
using conservative heuristics, with an optional LLM fallback for poorly-structured text.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass

from research_companion import store
from research_companion.extract import get_paper_text
from research_companion.rebuttal.verify import _norm


@dataclass
class Section:
    section_id: str      # "s1", "s2", "s2.1" — stable positional ids in document order
    title: str
    level: int           # 1 or 2 only
    parent: str | None   # "s2" for "s2.1"; None for level-1
    char_start: int      # offset into the text this tree was built from
    char_end: int        # exclusive; sections tile the text (no gaps/overlaps at level 1)


# ---------------------------------------------------------------------------
# Canonical section names (case-insensitive, exact whole-line match)
# ---------------------------------------------------------------------------
_CANONICAL_NAMES: frozenset[str] = frozenset({
    "abstract",
    "introduction",
    "related work",
    "background",
    "method",
    "methods",
    "methodology",
    "approach",
    "experiment",
    "experiments",
    "experimental setup",
    "results",
    "evaluation",
    "analysis",
    "discussion",
    "limitations",
    "conclusion",
    "conclusions",
    "future work",
    "references",
    "bibliography",
    "acknowledgments",
    "acknowledgements",
    "appendix",
})

# Numbered heading pattern: optional leading whitespace, then 1+ digits,
# optionally ".digit+" for sub-section, optional trailing ".", space, then
# text starting with uppercase letter (1-80 chars total for the title part).
_NUMBERED_RE = re.compile(
    r"^\s*(\d+)(\.\d+)?\.?\s+([A-Z]\S.{0,78})$"
)


def _is_allcaps_heading(line: str) -> bool:
    """Return True if line qualifies as an ALL-CAPS section heading."""
    stripped = line.strip()
    if len(stripped) < 3 or len(stripped) >= 60:
        return False
    if stripped.endswith("."):
        return False
    # Must contain at least one letter
    if not any(c.isalpha() for c in stripped):
        return False
    # All letters must be uppercase
    return all(c.isupper() for c in stripped if c.isalpha())


def _find_heading_candidates(text: str) -> list[tuple[int, str, int, str | None]]:
    """Scan text line-by-line and collect heading candidates.

    Returns list of (char_offset, title, level, parent_hint) tuples.
    parent_hint is the major section number for level-2 headings (e.g. "2" for "2.1").
    """
    candidates: list[tuple[int, str, int, str | None]] = []
    pos = 0
    for line in text.split("\n"):
        line_start = pos
        pos += len(line) + 1  # +1 for the '\n'

        stripped = line.strip()
        if not stripped:
            continue

        # Priority 1: Numbered headings
        m = _NUMBERED_RE.match(line)
        if m:
            major = m.group(1)
            minor = m.group(2)  # ".X" or None
            title_text = m.group(3).strip()

            # Reject if it looks like a sentence (ends with "." AND > 60 chars)
            if title_text.endswith(".") and len(title_text) > 60:
                pass  # fall through to next checks
            else:
                level = 2 if minor else 1
                parent_hint = major if minor else None
                candidates.append((line_start, title_text, level, parent_hint))
                continue

        # Priority 2: Canonical names (case-insensitive, < 60 chars)
        if stripped.lower() in _CANONICAL_NAMES and len(stripped) < 60:
            candidates.append((line_start, stripped, 1, None))
            continue

        # Priority 3: ALL-CAPS headings
        if _is_allcaps_heading(stripped):
            candidates.append((line_start, stripped, 1, None))
            continue

    return candidates


def _fallback_section(text: str) -> list[Section]:
    """Return the single-section fallback."""
    return [Section("s1", "Full Text", 1, None, 0, len(text))]


def _get_line_at(text: str, char_offset: int) -> str:
    """Return the full line of text that starts at char_offset."""
    end = text.find("\n", char_offset)
    if end == -1:
        return text[char_offset:]
    return text[char_offset:end]


def build_section_tree(text: str) -> list[Section]:
    """Build a list of Section objects from plain text using heuristics.

    Heuristics (in priority order):
    1. Numbered headings (level 1 or 2)
    2. Canonical names (level 1)
    3. ALL-CAPS short lines (level 1)

    GUARANTEE: always returns >= 1 section.
    """
    raw_candidates = _find_heading_candidates(text)

    if not raw_candidates:
        return _fallback_section(text)

    # Sort by char offset
    raw_candidates.sort(key=lambda c: c[0])

    # Filter out candidates whose body would be < 40 chars (except the last).
    # Body = text from end of heading line to start of next heading.
    filtered: list[tuple[int, str, int, str | None]] = []
    for i, cand in enumerate(raw_candidates):
        is_last = (i == len(raw_candidates) - 1)
        if is_last:
            filtered.append(cand)
        else:
            # Find end of heading line
            heading_line_end = text.find("\n", cand[0])
            if heading_line_end == -1:
                heading_line_end = len(text)
            body_start = heading_line_end + 1
            next_start = raw_candidates[i + 1][0]
            body_len = next_start - body_start
            if body_len >= 40:
                filtered.append(cand)

    candidates = filtered

    # Cap at 40 level-1 sections — treat as unstructured if exceeded
    level1_count = sum(1 for c in candidates if c[2] == 1)
    if level1_count > 40:
        return _fallback_section(text)

    if not candidates:
        return _fallback_section(text)

    # Build Section objects with tiled char ranges.
    sections: list[Section] = []
    l1_idx = 0
    l2_counters: dict[str, int] = {}   # parent_sid -> l2 count
    current_l1_sid: str | None = None
    numbered_major_to_sid: dict[str, str] = {}  # "2" -> "s2" for numbered l1 headings

    for i, (char_start, title, level, parent_hint) in enumerate(candidates):
        char_end = candidates[i + 1][0] if i + 1 < len(candidates) else len(text)

        if level == 1:
            l1_idx += 1
            sid = f"s{l1_idx}"
            current_l1_sid = sid

            # Record major number -> sid for numbered level-1 headings
            line_text = _get_line_at(text, char_start)
            nm = _NUMBERED_RE.match(line_text)
            if nm and not nm.group(2):  # level-1: has major but no sub-number
                numbered_major_to_sid[nm.group(1)] = sid

            sections.append(Section(
                section_id=sid,
                title=title,
                level=1,
                parent=None,
                char_start=char_start,
                char_end=char_end,
            ))

        else:  # level == 2
            # Determine parent
            parent_sid: str | None = None
            if parent_hint is not None and parent_hint in numbered_major_to_sid:
                parent_sid = numbered_major_to_sid[parent_hint]
            elif current_l1_sid is not None:
                parent_sid = current_l1_sid

            parent_key = parent_sid or "_none"
            l2_counters[parent_key] = l2_counters.get(parent_key, 0) + 1
            l2_num = l2_counters[parent_key]
            sid = f"{parent_sid}.{l2_num}" if parent_sid else f"s0.{l2_num}"

            sections.append(Section(
                section_id=sid,
                title=title,
                level=2,
                parent=parent_sid,
                char_start=char_start,
                char_end=char_end,
            ))

    if not sections:
        return _fallback_section(text)

    # Fix #1: absorb preamble text (before the first heading) into the first section
    # so that level-1 sections tile the entire text from offset 0.
    if sections[0].char_start > 0:
        first = sections[0]
        sections[0] = Section(
            section_id=first.section_id,
            title=first.title,
            level=first.level,
            parent=first.parent,
            char_start=0,
            char_end=first.char_end,
        )

    return sections


# ---------------------------------------------------------------------------
# Boilerplate detection
# ---------------------------------------------------------------------------

_BOILERPLATE_RE = re.compile(
    r"^(references|bibliography|acknowledg\w*|appendix(\s+.*)?)$",
    re.IGNORECASE,
)


def is_boilerplate(title: str) -> bool:
    """Return True if a section title is boilerplate.

    Covers: references, bibliography, acknowledgments/acknowledgements,
    appendix (including "Appendix A", "Appendix B: ..." prefixes).
    """
    stripped = title.strip()
    return bool(_BOILERPLATE_RE.match(stripped))


# ---------------------------------------------------------------------------
# LLM refinement
# ---------------------------------------------------------------------------

def refine_sections_llm(text: str, sections: list[Section], llm: Callable[[str], str]) -> list[Section]:
    """Refine sections using an LLM callable when heuristics found < 3 sections.

    The LLM receives the first ~6000 chars and returns JSON {"headings": [...]}.
    Each proposed heading is located in the FULL text by exact match, then by
    whitespace-normalized match. Unmatched headings are silently dropped.
    If < 2 headings match, returns the original sections unchanged.
    """
    snippet = text[:6000]
    prompt = (
        "The following is the beginning of an academic paper. "
        "List all section headings you can identify as a JSON object with a single key "
        "\"headings\" containing an array of verbatim heading strings exactly as they appear "
        "in the text. Do not invent headings; only include text that appears literally.\n\n"
        f"TEXT:\n{snippet}\n\nJSON:"
    )

    try:
        raw = llm(prompt)
    except Exception:
        return sections

    # Find the first '{' to parse JSON defensively
    brace_idx = raw.find("{")
    if brace_idx == -1:
        return sections

    try:
        data = json.loads(raw[brace_idx:])
    except (json.JSONDecodeError, ValueError):
        return sections

    proposed_headings = data.get("headings")
    if not isinstance(proposed_headings, list):
        return sections

    # Locate each heading in the full text
    matched_offsets: list[tuple[int, str]] = []  # (char_offset, heading_text)
    norm_text = _norm(text)

    for heading in proposed_headings:
        if not isinstance(heading, str) or not heading.strip():
            continue
        # Try exact match first
        idx = text.find(heading)
        if idx != -1:
            matched_offsets.append((idx, heading))
            continue
        # Try whitespace-normalized match
        norm_heading = _norm(heading)
        norm_idx = norm_text.find(norm_heading)
        if norm_idx != -1:
            orig_idx = _find_in_original(text, norm_heading, norm_idx)
            if orig_idx != -1:
                matched_offsets.append((orig_idx, heading))

    if len(matched_offsets) < 2:
        return sections

    # Sort by position
    matched_offsets.sort(key=lambda x: x[0])

    # Build sections with tiling rules (all level 1)
    new_sections: list[Section] = []
    for i, (char_start, heading) in enumerate(matched_offsets):
        char_end = matched_offsets[i + 1][0] if i + 1 < len(matched_offsets) else len(text)
        sid = f"s{i + 1}"
        new_sections.append(Section(
            section_id=sid,
            title=heading,
            level=1,
            parent=None,
            char_start=char_start,
            char_end=char_end,
        ))

    return new_sections if new_sections else sections


def _find_in_original(text: str, norm_target: str, approx_norm_idx: int) -> int:
    """Find the start position in `text` corresponding to a normalized match.

    approx_norm_idx is an index into the *normalized* version of text.  We build
    a norm->original index mapping so the search window is anchored correctly in
    the original text, then scan a bounded window for the span whose normalized
    form equals norm_target.

    Headings are assumed to be < 100 characters in the original text.
    """
    # Build a mapping: norm_pos -> original_pos for each character kept after
    # whitespace normalization (i.e. every non-whitespace char + first space of
    # each run).  This lets us translate approx_norm_idx back to original space.
    norm_to_orig: list[int] = []  # norm_to_orig[k] = original index of norm[k]
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c in (' ', '\t', '\n', '\r'):
            # Start of a whitespace run -> emit one space in the normalized text
            norm_to_orig.append(i)
            i += 1
            while i < n and text[i] in (' ', '\t', '\n', '\r'):
                i += 1
        else:
            norm_to_orig.append(i)
            i += 1
    # norm_to_orig now has one entry per character of _norm(text).
    # Leading/trailing spaces are stripped by _norm, so the mapping may have a
    # leading space we need to account for.  Instead of reproducing _norm exactly,
    # we look up the original index for approx_norm_idx with a small guard.
    orig_anchor = norm_to_orig[approx_norm_idx] if approx_norm_idx < len(norm_to_orig) else len(text)

    # Search window: scan forward from orig_anchor (which maps directly to the
    # first character of the heading in the original text).  We allow up to
    # len(norm_target) + 30 extra characters to accommodate trailing whitespace
    # in the span.  We do NOT scan before orig_anchor — any span that starts
    # before orig_anchor would include leading whitespace and still match, but
    # would give an incorrect (too-early) position.
    search_end = min(n, orig_anchor + len(norm_target) + 30)

    for start in range(orig_anchor, search_end):
        for end in range(start + len(norm_target), min(start + len(norm_target) + 100, n + 1)):
            span = text[start:end]
            if _norm(span) == norm_target:
                return start

    # Fallback: scan a small window before orig_anchor in case the anchor is
    # slightly over-shot (e.g. leading whitespace is counted differently).
    search_start = max(0, orig_anchor - 10)
    for start in range(search_start, orig_anchor):
        for end in range(start + len(norm_target), min(start + len(norm_target) + 100, n + 1)):
            span = text[start:end]
            if _norm(span) == norm_target:
                return start

    return -1


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def section_text(text: str, s: Section) -> str:
    """Return the text slice for a section."""
    return text[s.char_start:s.char_end]


def group_extraction_by_section(extraction: dict, sections: list[Section]) -> dict[str, dict]:
    """Group extraction entities by section.

    Each key in extraction that is a list of dicts is grouped by the "section" key
    of each entity. "related_work" entries are excluded entirely.
    Entities with missing/None/unknown section ids go to "_unassigned".
    """
    valid_ids = {s.section_id for s in sections}

    # Collect keys to group (lists of dicts, excluding related_work)
    keys_to_group = [
        k for k, v in extraction.items()
        if k != "related_work" and isinstance(v, list)
        and all(isinstance(item, dict) for item in v)
    ]

    # Initialize result with all valid section ids + _unassigned
    result: dict[str, dict] = {sid: {k: [] for k in keys_to_group} for sid in valid_ids}
    result["_unassigned"] = {k: [] for k in keys_to_group}

    for key in keys_to_group:
        for entity in extraction[key]:
            sec_id = entity.get("section")
            if sec_id and sec_id in valid_ids:
                result[sec_id][key].append(entity)
            else:
                result["_unassigned"][key].append(entity)

    return result


# ---------------------------------------------------------------------------
# build_and_save_sections: main entry point
# ---------------------------------------------------------------------------

def build_and_save_sections(
    paper_id: str,
    *,
    llm: Callable[[str], str] | None = None,
    force: bool = False,
) -> list[Section]:
    """Build (or load cached) section tree for a paper and persist it.

    Raises ValueError if the paper_id is unknown (no metadata).
    """
    meta = store.PaperMetadata.load(paper_id)
    if meta is None:
        raise ValueError(f"Unknown paper_id: {paper_id!r}")

    text = get_paper_text(meta)
    text_sha = hashlib.sha256(text.encode()).hexdigest()

    if not force:
        cached = store.load_sections(paper_id, text_sha=text_sha)
        if cached is not None:
            return [Section(**s) for s in cached.get("sections", [])]

    # Build section tree
    raw_sections = build_section_tree(text)
    method = "heuristic"

    if len(raw_sections) < 3 and llm is not None:
        refined = refine_sections_llm(text, raw_sections, llm)
        if refined != raw_sections:
            raw_sections = refined
            method = "heuristic+llm"
        else:
            raw_sections = refined  # same object, method stays "heuristic"

    # Persist
    payload = {
        "version": 1,
        "text_sha256": text_sha,
        "method": method,
        "sections": [asdict(s) for s in raw_sections],
    }
    store.save_sections(paper_id, payload)

    return raw_sections
