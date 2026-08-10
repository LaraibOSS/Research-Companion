"""Report Evidence Scoring (RCS) — Phase 2, slice 2e-2.

PaperQA2-style relevance/stance scoring of a saved deep-research report's
cited evidence chunks. A post-pass over an ALREADY-BUILT report
(deep_research.build_report stays pure and unchanged) -- for each section,
score_section makes ONE RCS_PROMPT LLM call over that section's citations'
REAL chunk text (store.load_text(paper_id)[char_start:char_end], exactly
the same chunk the reader would highlight), batched-numbered-block style
like gaps.synthesize_gaps. A citation whose chunk can't be loaded is left
unscored (never a guessed score); the LLM may only score listed refs --
invented refs are dropped. This is a MODEL JUDGMENT about chunk<->answer
relevance/stance, NOT a verified fact -- it must never be labeled
"verified" (that badge is reserved for the code-verified quote match).

Pipeline:
    1. _chunk_text (pure)      -- load one citation's real chunk text
    2. _chunks_block (pure)    -- numbered block of a section's chunks
    3. _normalize_scores (pure)-- drop invented refs, clamp/normalize
    4. score_section           -- one LLM call per section; never raises
    5. score_report             -- walk sections, attach rcs; never raises

See docs/superpowers/specs/2026-08-10-report-rcs-scoring-design.md.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from research_companion import store

_MAX_CHUNK_CHARS = 400
_VALID_STANCES = {"supports", "contradicts", "neutral"}


# ---------------------------------------------------------------------------
# _chunk_text
# ---------------------------------------------------------------------------

def _chunk_text(citation: dict, *, load_text_fn: Callable[[str], str | None]) -> str:
    """Return the citation's REAL cited chunk text:
    load_text_fn(paper_id)[char_start:char_end]. Defensive: a non-dict
    citation, a missing/non-str paper_id, load_text_fn returning None (or
    raising), non-int offsets, or reversed/negative offsets all degrade to
    "" (never raises). An out-of-range char_start beyond the text's length
    also naturally slices to "" (Python slicing is safe -- no extra bounds
    check needed there). An empty chunk means the citation is left
    unscored downstream -- never a guessed/fabricated score.
    """
    if not isinstance(citation, dict):
        return ""
    paper_id = citation.get("paper_id")
    if not paper_id or not isinstance(paper_id, str):
        return ""
    try:
        text = load_text_fn(paper_id)
    except Exception:
        return ""
    if not isinstance(text, str) or not text:
        return ""

    start = citation.get("char_start", 0)
    end = citation.get("char_end", 0)
    if not isinstance(start, int) or not isinstance(end, int) or start < 0 or end <= start:
        return ""
    return text[start:end]


# ---------------------------------------------------------------------------
# _chunks_block
# ---------------------------------------------------------------------------

def _chunks_block(citations: list, chunk_texts: list) -> tuple[str, dict]:
    """Build the numbered LLM chunk block for one section: one line per
    citation with non-empty chunk text -- "[i] <paper_title> -- <chunk
    text, truncated to _MAX_CHUNK_CHARS>" -- numbered by an LLM-facing ref
    index i (0-based, contiguous across only the SCORABLE citations -- a
    citation with empty chunk text is skipped entirely, so it never
    receives a fabricated score). Pure; never raises.

    Returns (block, ref_to_index) where ref_to_index maps each LLM-facing
    ref -> the citation's index in the original *citations* list (so
    score_section can map an LLM score back onto the right citation even
    though skipped citations shift the numbering).
    """
    lines: list[str] = []
    ref_to_index: dict[int, int] = {}
    ref = 0
    for i, citation in enumerate(citations or []):
        text = chunk_texts[i] if i < len(chunk_texts) else ""
        if not text:
            continue
        title = "Untitled"
        if isinstance(citation, dict):
            title = str(citation.get("paper_title") or "").strip() or "Untitled"
        truncated = text[:_MAX_CHUNK_CHARS]
        lines.append(f"[{ref}] {title} -- {truncated}")
        ref_to_index[ref] = i
        ref += 1
    return "\n".join(lines), ref_to_index


# ---------------------------------------------------------------------------
# _normalize_scores
# ---------------------------------------------------------------------------

def _normalize_scores(parsed: Any, valid_refs: set) -> dict:
    """Pure post-processing of the LLM's raw "scores" list: drops any
    entry whose ref is not in valid_refs (an invented ref -- dropped,
    never scored), clamps relevance to [0.0, 1.0], normalizes stance to
    one of {supports, contradicts, neutral} (anything else -> neutral),
    coerces rationale to a str. A non-dict `parsed`, or a non-list
    `parsed["scores"]`, returns {} (empty -- no scores, never raises).

    Returns {ref: {"relevance": float, "stance": str, "rationale": str}}.
    """
    if not isinstance(parsed, dict):
        return {}
    raw_scores = parsed.get("scores")
    if not isinstance(raw_scores, list):
        return {}

    out: dict[int, dict] = {}
    for entry in raw_scores:
        if not isinstance(entry, dict):
            continue
        ref = entry.get("ref")
        if not isinstance(ref, int) or ref not in valid_refs:
            continue

        relevance = entry.get("relevance", 0.0)
        try:
            relevance = float(relevance)
        except (TypeError, ValueError):
            relevance = 0.0
        relevance = max(0.0, min(1.0, relevance))

        stance = entry.get("stance")
        stance = stance if stance in _VALID_STANCES else "neutral"

        rationale = entry.get("rationale", "")
        rationale = str(rationale) if rationale else ""

        out[ref] = {"relevance": relevance, "stance": stance, "rationale": rationale}
    return out


# ---------------------------------------------------------------------------
# score_section
# ---------------------------------------------------------------------------

def score_section(
    question: str,
    answer: str,
    citations: list,
    *,
    load_text_fn: Callable[[str], str | None] = store.load_text,
    llm: Callable[[str], str] | None = None,
) -> list:
    """Score one section's cited evidence chunks against its question/
    answer via ONE RCS_PROMPT LLM call, batched-numbered-block style
    (mirrors gaps.synthesize_gaps). Returns a list index-aligned with
    *citations*: each entry is an rcs dict {"relevance": float, "stance":
    str, "rationale": str} for a citation whose real chunk text was
    scored, or None for a citation that had no loadable chunk text, wasn't
    returned by the LLM (an invented ref never maps back to a citation),
    or when there were no scorable chunks / no llm / the call or parse
    failed. Never raises.
    """
    from research_companion.extract import _strip_code_fences
    from research_companion.prompts import format_rcs_prompt

    citations = list(citations or [])
    chunk_texts = [_chunk_text(c, load_text_fn=load_text_fn) for c in citations]
    chunks_block, ref_to_index = _chunks_block(citations, chunk_texts)

    results: list = [None] * len(citations)
    if not ref_to_index or llm is None:
        return results

    prompt = format_rcs_prompt(
        question=str(question or ""), answer=str(answer or ""), chunks_block=chunks_block,
    )

    try:
        raw = llm(prompt)
        parsed = json.loads(_strip_code_fences(raw)) if isinstance(raw, str) else raw
    except Exception:
        return results

    scores_by_ref = _normalize_scores(parsed, set(ref_to_index.keys()))
    for ref, idx in ref_to_index.items():
        if ref in scores_by_ref:
            results[idx] = scores_by_ref[ref]
    return results
