"""brief.py — Brainstorm Brief.

Turn a topic + the session's papers (and, optionally, a chosen research
direction) into a structured brief: section headings, each seeded with a few
concrete, citation-grounded bullet points to frame writing around. Scaffolding
to fill in, NOT a finished draft.

Pipeline mirrors ``directions.py``: pure ``_collect_paper_grounding`` -> one
LLM call -> pure ``_assemble_brief``. Never raises.

Honesty guard: every bullet MUST cite a real provided paper. A bullet whose
``grounded_in`` keys all drop (or that cites nothing) is DROPPED — unlike a
research direction, an uncited brief bullet is never shown. The model cites; it
never invents a reference.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable

from research_companion.directions import _dedup_papers, _paper_citation_key
from research_companion.rebuttal.verify import _norm

# ---------------------------------------------------------------------------
# _collect_paper_grounding (pure)
# ---------------------------------------------------------------------------

def _collect_paper_grounding(papers: list[dict]) -> tuple[str, dict[str, dict]]:
    """Build the LLM grounding block + index of citeable papers. The brief
    grounds STRICTLY in the session's papers (no graph/gaps), so the index is
    papers-only. Pure — no network/LLM.

    Returns (grounding_block, index) where index maps a stable ``[p:...]`` key
    to ``{"title", "year", "paper_id", "concepts"}``. grounding_block is "" when
    the index is empty.
    """
    index: dict[str, dict] = {}
    lines: list[str] = []
    for p in _dedup_papers(list(papers or [])):
        key = _paper_citation_key(p)
        if key in index:
            continue
        title = str(p.get("title") or "").strip() or "Untitled"
        year = p.get("year")
        abstract = str(p.get("abstract") or "").strip()
        raw_concepts = p.get("concepts") or []
        concept_names = [
            c if isinstance(c, str) else str((c or {}).get("name", ""))
            for c in raw_concepts
        ]
        concept_names = [c for c in concept_names if c]
        index[key] = {
            "title": title,
            "year": year,
            "paper_id": p.get("paper_id"),
            "concepts": concept_names,
        }
        extra = f" Concepts: {', '.join(concept_names)}." if concept_names else ""
        abstract_bit = f" {abstract[:300]}" if abstract else ""
        lines.append(
            f"- [{key}] {title} ({year if year is not None else 'n.d.'}).{abstract_bit}{extra}"
        )
    return "\n".join(lines), index


# ---------------------------------------------------------------------------
# _assemble_brief (pure)
# ---------------------------------------------------------------------------

def _assemble_brief(llm_result: dict, index: dict[str, dict]) -> list[dict]:
    """Turn raw LLM sections into citation-backed brief sections.

    *llm_result* is the parsed BRIEF_PROMPT JSON:
        {"sections": [{"title", "bullets": [{"text", "grounded_in": [...]}]}]}

    Honesty: any ``grounded_in`` key not in *index* is dropped; a bullet with
    NO surviving citation is dropped entirely; a section left with no bullets
    is dropped; a section/bullet with no text is dropped.

    Returns [{"title", "bullets": [{"text", "citations": [{paper_id, title,
    year}]}]}].
    """
    out: list[dict] = []
    for raw_sec in (llm_result or {}).get("sections", []) or []:
        if not isinstance(raw_sec, dict):
            continue
        title = str(raw_sec.get("title", "")).strip()
        if not title:
            continue
        bullets: list[dict] = []
        for raw_b in raw_sec.get("bullets", []) or []:
            if not isinstance(raw_b, dict):
                continue
            text = str(raw_b.get("text", "")).strip()
            if not text:
                continue
            keys = [k for k in (raw_b.get("grounded_in") or [])
                    if isinstance(k, str) and k in index]
            if not keys:
                continue  # honesty: a brief bullet must cite a real paper
            citations: list[dict] = []
            seen: set = set()
            for k in keys:
                item = index[k]
                dedup = item.get("paper_id") or k
                if dedup in seen:
                    continue
                seen.add(dedup)
                citations.append({
                    "paper_id": item.get("paper_id"),
                    "title": item["title"],
                    "year": item.get("year"),
                })
            bullets.append({"text": text, "citations": citations})
        if bullets:
            out.append({"title": title, "bullets": bullets})
    return out


# ---------------------------------------------------------------------------
# synthesize_brief (orchestrator)
# ---------------------------------------------------------------------------

def synthesize_brief(
    topic: str,
    session_papers: list[dict] = (),
    *,
    direction: dict | None = None,
    llm: Callable[[str], str] | None = None,
) -> dict:
    """Topic + the session's papers (+ an optional chosen direction) -> a
    grounded, cited bullet brief.

    Pipeline: pure collect -> one LLM call -> pure assemble. Never raises. When
    there is nothing to ground on (no papers), the LLM call is skipped and an
    empty brief returned — the brief grounds strictly in real papers, so with
    none there is nothing to cite. Any LLM/parse failure (including ``llm=None``)
    degrades to an empty sections list with ``llm_error`` set.

    Returns {"sections": [...], "brief_id", "generated_from_sha", "topic",
    "llm_error"}.
    """
    from research_companion.extract import _strip_code_fences
    from research_companion.prompts import brief_prompt_sha256, format_brief_prompt

    sha = brief_prompt_sha256()
    topic_str = str(topic or "").strip()
    grounding_block, index = _collect_paper_grounding(list(session_papers or []))

    dir_title = ""
    direction_block = ""
    if isinstance(direction, dict):
        dir_title = str(direction.get("title", "")).strip()
        dir_rat = str(direction.get("rationale", "")).strip()
        if dir_title:
            direction_block = (
                f"Chosen direction: {dir_title}"
                + (f" — {dir_rat}" if dir_rat else "")
                + "\n"
            )

    brief_id = "brief_" + hashlib.sha256(
        _norm(topic_str + "|" + dir_title).encode("utf-8")).hexdigest()[:12]

    if not index:
        return {"sections": [], "brief_id": brief_id, "generated_from_sha": sha,
                "topic": topic_str, "llm_error": None}

    prompt = format_brief_prompt(
        topic=topic_str, grounding_block=grounding_block, direction_block=direction_block)

    raw_sections: list = []
    llm_error: str | None = None
    try:
        raw = llm(prompt)
        data = json.loads(_strip_code_fences(raw)) if isinstance(raw, str) else raw
        candidate = data.get("sections") if isinstance(data, dict) else None
        if isinstance(candidate, list):
            raw_sections = candidate
    except Exception as exc:  # noqa: BLE001 — never raise; surface as llm_error
        raw_sections = []
        llm_error = str(exc) or exc.__class__.__name__

    sections = _assemble_brief({"sections": raw_sections}, index)
    return {"sections": sections, "brief_id": brief_id, "generated_from_sha": sha,
            "topic": topic_str, "llm_error": llm_error}
