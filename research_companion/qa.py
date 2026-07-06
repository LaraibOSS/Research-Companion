"""Section-scoped grounded Q&A with BM25 retrieval.

Pipeline:
    question -> BM25 over section units -> top-k sections -> LLM with sources_block
             -> grounded answer with [S#] citations -> quote verification -> log
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from research_companion import store
from research_companion.prompts import format_qa_prompt
from research_companion.rank import tokenize
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
    grounding_node_ids: list[str] = field(default_factory=list)  # graph nodes behind cited sources


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
# Shared helper functions (also used by converse.py)
# ---------------------------------------------------------------------------

def build_sources_block(
    top_units: list[dict],
    top_scores: list[float],
    char_budget: int,
) -> tuple[str, list[str]]:
    """Build a numbered sources block for LLM prompt injection.

    Returns:
        (sources_block_str, offered_texts) where offered_texts is a list of
        raw section text strings (used for quote verification).

    Strategy: reserve all header lines (+ entities line) first; distribute
    the REMAINING budget across text slices proportionally (floor 0 if needed).
    Never hard-trim the joined block — all [S#] headers must always be present.
    """
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
    offered_texts: list[str] = []
    for unit, score, header in zip(top_units, top_scores, header_strings, strict=False):
        fraction = (score / total_score) if total_score > 0 else (1.0 / k)
        allocated = int(text_budget * fraction)  # floor; may be 0
        text_slice = unit["text"][:allocated]
        sources_block_parts.append(f"{header}\n{text_slice}")
        offered_texts.append(unit["text"])

    sources_block = "\n\n".join(sources_block_parts)
    return sources_block, offered_texts


def parse_citations(answer_text: str, sources: list[QASource]) -> list[QASource]:
    """Parse [S#] citation markers from answer_text and return cited QASource list."""
    cited_indices: list[int] = []
    for m in re.finditer(r"\[S(\d+)\]", answer_text):
        n = int(m.group(1))
        if 1 <= n <= len(sources):
            idx = n - 1
            if idx not in cited_indices:
                cited_indices.append(idx)
    return [sources[i] for i in sorted(cited_indices)]


def extract_unverified_quotes(answer_text: str, offered_texts: list[str]) -> list[str]:
    """Extract double-quoted spans >= 20 chars from answer_text not found in offered_texts.

    Normalises smart quotes before scanning. Returns list of unverified spans.
    """
    answer_norm = answer_text.replace("“", '"').replace("”", '"')
    quoted_spans = re.findall(r'"([^"]{20,})"', answer_norm)

    unverified: list[str] = []
    for span in quoted_spans:
        found = any(_verify_quote(span, src_text) for src_text in offered_texts)
        if not found:
            unverified.append(span)
    return unverified


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
    k_sections: int | None = None,
    char_budget: int | None = None,
    section_id: str | None = None,
    paper_ids: list[str] | None = None,
    provider: str | None = None,
    model: str | None = None,
    embed_query=None,
    backfill=None,
) -> QAAnswer:
    """Answer *question* using hybrid (BM25 + optional embedding) retrieval.

    Args:
        question:   The research question or claim.
        llm:        Callable(prompt: str) -> str. If None, a real LLM provider is wired.
        k_sections: How many top sections to pass as context (None -> settings default).
        char_budget: Max total chars for the sources_block (None -> settings default).
        embed_query: Callable(str) -> vector for hybrid ranking; None -> auto (HF token).
        backfill:   Callable(paper_id) embedding backfiller; None -> real; only invoked
                    when hybrid retrieval is possible.
        section_id: If set, scope query context to the configured draft's section with this id.
                    The draft's own units are excluded from retrieval.
                    Extra query tokens come from that draft section's BM25 tokens.
        paper_ids:  Restrict index to these papers (None = all).
        provider:   "anthropic" or "openai" when llm is None; defaults from
                    RESEARCH_COMPANION_PROVIDER (falling back to "anthropic").
        model:      Model override when llm is None; defaults from RESEARCH_COMPANION_MODEL.
    """
    # --- 0. Resolve retrieval knobs from settings when unspecified ---------------
    if k_sections is None or char_budget is None:
        try:
            from research_companion.settings import get_settings

            _s = get_settings()
        except Exception:
            _s = {}
        if k_sections is None:
            k_sections = int(_s.get("k_sections", 6))
        if char_budget is None:
            char_budget = int(_s.get("char_budget", 8000))

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

    # --- 2. Hybrid ranking (BM25 + optional embeddings) --------------------------
    # Lazy embedding backfill for papers missing vectors — only when hybrid is
    # even possible (an embed_query is provided or an HF token is configured).
    import os as _os

    from research_companion.retrieve import rank_units

    if embed_query is not None or _os.environ.get("HF_TOKEN"):
        if backfill is None:
            from research_companion.embed import embed_paper_sections as backfill  # type: ignore[assignment]
        seen: set[str] = set()
        for u in retrieval_units:
            pid = u.get("paper_id", "")
            if pid in seen:
                continue
            seen.add(pid)
            if store.load_embeddings(pid) is None:
                try:
                    backfill(pid)
                except Exception:
                    continue

    ranked = rank_units(question, q_tokens, retrieval_units,
                        k=k_sections, embed_query=embed_query)
    if not ranked:
        return QAAnswer(_NO_MATERIAL_MSG, [], [], [], 0)

    top_units = [r["unit"] for r in ranked]
    top_scores = [r["score"] for r in ranked]

    # --- 3. Build sources_block with header-safe proportional budget trimming ----
    sources_block, offered_texts = build_sources_block(top_units, top_scores, char_budget)

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
    cited = parse_citations(raw_answer, sources)

    # --- 7. Quote verification -------------------------------------------------
    unverified_quotes = extract_unverified_quotes(raw_answer, offered_texts)

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

    # --- 9. Grounding node ids (cited papers + their section-matched entities) --
    grounding_node_ids = _grounding_node_ids(cited)

    return QAAnswer(
        answer=raw_answer,
        sources=sources,
        cited=cited,
        unverified_quotes=unverified_quotes,
        input_chars=input_chars,
        grounding_node_ids=grounding_node_ids,
    )


def _grounding_node_ids(cited: list[QASource]) -> list[str]:
    """Graph node ids behind the cited sources: each cited paper node plus entity
    nodes connected to it via a `contains` edge tagged with the cited section id.
    Any failure -> empty list; never raises."""
    if not cited:
        return []
    try:
        from research_companion.graph import load_graph

        g = load_graph()
        wanted = {(s.paper_id, s.section_id) for s in cited}
        node_ids: set[str] = set()
        for paper_id, section_id in wanted:
            if paper_id not in g:
                continue
            node_ids.add(paper_id)
            for _, nbr, data in g.edges(paper_id, data=True):
                if data.get("relation") == "contains" and data.get("section") == section_id:
                    node_ids.add(nbr)
        return sorted(node_ids)
    except Exception:
        return []


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
