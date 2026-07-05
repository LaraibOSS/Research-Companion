"""Draft alignment engine.

For each candidate paper, determines which sections of the draft paper it
strengthens / challenges / offers an alternative perspective on — with
evidence quotes verified verbatim against the candidate's own text and a
deterministic usefulness score with an uncertainty band.

Canonical payload (version 1):
    {
        "version": 1,
        "draft_paper_id": str,
        "candidate_paper_id": str,
        "prompt_sha256": str,
        "computed_at": str (UTC ISO),
        "score": float,
        "band": float,
        "verdict": "high"|"medium"|"low",
        "signals": {
            "quote_verification": float,
            "llm_relevance": float,
            "lexical_overlap": float,
        },
        "sections": [           # irrelevant entries excluded
            {
                "section_id": str,
                "section_title": str,
                "relation": "strengthens"|"challenges"|"alternative"|"irrelevant",
                "relevance": float,   # clamped [0,1]
                "rationale": str,
                "evidence": [{"quote": str, "verified": bool, "match": str}],
            }
        ],
    }

Scoring weights (exact — UI and API depend on these):
    quote_verification 1.0, llm_relevance 0.8, lexical_overlap 0.6
    score = (1.0*vf + 0.8*mr + 0.6*lx) / (1.0+0.8+0.6)
    band  = clamp(0.5/sqrt(3) + 0.5*stdev([vf, mr, lx]), 0.05, 0.5)

Vocabulary (stored / reported):
    LLM output "different_perspective" -> stored "alternative"
    All other: strengthens, challenges, irrelevant kept as-is

Persist rules:
    persist=True   -> always writes
    persist=False  -> never writes
    persist=None   -> writes only when draft_id == store.get_draft_paper_id()
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from typing import Callable

from research_companion import store
from research_companion.prompts import alignment_prompt_sha256, format_alignment_prompt
from research_companion.rebuttal.verify import verify_quote as _verify_quote_fn
from research_companion.sections import (
    Section,
    build_and_save_sections,
    is_boilerplate,
    section_text,
)

# ---------------------------------------------------------------------------
# Stopwords (mirrors chat.py's _STOP set; Task 7 will centralize)
# ---------------------------------------------------------------------------

_STOP: frozenset[str] = frozenset({
    "the", "a", "an", "of", "in", "on", "to", "for", "and", "or", "is", "are",
    "what", "which", "how", "why", "do", "does", "did", "this", "that", "these",
    "those", "with", "from", "by", "as", "be", "been", "being", "was", "were",
    "it", "its", "they", "them", "their", "there", "here", "we", "you",
})

# Scoring weights (exact — UI and API depend on these)
_W_VF = 1.0   # quote_verification
_W_MR = 0.8   # llm_relevance
_W_LX = 0.6   # lexical_overlap
_W_SUM = _W_VF + _W_MR + _W_LX   # 2.4

# Vocabulary mapping: LLM output -> stored
_RELATION_MAP: dict[str, str] = {
    "different_perspective": "alternative",
}


# ---------------------------------------------------------------------------
# Public error type
# ---------------------------------------------------------------------------

class AlignmentError(RuntimeError):
    """Raised for unrecoverable alignment failures (bad LLM JSON, schema errors, etc.)."""


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def score_alignment(
    verified_frac: float, mean_relevance: float, lexical: float
) -> tuple[float, float]:
    """Compute (score, band) for a set of three signal values.

    score = (1.0*vf + 0.8*mr + 0.6*lx) / 2.4
    band  = clamp(0.5/sqrt(3) + 0.5*stdev([vf, mr, lx]), 0.05, 0.5)
    """
    score = (_W_VF * verified_frac + _W_MR * mean_relevance + _W_LX * lexical) / _W_SUM
    values = [verified_frac, mean_relevance, lexical]
    mean = sum(values) / len(values)
    stdev = math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))
    band = min(0.5, max(0.05, 0.5 / math.sqrt(len(values)) + 0.5 * stdev))
    return score, band


def usefulness_verdict(score: float) -> str:
    """Map a score to a verdict string."""
    if score >= 0.7:
        return "high"
    if score >= 0.4:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# Lexical overlap (Jaccard on lowercase alnum tokens len>=3 minus stopwords)
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> set[str]:
    """Lowercase alnum tokens of length >= 3, excluding stopwords."""
    import re
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w for w in words if len(w) >= 3 and w not in _STOP}


def lexical_overlap(a_tokens: set[str], b_tokens: set[str]) -> float:
    """Jaccard similarity on two sets of tokens."""
    if not a_tokens and not b_tokens:
        return 0.0
    union = a_tokens | b_tokens
    if not union:
        return 0.0
    intersection = a_tokens & b_tokens
    return len(intersection) / len(union)


# ---------------------------------------------------------------------------
# rank_draft_sections
# ---------------------------------------------------------------------------

def rank_draft_sections(
    draft_sections: list[Section],
    draft_text: str,
    candidate_meta: store.PaperMetadata,
    candidate_extraction: dict | None,
    k: int = 5,
) -> list[tuple[Section, float]]:
    """Rank non-boilerplate draft sections by lexical overlap with the candidate.

    Deterministic, no LLM.

    Candidate signature = tokens from:
        title + entity labels (concepts/methods/datasets) + claim texts

    Score each non-boilerplate section by lexical_overlap against that signature.
    Return top-k by (score desc, document order).
    """
    # Build candidate signature
    cand_text_parts = [candidate_meta.title or ""]
    if candidate_extraction:
        for key in ("concepts", "methods", "datasets"):
            for item in candidate_extraction.get(key, []):
                name = item.get("name", "")
                if name:
                    cand_text_parts.append(name)
        for claim in candidate_extraction.get("claims", []):
            txt = claim.get("text", "")
            if txt:
                cand_text_parts.append(txt)
    cand_sig = _tokenize(" ".join(cand_text_parts))

    scored: list[tuple[float, int, Section]] = []
    for idx, sec in enumerate(draft_sections):
        if is_boilerplate(sec.title):
            continue
        # Section tokens = title + first 400 chars of section body
        body = section_text(draft_text, sec)[:400]
        sec_tokens = _tokenize(sec.title + " " + body)
        overlap = lexical_overlap(sec_tokens, cand_sig)
        scored.append((overlap, idx, sec))

    # Sort by score desc, then by document order (idx asc) for ties
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [(sec, score) for score, _idx, sec in scored[:k]]


# ---------------------------------------------------------------------------
# align_papers (main entry point)
# ---------------------------------------------------------------------------

def align_papers(
    draft_id: str,
    candidate_id: str,
    *,
    llm: Callable[[str], str],
    force: bool = False,
    persist: bool | None = None,
) -> dict:
    """Align a candidate paper against the draft paper.

    Args:
        draft_id: Paper ID of the draft paper.
        candidate_id: Paper ID of the candidate paper.
        llm: Callable(prompt: str) -> str. Tests inject fakes; CLI wires real provider.
        force: If True, ignore cache and re-run the LLM.
        persist: True = always write; False = never write;
                 None = write only when draft_id == store.get_draft_paper_id().

    Returns:
        Canonical alignment payload dict (version 1).

    Raises:
        ValueError: If draft_id or candidate_id are unknown.
        AlignmentError: If draft_id == candidate_id, or LLM returns bad JSON/schema.
    """
    # Step 1: Load both papers
    draft_meta = store.PaperMetadata.load(draft_id)
    if draft_meta is None:
        raise ValueError(f"Unknown draft paper_id: {draft_id!r}")

    cand_meta = store.PaperMetadata.load(candidate_id)
    if cand_meta is None:
        raise ValueError(f"Unknown candidate paper_id: {candidate_id!r}")

    if draft_id == candidate_id:
        raise AlignmentError(f"draft_id == candidate_id: {draft_id!r}; cannot align a paper with itself.")

    current_sha = alignment_prompt_sha256()

    # Step 2: Cache check
    if not force and persist is not False:
        cached = store.load_alignment(candidate_id, draft_paper_id=draft_id)
        if cached is not None and cached.get("prompt_sha256") == current_sha:
            return cached

    # Step 3: Load draft sections and candidate text
    from research_companion.extract import get_paper_text
    draft_sections = build_and_save_sections(draft_id)

    # Load candidate text (raises FileNotFoundError if no PDF; we treat "" gracefully)
    try:
        cand_text = get_paper_text(cand_meta)
    except FileNotFoundError:
        cand_text = ""

    # Load candidate extraction (may be None)
    from research_companion.prompts import extraction_prompt_sha256
    cand_extraction = store.load_extraction(candidate_id, prompt_sha=extraction_prompt_sha256())

    # Step 4: rank_draft_sections, build prompt, call LLM
    top_sections = rank_draft_sections(
        draft_sections,
        get_paper_text(draft_meta),
        cand_meta,
        cand_extraction,
        k=5,
    )
    top_section_ids = {s.section_id for s, _ in top_sections}
    # We also need all sections by id for lookup
    section_by_id = {s.section_id: s for s in draft_sections}

    # Build draft_sections_block: id, title, first ~400 chars
    try:
        draft_text_full = get_paper_text(draft_meta)
    except FileNotFoundError:
        draft_text_full = ""

    block_lines = []
    for sec, _ in top_sections:
        body = section_text(draft_text_full, sec)[:400]
        block_lines.append(f"[{sec.section_id}] {sec.title}\n{body}")
    draft_sections_block = "\n\n".join(block_lines) if block_lines else "(no sections)"

    # Build candidate_block: title, abstract/first chunk, claims
    cand_parts = [f"Title: {cand_meta.title}"]
    if cand_text:
        cand_parts.append(f"Text (first 2000 chars):\n{cand_text[:2000]}")
    if cand_extraction:
        claims = cand_extraction.get("claims", [])
        if claims:
            claim_lines = [f"- {c.get('text', '')}" for c in claims[:10] if c.get("text")]
            if claim_lines:
                cand_parts.append("Claims:\n" + "\n".join(claim_lines))
    candidate_block = "\n\n".join(cand_parts)

    prompt = format_alignment_prompt(
        draft_sections_block=draft_sections_block,
        candidate_block=candidate_block,
    )
    raw = llm(prompt)

    # Step 5: Parse JSON defensively (first '{' .. last '}')
    first_brace = raw.find("{")
    last_brace = raw.rfind("}")
    if first_brace == -1 or last_brace == -1:
        raise AlignmentError(f"LLM returned no JSON object: {raw[:200]!r}")
    try:
        parsed = json.loads(raw[first_brace:last_brace + 1])
    except json.JSONDecodeError as exc:
        raise AlignmentError(f"LLM returned invalid JSON: {exc}") from exc

    if not isinstance(parsed, dict):
        raise AlignmentError(f"LLM JSON is not an object: {type(parsed).__name__}")
    if "sections" not in parsed:
        raise AlignmentError("LLM JSON missing required key 'sections'")
    if not isinstance(parsed["sections"], list):
        raise AlignmentError("LLM JSON 'sections' is not a list")

    # Step 6: Verify evidence quotes against CANDIDATE text
    # Build final section entries with evidence verification
    out_sections = []
    all_quotes: list[bool] = []

    valid_section_ids = top_section_ids

    for entry in parsed["sections"]:
        if not isinstance(entry, dict):
            continue
        sec_id = entry.get("section_id")
        if sec_id not in valid_section_ids:
            continue

        relation_raw = entry.get("relation", "irrelevant")
        # Map vocabulary
        relation = _RELATION_MAP.get(relation_raw, relation_raw)

        # Clamp relevance
        try:
            relevance = float(entry.get("relevance", 0.0))
        except (TypeError, ValueError):
            relevance = 0.0
        relevance = max(0.0, min(1.0, relevance))

        rationale = entry.get("rationale", "")

        # Verify evidence quotes against candidate text
        evidence_raw = entry.get("evidence", [])
        if not isinstance(evidence_raw, list):
            evidence_raw = []

        verified_evidence = []
        for ev in evidence_raw:
            if not isinstance(ev, dict):
                continue
            quote = ev.get("quote", "")
            verified, match_type = _verify_quote_fn(quote, cand_text)
            verified_evidence.append({
                "quote": quote,
                "verified": verified,
                "match": match_type if match_type else "none",
            })
            all_quotes.append(verified)

        sec_obj = section_by_id.get(sec_id)
        sec_title = sec_obj.title if sec_obj else sec_id

        out_sections.append({
            "section_id": sec_id,
            "section_title": sec_title,
            "relation": relation,
            "relevance": relevance,
            "rationale": rationale,
            "evidence": verified_evidence,
        })

    # Step 7: Map vocab, compute score/band/verdict, build payload
    # Exclude irrelevant sections from payload
    relevant_sections = [s for s in out_sections if s["relation"] != "irrelevant"]

    # verified_frac: if zero quotes -> 0.0 (honesty first)
    if all_quotes:
        verified_frac = sum(1 for v in all_quotes if v) / len(all_quotes)
    else:
        verified_frac = 0.0

    # mean_relevance: mean of non-irrelevant sections; 0.0 if none
    non_irrel = [s for s in out_sections if s["relation"] != "irrelevant"]
    if non_irrel:
        mean_relevance = sum(s["relevance"] for s in non_irrel) / len(non_irrel)
    else:
        mean_relevance = 0.0

    # lexical signal: lexical_overlap between draft text tokens and candidate text tokens
    draft_tokens = _tokenize(draft_text_full)
    cand_tokens = _tokenize(cand_text)
    lx_signal = lexical_overlap(draft_tokens, cand_tokens)

    score, band = score_alignment(verified_frac, mean_relevance, lx_signal)
    verdict = usefulness_verdict(score)

    payload: dict = {
        "version": 1,
        "draft_paper_id": draft_id,
        "candidate_paper_id": candidate_id,
        "prompt_sha256": current_sha,
        "computed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "score": score,
        "band": band,
        "verdict": verdict,
        "signals": {
            "quote_verification": verified_frac,
            "llm_relevance": mean_relevance,
            "lexical_overlap": lx_signal,
        },
        "sections": relevant_sections,
    }

    # Step 8: Persist per rules
    should_persist: bool
    if persist is True:
        should_persist = True
    elif persist is False:
        should_persist = False
    else:
        # persist=None: write only when draft_id == configured draft
        should_persist = (draft_id == store.get_draft_paper_id())

    if should_persist:
        store.save_alignment(candidate_id, payload)

    return payload
