"""Draft scaffolding -- turn one chosen Research Direction into a draft
(Brainstorm slice 2d: "Draft this direction").

"Generate directions (2b) -> check novelty (2c) -> act on one (2d)": click
"Draft this direction" on a direction card and get a real, editable draft
outline created as the active draft, flowing straight into the existing
draft pipeline (alignment, opportunities, coverage) -- same handling as any
freshly-uploaded draft mid-ingest (sections+text, no extraction yet).

Two clearly separated stages so the mutation is atomic-on-success:
    1. generate_outline (pure-ish, one LLM call, never raises) -- turns a
       direction into a research-paper section outline tailored to it. A
       degenerate/empty outline (LLM/parse failure, or a well-formed but
       empty "sections" list) is treated as a failure -- we do not create
       an empty draft.
    2. scaffold_sections_payload (pure) -- builds the synthetic draft body
       + the tiling sections.json from a successful outline.
    3. create_draft_from_direction (mutating, called ONLY after a
       successful outline) -- mints a deterministic paper_id, writes
       metadata+text+sections directly (bypassing the PDF pipeline --
       store.save_text/save_sections have no PDF dependency). Setting the
       draft pointer + journey/events is the caller's job (lab_api.py's
       existing _apply_draft), not this module's, so that wiring is never
       duplicated.

Honest: the outline is grounded ONLY in the direction's own rationale and
its real grounding papers (citations of kind "paper"); the prompt must not
invent papers/citations not supplied. `parse_source="scaffold"` marks the
draft as a clearly-labeled scaffold, not a real paper.

See docs/superpowers/specs/2026-08-10-brainstorm-scaffold-design.md.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from research_companion import store
from research_companion.extract import _strip_code_fences
from research_companion.prompts import format_scaffold_outline_prompt
from research_companion.rebuttal.verify import _norm

_MAX_SECTIONS = 12


# ---------------------------------------------------------------------------
# _grounding_block
# ---------------------------------------------------------------------------

def _grounding_block(citations: list) -> str:
    """One "- {title} ({year})." line per real grounding paper citation
    (kind == "paper" only -- concept/gap citations aren't papers to
    reference by title). "" when there are none. Never raises."""
    lines = []
    for c in citations or []:
        if not isinstance(c, dict) or c.get("kind") != "paper":
            continue
        title = str(c.get("title") or "").strip()
        if not title:
            continue
        year = c.get("year")
        year_str = year if year is not None else "n.d."
        lines.append(f"- {title} ({year_str}).")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# _normalize_outline_sections
# ---------------------------------------------------------------------------

def _normalize_outline_sections(raw_sections: list) -> list[dict]:
    """Pure post-processing of the LLM's raw "sections" list: caps at
    _MAX_SECTIONS, clamps level to {1,2}, drops empty titles, and promotes a
    level-2 section with no preceding level-1 to level-1 (mirrors
    sections.py's tiling invariant -- a level-2 section always nests under
    a real level-1 parent). Never raises. Returns
    [{"title","level","description"}, ...]."""
    out: list[dict] = []
    seen_level1 = False
    for item in raw_sections or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        level = 2 if item.get("level") in (2, "2") else 1
        if level == 2 and not seen_level1:
            level = 1
        if level == 1:
            seen_level1 = True
        description = str(item.get("description") or "").strip()
        out.append({"title": title, "level": level, "description": description})
        if len(out) >= _MAX_SECTIONS:
            break
    return out


# ---------------------------------------------------------------------------
# generate_outline
# ---------------------------------------------------------------------------

def generate_outline(direction: dict, *, llm: Callable[[str], str] | None = None) -> dict:
    """Turn one Research Direction (2b's {title, rationale, direction_type,
    citations}) into a research-paper section outline via one
    SCAFFOLD_OUTLINE_PROMPT call. Never raises.

    A degenerate/empty outline (LLM call/parse failure, or a well-formed
    but empty "sections" list) is treated as a failure -- callers must not
    create an empty draft -- so BOTH cases set `llm_error`.

    Returns {"sections": [{"title","level","description"}, ...],
    "llm_error": str|None}.
    """
    d = direction if isinstance(direction, dict) else {}
    title = str(d.get("title") or "").strip()
    rationale = str(d.get("rationale") or "").strip()
    direction_type = str(d.get("direction_type") or "").strip()
    citations = d.get("citations") if isinstance(d.get("citations"), list) else []

    prompt = format_scaffold_outline_prompt(
        title=title, rationale=rationale, direction_type=direction_type,
        grounding_block=_grounding_block(citations),
    )

    try:
        raw = llm(prompt)
        parsed = json.loads(_strip_code_fences(raw)) if isinstance(raw, str) else raw
        if not isinstance(parsed, dict):
            raise ValueError("LLM returned non-object JSON")
        raw_sections = parsed.get("sections")
        if not isinstance(raw_sections, list):
            raise ValueError("LLM response missing a 'sections' list")
    except Exception as exc:
        return {"sections": [], "llm_error": str(exc) or exc.__class__.__name__}

    sections = _normalize_outline_sections(raw_sections)
    if not sections:
        return {"sections": [], "llm_error": "The model returned an empty outline."}

    return {"sections": sections, "llm_error": None}


# ---------------------------------------------------------------------------
# scaffold_sections_payload
# ---------------------------------------------------------------------------

def scaffold_sections_payload(outline: dict, *, title: str) -> tuple[str, dict]:
    """Build the synthetic draft body + the tiling sections.json from a
    successful `generate_outline` result. Pure; never raises.

    For each outline section: a markdown block "# {title}\\n\\n{description}
    \\n\\n" (level 1) or "## {title}\\n\\n{description}\\n\\n" (level 2),
    concatenated in order into `text`. char_start/char_end tile `text`
    exactly (no gaps/overlaps), section_id follows sections.py's convention
    (s1, s2, s2.1, ...), and a level-2's `parent` is the nearest preceding
    level-1's section_id (or None -> "s0.N" if somehow there is none, the
    same fallback sections.build_section_tree uses).

    `title` (the direction's own title, i.e. what create_draft_from_direction
    also uses for the paper's metadata.title) is accepted for signature
    symmetry with create_draft_from_direction but is NOT written into the
    body -- every outline section already carries its own tailored heading,
    so a redundant top-level "# {title}" would just duplicate what the
    Introduction section already says (mirrors directions.py's
    _collect_grounding, whose `topic` parameter is accepted for the same
    symmetry reason without being grounding content itself).

    Returns (text, {"version": 1, "text_sha256": ..., "method": "scaffold",
    "sections": [{"section_id","title","level","parent","char_start",
    "char_end"}, ...]}).
    """
    _ = title  # accepted for signature symmetry only; see docstring above.
    sections = (outline or {}).get("sections") or []

    blocks: list[str] = []
    records: list[dict] = []
    l1_idx = 0
    current_l1_sid: str | None = None
    l2_counters: dict[str, int] = {}

    for sec in sections:
        if not isinstance(sec, dict):
            continue
        sec_title = str(sec.get("title") or "").strip() or "Untitled"
        description = str(sec.get("description") or "").strip()
        level = 2 if sec.get("level") == 2 else 1

        if level == 1:
            l1_idx += 1
            sid = f"s{l1_idx}"
            current_l1_sid = sid
            parent = None
            heading = f"# {sec_title}\n\n{description}\n\n"
        else:
            parent = current_l1_sid
            parent_key = parent or "_none"
            l2_counters[parent_key] = l2_counters.get(parent_key, 0) + 1
            sid = f"{parent}.{l2_counters[parent_key]}" if parent else f"s0.{l2_counters[parent_key]}"
            heading = f"## {sec_title}\n\n{description}\n\n"

        blocks.append(heading)
        records.append({"section_id": sid, "title": sec_title, "level": level, "parent": parent})

    text = "".join(blocks)

    pos = 0
    sections_payload: list[dict] = []
    for block, rec in zip(blocks, records, strict=True):
        start = pos
        end = pos + len(block)
        pos = end
        sections_payload.append({**rec, "char_start": start, "char_end": end})

    payload = {
        "version": 1,
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "method": "scaffold",
        "sections": sections_payload,
    }
    return text, payload


# ---------------------------------------------------------------------------
# create_draft_from_direction
# ---------------------------------------------------------------------------

def _scaffold_paper_id(title: str, rationale: str) -> str:
    """Deterministic paper_id for a scaffolded draft -- a content hash of
    the direction's (title, rationale), so re-scaffolding the SAME
    direction overwrites the same draft paper rather than piling up
    duplicates (mirrors directions._assemble_directions's direction_id
    hashing convention: the same rebuttal.verify._norm helper, sha256,
    truncated to 12 hex chars)."""
    key = f"{_norm(title)}|{_norm(rationale)}"
    return "scaffold:" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


def create_draft_from_direction(direction: dict, outline: dict, *, store_mod: Any = store) -> str:
    """Materialize a successful outline as a draft paper. MUTATING -- call
    ONLY after `generate_outline` succeeds (llm_error is None and sections
    is non-empty); the caller (lab_api.py) is responsible for that
    atomic-on-success check.

    Mints a deterministic `paper_id` (see `_scaffold_paper_id`), builds a
    `PaperMetadata` record (title = the direction's title, authors=[],
    year=None, abstract = the direction's rationale, parse_source=
    "scaffold" -- a clearly-labeled scaffold, not a real paper --
    full_text_available=True), `.save()`s it, then writes the synthetic
    body (`store_mod.save_text`) and the tiling sections
    (`store_mod.save_sections`) from `scaffold_sections_payload`.

    Does NOT set the draft pointer, record a journey version, or fire
    events -- the caller reuses the existing `_apply_draft` for that so the
    wiring is never duplicated. `store_mod` is the injectable seam for
    tests (defaults to the real `research_companion.store`).

    Returns the minted `paper_id`.
    """
    d = direction if isinstance(direction, dict) else {}
    title = str(d.get("title") or "").strip() or "Untitled direction"
    rationale = str(d.get("rationale") or "").strip()

    paper_id = _scaffold_paper_id(title, rationale)
    text, sections_payload = scaffold_sections_payload(outline, title=title)

    meta = store_mod.PaperMetadata(
        paper_id=paper_id,
        title=title,
        authors=[],
        year=None,
        abstract=rationale,
        source_url="",
        added_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        parse_source="scaffold",
        full_text_available=True,
    )
    meta.save()
    store_mod.save_text(paper_id, text)
    store_mod.save_sections(paper_id, sections_payload)
    return paper_id
