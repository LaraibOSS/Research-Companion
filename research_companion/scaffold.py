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
