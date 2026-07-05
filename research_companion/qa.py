"""Section-scoped grounded Q&A with BM25 retrieval.

Pipeline:
    question -> BM25 over section units -> top-k sections -> LLM with sources_block
             -> grounded answer with [S#] citations -> quote verification -> log
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from research_companion import store
from research_companion.prompts import format_qa_prompt
from research_companion.rank import BM25, tokenize
from research_companion.sections import Section, group_extraction_by_section, is_boilerplate

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class QASource:
    paper_id: str
    paper_title: str
    section_id: str
    section_title: str
    score: float


@dataclass(frozen=True)
class QAAnswer:
    answer: str
    sources: list[QASource]      # all sources offered to the LLM, tagged [S1]..[Sk]
    cited: list[QASource]        # subset actually cited as [S#] in the answer text
    unverified_quotes: list[str] # "double-quoted" spans (>= 20 chars) in answer not found verbatim
    input_chars: int             # size of prompt actually sent (proxy for tokens)


# ---------------------------------------------------------------------------
# Section index
# ---------------------------------------------------------------------------

def build_section_index(paper_ids: list[str] | None = None) -> list[dict]:
    """Build a list of units, one per (paper x non-boilerplate section).

    Each unit has keys:
        paper_id, paper_title, section_id, section_title, tokens, text

    Papers without text.txt are skipped silently.
    Papers without sections.json contribute one whole-paper unit (section_id "s1",
    section_title "Full Text").
    """
    from research_companion.prompts import extraction_prompt_sha256 as _ext_sha

    if paper_ids is None:
        papers = store.list_papers()
        paper_ids = [p.paper_id for p in papers]

    units: list[dict] = []
    ext_sha = _ext_sha()

    for pid in paper_ids:
        meta = store.PaperMetadata.load(pid)
        if meta is None:
            continue

        # Try to load text; skip paper silently if missing
        text = store.load_text(pid)
        if text is None:
            continue

        title = meta.title

        # Load sections
        sections_payload = store.load_sections(pid)
        if sections_payload is not None:
            raw_sections = [Section(**s) for s in sections_payload.get("sections", [])]
        else:
            raw_sections = None

        # Load extraction if cached (for entity label boosting)
        extraction = store.load_extraction(pid, prompt_sha=ext_sha)

        if raw_sections:
            # Group extraction entities by section
            grouped = group_extraction_by_section(extraction, raw_sections) if extraction else {}

            for sec in raw_sections:
                if is_boilerplate(sec.title):
                    continue

                # Text slice for this section
                text_slice = text[sec.char_start:sec.char_end]

                # Build tokens: section title + entity labels for this section + first 300 chars
                token_source = sec.title + " "
                entity_labels: list[str] = []
                if grouped:
                    sec_data = grouped.get(sec.section_id, {})
                    for key in ("concepts", "methods", "datasets"):
                        for item in sec_data.get(key, []):
                            name = item.get("name", "")
                            if name:
                                token_source += name + " "
                                entity_labels.append(name)
                token_source += text_slice[:300]
                tokens = tokenize(token_source)

                units.append({
                    "paper_id": pid,
                    "paper_title": title,
                    "section_id": sec.section_id,
                    "section_title": sec.title,
                    "tokens": tokens,
                    "text": text_slice,
                    "entity_labels": entity_labels,
                })
        else:
            # No sections — whole-paper unit
            token_source = title + " " + text[:300]
            entity_labels: list[str] = []
            if extraction:
                for key in ("concepts", "methods", "datasets"):
                    for item in extraction.get(key, []):
                        name = item.get("name", "")
                        if name:
                            token_source += " " + name
                            entity_labels.append(name)
            tokens = tokenize(token_source)
            units.append({
                "paper_id": pid,
                "paper_title": title,
                "section_id": "s1",
                "section_title": "Full Text",
                "tokens": tokens,
                "text": text,
                "entity_labels": entity_labels,
            })

    return units


# ---------------------------------------------------------------------------
# Quote verification helpers
# ---------------------------------------------------------------------------

def _norm_text(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip()


def _verify_quote(quote: str, text: str) -> bool:
    """Return True if quote is found verbatim or after whitespace-normalization in text."""
    if quote in text:
        return True
    return _norm_text(quote) in _norm_text(text)


# ---------------------------------------------------------------------------
# Main answer function
# ---------------------------------------------------------------------------

_NO_MATERIAL_MSG = (
    "No relevant material in the lab for this question."
)


def answer(
    question: str,
    *,
    llm=None,
    k_sections: int = 6,
    char_budget: int = 8000,
    section_id: str | None = None,
    paper_ids: list[str] | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> QAAnswer:
    """Answer *question* using BM25-retrieved paper sections.

    Args:
        question:   The research question or claim.
        llm:        Callable(prompt: str) -> str. If None, a real LLM provider is wired.
        k_sections: How many top sections to pass as context.
        char_budget: Max total chars for the sources_block.
        section_id: If set, scope query context to the configured draft's section with this id.
                    The draft's own units are excluded from retrieval.
                    Extra query tokens come from that draft section's BM25 tokens.
        paper_ids:  Restrict index to these papers (None = all).
        provider:   "anthropic" or "openai" when llm is None; defaults from
                    RESEARCH_COMPANION_PROVIDER (falling back to "anthropic").
        model:      Model override when llm is None; defaults from RESEARCH_COMPANION_MODEL.
    """
    # --- 1. Build index & determine query tokens --------------------------------
    all_units = build_section_index(paper_ids)

    draft_id = store.get_draft_paper_id() if section_id is not None else None

    # Query = question tokens + (optionally) draft section tokens
    q_tokens = tokenize(question)

    if section_id is not None and draft_id is not None:
        # Find the draft section's tokens to prepend
        for unit in all_units:
            if unit["paper_id"] == draft_id and unit["section_id"] == section_id:
                q_tokens = unit["tokens"] + q_tokens
                break
        # Exclude draft's own units from retrieval
        retrieval_units = [u for u in all_units if u["paper_id"] != draft_id]
    else:
        retrieval_units = all_units

    if not retrieval_units:
        return QAAnswer(_NO_MATERIAL_MSG, [], [], [], 0)

    # --- 2. BM25 scoring -------------------------------------------------------
    corpus = [u["tokens"] for u in retrieval_units]
    bm = BM25(corpus)
    raw_scores = bm.score(q_tokens)

    # Pair each unit with its score, filter zero-score units
    scored = [(score, i) for i, score in enumerate(raw_scores) if score > 0.0]

    if not scored:
        return QAAnswer(_NO_MATERIAL_MSG, [], [], [], 0)

    # Top-k by score (ties: stable index order via sort stability)
    scored.sort(key=lambda t: (-t[0], t[1]))
    top_k = scored[:k_sections]

    top_units = [retrieval_units[i] for _, i in top_k]
    top_scores = [s for s, _ in top_k]

    # --- 3. Build sources_block with header-safe proportional budget trimming ----
    # Strategy: reserve all header lines (+ entities line) first; distribute
    # the REMAINING budget across text slices proportionally (floor 0 if needed).
    # Never hard-trim the joined block — all [S#] headers must always be present.
    total_score = sum(top_scores)

    # Build header strings (with optional entities line) per unit
    header_strings: list[str] = []
    for idx, unit in enumerate(top_units, 1):
        header = f"[S{idx}] {unit['paper_title']} — §{unit['section_title']}"
        entity_labels = unit.get("entity_labels", [])
        if entity_labels:
            header = header + "\n" + ", ".join(entity_labels)
        header_strings.append(header)

    # Compute chars consumed by headers + separators between parts ("\n\n")
    # Each part is: header_string + "\n" + text_slice
    # Joined by "\n\n", so separators add 2*(k-1) chars
    k = len(top_units)
    header_chars = sum(len(h) + 1 for h in header_strings)  # +1 for "\n" after each header
    separator_chars = 2 * (k - 1)  # "\n\n" between parts
    reserved = header_chars + separator_chars
    text_budget = max(0, char_budget - reserved)

    # Distribute text_budget proportionally across slices
    sources_block_parts: list[str] = []
    for _idx, (unit, score, header) in enumerate(
        zip(top_units, top_scores, header_strings, strict=False), 1
    ):
        fraction = (score / total_score) if total_score > 0 else (1.0 / k)
        allocated = int(text_budget * fraction)  # floor; may be 0
        text_slice = unit["text"][:allocated]
        sources_block_parts.append(f"{header}\n{text_slice}")

    sources_block = "\n\n".join(sources_block_parts)

    # --- 4. Build sources list -------------------------------------------------
    sources: list[QASource] = [
        QASource(
            paper_id=unit["paper_id"],
            paper_title=unit["paper_title"],
            section_id=unit["section_id"],
            section_title=unit["section_title"],
            score=score,
        )
        for unit, score in zip(top_units, top_scores, strict=False)
    ]

    # --- 5. Call LLM -----------------------------------------------------------
    if llm is None:
        llm = _resolve_llm(provider=provider, model=model)

    prompt = format_qa_prompt(question=question, sources_block=sources_block)
    input_chars = len(prompt)
    raw_answer = llm(prompt)

    # --- 6. Parse [S#] citations -----------------------------------------------
    cited_indices: list[int] = []
    for m in re.finditer(r"\[S(\d+)\]", raw_answer):
        n = int(m.group(1))
        if 1 <= n <= len(sources):
            idx = n - 1
            if idx not in cited_indices:
                cited_indices.append(idx)
    cited = [sources[i] for i in sorted(cited_indices)]

    # --- 7. Quote verification -------------------------------------------------
    # Extract double-quoted spans >= 20 chars from the answer
    # (normalise smart quotes first)
    answer_norm = raw_answer.replace("“", '"').replace("”", '"')
    quoted_spans = re.findall(r'"([^"]{20,})"', answer_norm)

    # Collect all offered source texts
    offered_texts = [u["text"] for u in top_units]

    unverified_quotes: list[str] = []
    for span in quoted_spans:
        found = any(_verify_quote(span, src_text) for src_text in offered_texts)
        if not found:
            unverified_quotes.append(span)

    # --- 8. Log ----------------------------------------------------------------
    log_path = store.papergraph_dir() / "qa_log.jsonl"
    log_entry = {
        "at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "question": question,
        "answer": raw_answer,
        "sources": [f"{s.paper_id}+{s.section_id}" for s in sources],
        "cited": len(cited),
        "unverified_quotes": len(unverified_quotes),
    }
    with open(log_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

    return QAAnswer(
        answer=raw_answer,
        sources=sources,
        cited=cited,
        unverified_quotes=unverified_quotes,
        input_chars=input_chars,
    )


# ---------------------------------------------------------------------------
# LLM resolver (mirrors pattern from cli.py / alignment.py)
# ---------------------------------------------------------------------------

def _resolve_llm(*, provider: str | None = None, model: str | None = None):
    """Return an LLM callable; provider/model default from the environment
    (RESEARCH_COMPANION_PROVIDER / RESEARCH_COMPANION_MODEL), matching the
    other commands' resolution rules."""
    import os

    from research_companion.extract import _call_anthropic, _call_openai, resolve_model

    provider = provider or os.environ.get("RESEARCH_COMPANION_PROVIDER", "anthropic")
    model = model or os.environ.get("RESEARCH_COMPANION_MODEL") or None
    resolved_model = resolve_model(provider, model)

    def _real_llm(prompt: str) -> str:
        if provider == "openai":
            # Prose answer: JSON mode would mangle free text.
            text, _usage = _call_openai(prompt, model=resolved_model, json_mode=False)
        else:
            text, _usage = _call_anthropic(prompt, model=resolved_model)
        return text

    return _real_llm
