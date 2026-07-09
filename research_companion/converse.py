"""Talk-to-the-analysis: companion voice for Research Companion v0.3.

Allows conversational grounded Q&A over any analysis artifact (review report,
alignment, suggestions, gaps, or paper metadata).  Persists multi-turn history
as JSONL under papergraph_dir()/conversations/<id>.jsonl.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from research_companion import store
from research_companion.prompts import (
    converse_prompt_sha256,
    extraction_prompt_sha256,
    format_converse_prompt,
)
from research_companion.qa import (
    QASource,
    _resolve_llm,
    build_section_index,
    build_sources_block,
    extract_unverified_quotes,
    parse_citations,
)
from research_companion.rank import tokenize

# ---------------------------------------------------------------------------
# Valid context types
# ---------------------------------------------------------------------------

_VALID_CONTEXT_TYPES = frozenset({"review", "alignment", "suggestions", "gaps", "paper"})

# ---------------------------------------------------------------------------
# Public data classes / errors
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConverseResult:
    answer: str
    citations: list  # list of QASource-shaped dicts or QASource objects
    unverified_quotes: list[str]
    conversation_id: str


class ConverseError(ValueError):
    """Raised for unknown context type, missing artifact, or empty message.

    Attributes:
        status (int): HTTP-status hint — 400 for validation errors,
                      404 for missing artifacts.
    """

    def __init__(self, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


# ---------------------------------------------------------------------------
# Context builders
# ---------------------------------------------------------------------------

def _project_overview_block(paper_id: str | None) -> tuple[str, list[str]]:
    """Fallback context when no review report exists: what's in the lab right now."""
    lines: list[str] = [
        "No review report exists yet"
        + (f" for paper {paper_id!r}" if paper_id else "")
        + " — here is a project overview instead.",
    ]

    draft_id = store.get_draft_paper_id()
    papers = store.list_papers()
    if draft_id:
        draft_title = next((p.title for p in papers if p.paper_id == draft_id), draft_id)
        lines.append(f"Draft under revision: {draft_title}")
    if papers:
        lines.append(f"Library: {len(papers)} paper(s):")
        for p in papers[:25]:
            year = f" ({p.year})" if p.year else ""
            marker = " [draft]" if p.paper_id == draft_id else ""
            lines.append(f"  - {p.title}{year}{marker}")
    else:
        lines.append("Library: empty — no papers ingested yet.")

    if draft_id:
        from research_companion.suggestions import load_suggestions
        payload = load_suggestions(draft_id)
        if payload:
            items = payload.get("suggestions", [])
            open_n = sum(1 for s in items if s.get("status") == "open")
            addressed_n = sum(1 for s in items if s.get("status") == "addressed")
            lines.append(
                f"Suggestions: {open_n} open, {addressed_n} addressed."
            )

    rendered = "\n".join(lines)
    return rendered, [rendered]


def _context_block_review(context: dict) -> tuple[str, list[str]]:
    """Build context block from a review report."""
    paper_id = context.get("id") or store.get_draft_paper_id()
    if paper_id is None:
        return _project_overview_block(None)

    report = store.load_review_report(paper_id)
    if report is None:
        # "review" is the FAB's default context — a missing report must not kill
        # the chat. Degrade to a project overview so the companion can still talk.
        return _project_overview_block(paper_id)

    lines: list[str] = [f"Review Report for paper: {paper_id}"]
    lanes = report.get("lanes", {})
    if isinstance(lanes, dict):
        for lane_name, lane_data in lanes.items():
            if isinstance(lane_data, dict):
                ok = lane_data.get("ok", True)
                item_status = "ok" if ok else "error"
                lines.append(f"Lane {lane_name}: {item_status}")
                items = lane_data.get("items", [])
                for item in items:
                    if isinstance(item, dict):
                        lines.append(f"  - {item.get('message', str(item))}")
                    else:
                        lines.append(f"  - {item}")

    rendered = "\n".join(lines)
    artifact_texts = [rendered]
    return rendered, artifact_texts


def _context_block_alignment(context: dict) -> tuple[str, list[str]]:
    """Build context block from an alignment record."""
    paper_id = context.get("id")
    draft_id = store.get_draft_paper_id()
    if paper_id is None:
        raise ConverseError("Alignment context requires an id.", status=400)

    alignment = store.load_alignment(paper_id, draft_paper_id=draft_id)
    if alignment is None:
        raise ConverseError(
            f"No alignment found for paper {paper_id!r}.", status=404
        )

    lines: list[str] = [
        f"Alignment: paper={paper_id!r} vs draft={draft_id!r}",
        f"Verdict: {alignment.get('verdict', 'n/a')}",
        f"Score: {alignment.get('score', 'n/a')}",
    ]
    for sec in alignment.get("sections", []):
        sec_id = sec.get("section_id", "")
        relation = sec.get("relation", "")
        rationale = sec.get("rationale", "")
        evidence_items = sec.get("evidence", [])
        lines.append(f"\nSection {sec_id}: {relation}")
        lines.append(f"  Rationale: {rationale}")
        for ev in evidence_items:
            quote = ev.get("quote", "") if isinstance(ev, dict) else str(ev)
            if quote:
                lines.append(f'  Evidence: "{quote}"')

    rendered = "\n".join(lines)
    # Include rationale + evidence texts for quote verification
    artifact_texts: list[str] = [rendered]
    for sec in alignment.get("sections", []):
        rationale = sec.get("rationale", "")
        if rationale:
            artifact_texts.append(rationale)
        for ev in sec.get("evidence", []):
            q = ev.get("quote", "") if isinstance(ev, dict) else ""
            if q:
                artifact_texts.append(q)
    return rendered, artifact_texts


def _context_block_suggestions(context: dict) -> tuple[str, list[str]]:
    """Build context block from a suggestions payload."""
    from research_companion.suggestions import load_suggestions

    paper_id = context.get("id") or store.get_draft_paper_id()
    if paper_id is None:
        raise ConverseError("No paper id for suggestions context and no draft configured.", status=404)

    payload = load_suggestions(paper_id)
    if payload is None:
        raise ConverseError(
            f"No suggestions found for paper {paper_id!r}.", status=404
        )

    sugs = payload.get("suggestions", [])
    lines: list[str] = [f"Suggestions for paper: {paper_id}"]
    for idx, sug in enumerate(sugs, 1):
        sug_id = sug.get("id", "")
        kind = sug.get("kind", "")
        severity = sug.get("severity", "")
        title = sug.get("title", "")
        detail = sug.get("detail", "")
        item_status = sug.get("status", "open")
        lines.append(
            f"\n{idx}. [{severity.upper()}] {title} (id={sug_id}, kind={kind}, status={item_status})"
        )
        if detail:
            lines.append(f"   Detail: {detail}")

    rendered = "\n".join(lines)
    artifact_texts = [rendered]
    return rendered, artifact_texts


def _load_gaps(paper_id: str) -> list[dict]:
    """Load per-paper gaps.json; returns [] when absent (T9 may not be in flight yet)."""
    gaps_path = store.paper_dir(paper_id) / "gaps.json"
    if not gaps_path.exists():
        return []
    try:
        data = json.loads(gaps_path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("gaps", [])
    except (json.JSONDecodeError, ValueError):
        pass
    return []


def _context_block_gaps(context: dict) -> tuple[str, list[str]]:
    """Build context block from per-paper gaps."""
    paper_id = context.get("id") or store.get_draft_paper_id()
    if paper_id is None:
        raise ConverseError("No paper id for gaps context and no draft configured.", status=404)

    # Gaps may not exist yet (T9 in flight) — treat missing as empty (not an error)
    gaps = _load_gaps(paper_id)

    lines: list[str] = [f"Gaps for paper: {paper_id}"]
    if not gaps:
        lines.append("(No gaps identified yet.)")
    else:
        for idx, gap in enumerate(gaps, 1):
            if isinstance(gap, dict):
                title = gap.get("title", gap.get("gap", str(gap)))
                item_status = gap.get("status", "open")
                lines.append(f"\n{idx}. {title} (status={item_status})")
                detail = gap.get("detail", gap.get("description", ""))
                if detail:
                    lines.append(f"   {detail}")
            else:
                lines.append(f"\n{idx}. {gap}")

    rendered = "\n".join(lines)
    artifact_texts = [rendered]
    return rendered, artifact_texts


def _context_block_paper(context: dict) -> tuple[str, list[str]]:
    """Build context block from paper metadata + extraction summary."""
    paper_id = context.get("id") or store.get_draft_paper_id()
    if paper_id is None:
        raise ConverseError("No paper id for paper context and no draft configured.", status=404)

    meta = store.PaperMetadata.load(paper_id)
    if meta is None:
        raise ConverseError(
            f"Paper not found: {paper_id!r}.", status=404
        )

    lines: list[str] = [
        f"Paper: {meta.title}",
        f"Authors: {', '.join(meta.authors)}",
        f"Year: {meta.year}",
    ]
    if meta.abstract:
        lines.append(f"Abstract: {meta.abstract[:500]}")

    # Load extraction if available
    prompt_sha = extraction_prompt_sha256()
    extraction = store.load_extraction(paper_id, prompt_sha=prompt_sha)
    if extraction:
        claims = extraction.get("claims", [])
        methods = extraction.get("methods", [])
        results = extraction.get("results", [])
        lines.append(
            f"\nExtraction summary: {len(claims)} claims, "
            f"{len(methods)} methods, {len(results)} results."
        )
        for claim in claims[:5]:
            text = claim.get("text", "") if isinstance(claim, dict) else str(claim)
            if text:
                lines.append(f"  Claim: {text}")

    rendered = "\n".join(lines)
    artifact_texts = [rendered]
    return rendered, artifact_texts


_CONTEXT_BUILDERS = {
    "review": _context_block_review,
    "alignment": _context_block_alignment,
    "suggestions": _context_block_suggestions,
    "gaps": _context_block_gaps,
    "paper": _context_block_paper,
}


def _build_context_block(context: dict) -> tuple[str, list[str]]:
    """Dispatch to the appropriate context builder."""
    ctx_type = context.get("type", "")
    if ctx_type not in _VALID_CONTEXT_TYPES:
        raise ConverseError(
            f"Unknown context type {ctx_type!r}. Must be one of: "
            + ", ".join(sorted(_VALID_CONTEXT_TYPES)),
            status=400,
        )
    builder = _CONTEXT_BUILDERS[ctx_type]
    return builder(context)


# ---------------------------------------------------------------------------
# Conversation persistence
# ---------------------------------------------------------------------------

def _conversations_dir() -> Path:
    d = store.papergraph_dir() / "conversations"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _conv_path(conversation_id: str) -> Path:
    # Sanitise: keep only alphanumerics + underscore + hyphen
    safe = re.sub(r"[^A-Za-z0-9_\-]", "_", conversation_id)
    return _conversations_dir() / f"{safe}.jsonl"


def _new_conversation_id(now_iso: str, message: str) -> str:
    digest = hashlib.sha256((now_iso + message).encode("utf-8")).hexdigest()[:8]
    return f"conv_{digest}"


_HISTORY_READ_LIMIT = 64 * 1024  # 64 KB tail read cap


def _load_history(conversation_id: str, history_char_budget: int) -> str:
    """Read turns from the JSONL file; keep newest turns fitting the budget.

    Reads at most the last ~64 KB of the file to avoid unbounded memory use on
    large conversation files.  A possibly-partial first line after the seek is
    discarded before JSON parsing.

    Returns formatted history block as "User: ...\nCompanion: ..." lines,
    or empty string when no history or no file.
    """
    path = _conv_path(conversation_id)
    if not path.exists():
        return ""

    file_size = path.stat().st_size
    turns: list[dict] = []
    with path.open("rb") as fh:
        if file_size > _HISTORY_READ_LIMIT:
            fh.seek(-_HISTORY_READ_LIMIT, 2)  # seek from end
            raw_bytes = fh.read()
            raw_lines = raw_bytes.decode("utf-8", errors="replace").splitlines()
            # First line after a mid-file seek is likely partial — drop it
            raw_lines = raw_lines[1:]
        else:
            raw_lines = fh.read().decode("utf-8", errors="replace").splitlines()

    for line in raw_lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        # Skip meta lines
        if "meta" in obj:
            continue
        role = obj.get("role", "")
        content = obj.get("content", "")
        if role and content:
            turns.append({"role": role, "content": content})

    if not turns:
        return ""

    # Build pairs (user, assistant) from the end, keeping within budget
    formatted_turns: list[str] = []
    used = 0
    i = len(turns) - 1
    while i >= 0:
        t = turns[i]
        role_label = "Companion" if t["role"] == "assistant" else "User"
        line = f"{role_label}: {t['content']}"
        line_chars = len(line) + 1  # +1 for newline
        if used + line_chars > history_char_budget and formatted_turns:
            break
        formatted_turns.insert(0, line)
        used += line_chars
        i -= 1

    return "\n".join(formatted_turns)


def _persist_conversation(
    conversation_id: str,
    context: dict,
    message: str,
    answer_text: str,
    *,
    created_at: str,
    is_new: bool,
) -> None:
    """Append turns to the conversation JSONL file."""
    path = _conv_path(conversation_id)
    lines: list[str] = []

    if is_new:
        meta_line = json.dumps({
            "meta": {
                "conversation_id": conversation_id,
                "context": context,
                "created_at": created_at,
                "prompt_sha256": converse_prompt_sha256(),
            }
        }, ensure_ascii=False)
        lines.append(meta_line)

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    user_line = json.dumps({"role": "user", "content": message, "at": now}, ensure_ascii=False)
    assistant_line = json.dumps(
        {"role": "assistant", "content": answer_text, "at": now}, ensure_ascii=False
    )
    lines.extend([user_line, assistant_line])

    with path.open("a", encoding="utf-8") as fh:
        for line in lines:
            fh.write(line + "\n")


def delete_conversation(conversation_id: str) -> bool:
    """Delete a conversation's JSONL file. Returns True if a file was removed."""
    path = _conv_path(conversation_id)
    if not path.exists():
        return False
    path.unlink()
    return True


def load_conversation(conversation_id: str) -> dict | None:
    """Load a conversation from JSONL. Returns {"meta": {...}, "turns": [...]} or None."""
    path = _conv_path(conversation_id)
    if not path.exists():
        return None

    meta: dict | None = None
    turns: list[dict] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "meta" in obj:
                meta = obj["meta"]
            elif "role" in obj:
                turns.append(obj)

    if meta is None and not turns:
        return None

    return {"meta": meta or {}, "turns": turns}


# ---------------------------------------------------------------------------
# Main converse function
# ---------------------------------------------------------------------------

def converse(
    message: str,
    *,
    context: dict,
    conversation_id: str | None = None,
    llm: Any = None,
    embed_query: Any = None,
    k_sections: int | None = None,
    char_budget: int | None = None,
    history_char_budget: int = 4000,
    now: str | None = None,
) -> ConverseResult:
    """Answer *message* grounded in the given analysis artifact + retrieved paper sections.

    Args:
        message:            The user's message / question.
        context:            Dict with "type" (one of review/alignment/suggestions/gaps/paper)
                            and optional "id".
        conversation_id:    Existing conversation to continue; None -> new conversation.
        llm:                Callable(prompt: str) -> str.  None -> auto-resolved.
        embed_query:        Optional embedding callable for hybrid retrieval.
        k_sections:         How many top sections to retrieve (None -> settings default).
        char_budget:        Max chars for the sources block (None -> settings default).
        history_char_budget: Max chars for conversation history injected into prompt.
        now:                ISO timestamp override (for testing); None -> utcnow.

    Returns:
        ConverseResult with answer, citations, unverified_quotes, conversation_id.

    Raises:
        ConverseError: for empty message, unknown context type, or missing artifact.
    """
    # --- 0. Validate inputs ---------------------------------------------------
    if not message or not message.strip():
        raise ConverseError("Message must not be empty.", status=400)

    ctx_type = context.get("type", "")
    if ctx_type not in _VALID_CONTEXT_TYPES:
        raise ConverseError(
            f"Unknown context type {ctx_type!r}. Must be one of: "
            + ", ".join(sorted(_VALID_CONTEXT_TYPES)),
            status=400,
        )

    # --- 1. Resolve settings defaults ----------------------------------------
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

    # --- 2. Build context block ----------------------------------------------
    context_block, artifact_texts = _build_context_block(context)

    # --- 3. Retrieval --------------------------------------------------------
    # Build query from message + key context words (type + id)
    query_extra = f"{ctx_type} {context.get('id', '')}"
    retrieval_query = message + " " + query_extra
    q_tokens = tokenize(retrieval_query)

    all_units = build_section_index()

    if all_units:
        import os as _os

        from research_companion.retrieve import rank_units

        if embed_query is not None or _os.environ.get("HF_TOKEN"):
            from research_companion import store as _store
            seen: set[str] = set()
            for u in all_units:
                pid = u.get("paper_id", "")
                if pid in seen:
                    continue
                seen.add(pid)
                if _store.load_embeddings(pid) is None:
                    try:
                        from research_companion.embed import embed_paper_sections
                        embed_paper_sections(pid)
                    except Exception:
                        continue

        ranked = rank_units(retrieval_query, q_tokens, all_units,
                            k=k_sections, embed_query=embed_query)
    else:
        ranked = []

    if ranked:
        top_units = [r["unit"] for r in ranked]
        top_scores = [r["score"] for r in ranked]
        sources_block, offered_texts = build_sources_block(top_units, top_scores, char_budget)
        qa_sources: list[QASource] = [
            QASource(
                paper_id=u["paper_id"],
                paper_title=u["paper_title"],
                section_id=u["section_id"],
                section_title=u["section_title"],
                score=s,
                char_start=u.get("char_start", 0),
                char_end=u.get("char_end", 0),
                chunk_index=u.get("chunk_index", 0),
            )
            for u, s in zip(top_units, top_scores, strict=False)
        ]
    else:
        sources_block = "(No relevant paper sections found.)"
        offered_texts = []
        qa_sources = []

    # --- 4. Conversation history ---------------------------------------------
    now_iso = now or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    if conversation_id is None:
        is_new = True
        conversation_id = _new_conversation_id(now_iso, message)
    else:
        # Client supplied an id: treat as new if the file does not exist yet
        # so the meta line gets written for that explicit id.
        is_new = not _conv_path(conversation_id).exists()

    history_block = _load_history(conversation_id, history_char_budget)
    if not history_block:
        history_block = "(No prior conversation.)"

    # --- 5. Call LLM ---------------------------------------------------------
    if llm is None:
        llm = _resolve_llm()

    prompt = format_converse_prompt(
        context_block=context_block,
        sources_block=sources_block,
        history_block=history_block,
        message=message,
    )
    raw_answer = llm(prompt)

    # --- 6. Parse citations --------------------------------------------------
    cited = parse_citations(raw_answer, qa_sources)

    # --- 7. Quote verification -----------------------------------------------
    # Check against both artifact texts and offered source texts
    all_texts_for_verify = artifact_texts + offered_texts
    unverified_quotes = extract_unverified_quotes(raw_answer, all_texts_for_verify)

    # --- 8. Persist conversation ---------------------------------------------
    _persist_conversation(
        conversation_id,
        context,
        message,
        raw_answer,
        created_at=now_iso,
        is_new=is_new,
    )

    # --- 9. Build citations as dicts (matching /api/ask handler shape) -------
    cited_ids = {(s.paper_id, s.section_id) for s in cited}
    citation_dicts = [
        {
            "n": i + 1,
            "paper_id": s.paper_id,
            "title": s.paper_title,
            "section_id": s.section_id,
            "section_title": s.section_title,
            "cited": (s.paper_id, s.section_id) in cited_ids,
            # Absolute source offsets for exact-span reader highlighting
            # (mirrors /api/ask — Phase 3 Task B).
            "char_start": s.char_start,
            "char_end": s.char_end,
            "chunk_index": s.chunk_index,
        }
        for i, s in enumerate(qa_sources)
    ]

    return ConverseResult(
        answer=raw_answer,
        citations=citation_dicts,
        unverified_quotes=unverified_quotes,
        conversation_id=conversation_id,
    )
