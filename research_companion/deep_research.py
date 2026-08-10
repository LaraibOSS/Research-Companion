"""Deep-Research Report generator (Phase 2, slice 2e-1).

"Topic -> LLM-generated investigation sub-questions (STORM-style
perspectives, grounded in the library) -> per-question cited synthesis
(reusing qa.answer) -> an assembled, cited report" -- turns the ideation
arc's endpoint into a deliverable: a structured, cited literature-review
report over the researcher's own library.

Pipeline (mirrors gaps.py's synthesize_gaps / scaffold.py's two-stage
shape, split across this module and the caller (lab_api.py) so per-question
job progress can be reported between qa.answer calls):
    1. _report_grounding_block (pure)     -- library papers + underexplored
                                              concepts grounding block
    2. generate_questions (one LLM call)  -- 4-max_questions distinct
                                              investigation sub-questions
    3. build_report (pure orchestration)  -- per question, call the
                                              injectable answer_fn (the
                                              caller passes a qa.answer
                                              closure) and assemble the
                                              cited report

Honest: questions are grounded ONLY in the library's own concepts/papers
(the prompt must not invent papers/concepts not supplied); every answer +
its citations come straight from qa.answer -- real, quote-verified library
chunks. Nothing is fabricated. Scope is explicitly "over your library", not
the open web.

See docs/superpowers/specs/2026-08-10-deep-research-report-design.md.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

# ---------------------------------------------------------------------------
# _report_grounding_block
# ---------------------------------------------------------------------------

def _report_grounding_block(library_papers: list, graph: Any = None) -> str:
    """Build the LLM grounding block for question generation: one
    "- Paper: {title} ({year})." line per real library paper, plus one
    "- Underexplored concept: {name} (...)." line per underexplored concept
    (reusing directions._underexplored_concepts -- the only existing
    per-concept frequency signal). Pure; never raises. "" when there is
    nothing to ground on.
    """
    from research_companion.directions import _underexplored_concepts

    lines: list[str] = []
    for p in library_papers or []:
        if not isinstance(p, dict):
            continue
        title = str(p.get("title") or "").strip()
        if not title:
            continue
        year = p.get("year")
        year_str = year if year is not None else "n.d."
        lines.append(f"- Paper: {title} ({year_str}).")

    for c in _underexplored_concepts(graph):
        plural = "s" if c["paper_count"] != 1 else ""
        lines.append(
            f"- Underexplored concept: {c['name']} "
            f"(appears in only {c['paper_count']} paper{plural} in this library)."
        )

    return "\n".join(lines)
