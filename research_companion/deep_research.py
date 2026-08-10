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


# ---------------------------------------------------------------------------
# _normalize_questions
# ---------------------------------------------------------------------------

def _normalize_questions(raw_questions: list, *, max_questions: int) -> list[str]:
    """Pure post-processing of the LLM's raw "questions" list: drops
    non-string/empty items, dedupes case-insensitively (first occurrence
    wins), caps at max_questions. Never raises."""
    out: list[str] = []
    seen: set[str] = set()
    for item in raw_questions or []:
        if not isinstance(item, str):
            continue
        q = item.strip()
        if not q:
            continue
        key = q.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(q)
        if len(out) >= max_questions:
            break
    return out


# ---------------------------------------------------------------------------
# _normalize_plan_questions (Editable Research Plan, 2e-4)
# ---------------------------------------------------------------------------

def _normalize_plan_questions(raw_questions: list, *, max_questions: int = 12) -> list[str]:
    """Pure post-processing for the editable plan: trims, drops non-string/
    empty items, dedupes case-insensitively (first occurrence wins --
    mirrors _normalize_questions exactly), caps at max_questions (default
    12 -- a sane ceiling on how many questions a report will ever answer,
    whether LLM-generated or user-edited/added). Never raises. Reused by
    the plan endpoint (POST /api/report/plan, on freshly generated
    questions) and by the extended refresh (POST /api/report/refresh, on
    the user's edited/reordered/added question list) so both accept
    exactly the same normalization.
    """
    if not isinstance(raw_questions, list):
        return []
    return _normalize_questions(raw_questions, max_questions=max_questions)


# ---------------------------------------------------------------------------
# generate_questions
# ---------------------------------------------------------------------------

def generate_questions(
    topic: str,
    *,
    library_papers: list = (),
    graph: Any = None,
    llm: Callable[[str], str] | None = None,
    max_questions: int = 6,
) -> dict:
    """Turn a topic + the library's own concepts/papers into 4-max_questions
    distinct investigation sub-questions via one REPORT_QUESTIONS_PROMPT
    call. Never raises.

    Empty topic AND empty grounding -> no LLM call, `{"questions": [],
    "llm_error": None}` (truly nothing to ground on). A degenerate/empty
    question list (LLM/parse failure, or a well-formed but empty
    "questions" list) is treated as a failure -- callers must not build an
    empty report -- so BOTH cases set `llm_error` (mirrors
    scaffold.generate_outline's empty-outline rule).

    Returns {"questions": [str, ...], "llm_error": str|None}.
    """
    from research_companion.extract import _strip_code_fences
    from research_companion.prompts import format_report_questions_prompt

    topic_str = str(topic or "").strip()
    grounding_block = _report_grounding_block(list(library_papers or []), graph)

    if not topic_str and not grounding_block:
        return {"questions": [], "llm_error": None}

    prompt = format_report_questions_prompt(
        topic=topic_str, grounding_block=grounding_block, max_questions=max_questions,
    )

    try:
        raw = llm(prompt)
        parsed = json.loads(_strip_code_fences(raw)) if isinstance(raw, str) else raw
        if not isinstance(parsed, dict):
            raise ValueError("LLM returned non-object JSON")
        raw_questions = parsed.get("questions")
        if not isinstance(raw_questions, list):
            raise ValueError("LLM response missing a 'questions' list")
    except Exception as exc:
        return {"questions": [], "llm_error": str(exc) or exc.__class__.__name__}

    questions = _normalize_questions(raw_questions, max_questions=max_questions)
    if not questions:
        return {"questions": [], "llm_error": "The model returned no investigation questions."}

    return {"questions": questions, "llm_error": None}


# ---------------------------------------------------------------------------
# build_report
# ---------------------------------------------------------------------------

def _citation_dict(source: Any) -> dict:
    """Map one QASource-like object to the report's citation dict shape.
    Duck-typed (getattr with defaults) so a plain namespace/mock works in
    tests too -- this module never imports qa.QASource directly."""
    return {
        "paper_id": getattr(source, "paper_id", "") or "",
        "paper_title": getattr(source, "paper_title", "") or "",
        "section_id": getattr(source, "section_id", "") or "",
        "char_start": getattr(source, "char_start", 0) or 0,
        "char_end": getattr(source, "char_end", 0) or 0,
        "chunk_index": getattr(source, "chunk_index", 0) or 0,
        "score": getattr(source, "score", 0.0) or 0.0,
    }


def build_report(
    topic: str,
    questions: list,
    *,
    answer_fn: Callable[[str], Any],
    generated_shas: dict,
) -> dict:
    """Pure orchestration: for each question, call the injectable
    `answer_fn(question) -> QAAnswer`-like object (the caller passes a
    `qa.answer` closure) and map it to a report section. A question whose
    `answer_fn` raises, or returns something with no usable answer (e.g.
    None), degrades to an empty section with an `"error"` key -- it never
    aborts the rest of the report. Never raises.

    Returns {"topic", "sections": [{"question", "answer", "citations":
    [{"paper_id","paper_title","section_id","char_start","char_end",
    "chunk_index","score"}, ...], "unverified_quotes", "error"?}, ...],
    "generated_from": generated_shas, "question_count": len(sections)}.
    """
    sections: list[dict] = []
    for q in questions or []:
        if not isinstance(q, str) or not q.strip():
            continue
        try:
            qa_answer = answer_fn(q)
            if qa_answer is None:
                raise ValueError("No answer was returned for this question.")
            sections.append({
                "question": q,
                "answer": getattr(qa_answer, "answer", "") or "",
                "citations": [_citation_dict(s) for s in (getattr(qa_answer, "cited", None) or [])],
                "unverified_quotes": list(getattr(qa_answer, "unverified_quotes", None) or []),
            })
        except Exception as exc:
            sections.append({
                "question": q,
                "answer": "",
                "citations": [],
                "unverified_quotes": [],
                "error": str(exc) or exc.__class__.__name__,
            })

    return {
        "topic": str(topic or "").strip(),
        "sections": sections,
        "generated_from": generated_shas,
        "question_count": len(sections),
    }
