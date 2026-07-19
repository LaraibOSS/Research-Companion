"""Deterministic, key-free verification tools for the MCP trust-layer server.

These are the *logic* behind the v0.7.0 MCP tools, kept free of any MCP-SDK
import so they can be unit-tested directly and reused. Each wraps an existing
building block and returns a JSON-safe dict:

- ``verify_citation`` — validate a citation against authoritative records (refcheck).
- ``ground_claim``    — check a quote is verbatim-present in a paper (rebuttal.verify).
- ``citation_coverage`` — how much of a draft's bibliography is in the library.
- ``search_library``  — BM25 keyword search over the library (no embeddings, so no key).

Everything here is local and LLM-free. Network is used only by ``verify_citation``
(CrossRef/OpenAlex lookups), and the lookup is injectable so tests stay offline.

Also here: the costed, key-requiring tools --

- ``ask_library``   — LLM Q&A over the local library (qa.answer), cost-gated.
- ``review_draft``  — the reviewer-style agent pipeline (review_runner.run_review),
  cost-gated; ``fast=True`` runs only the deterministic (LLM-free, $0) lanes.

Both estimate a call's cost against the ``mcp_cost_cap_usd`` setting *before*
doing any work and refuse (returning ``{"error", "estimated_cost_usd", "cap_usd"}``)
without ever invoking the LLM/pipeline when the estimate exceeds the cap. Neither
tool ever raises to the caller; failures come back as ``{"error": ...}`` dicts.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any


def verify_citation(
    *,
    title: str | None = None,
    authors: list[str] | None = None,
    year: int | None = None,
    doi: str | None = None,
    arxiv_id: str | None = None,
    raw: str | None = None,
    lookup: Callable[[Any], dict | None] | None = None,
) -> dict:
    """Validate a single citation against authoritative records.

    Returns ``{status: verified|suspect|unverified, reasons, matched, reference}``.
    ``lookup`` is injectable (defaults to CrossRef→OpenAlex→arXiv); pass a stub to
    stay offline.
    """
    from research_companion.refcheck.parse import parse_reference_string
    from research_companion.refcheck.retrieval import default_lookup
    from research_companion.refcheck.validate import Reference, validate_reference

    if raw and not (title or doi or arxiv_id):
        ref = parse_reference_string(raw)
    else:
        ref = Reference(
            title=title or "",
            authors=list(authors or []),
            year=year,
            doi=doi,
            arxiv_id=arxiv_id,
            raw=raw or "",
        )
    verdict = validate_reference(ref, lookup or default_lookup())
    return {
        "status": verdict.status,
        "reasons": list(verdict.reasons),
        "matched": verdict.matched,
        "reference": {
            "title": ref.title,
            "authors": ref.authors,
            "year": ref.year,
            "doi": ref.doi,
            "arxiv_id": ref.arxiv_id,
        },
    }


def ground_claim(*, quote: str, paper_id: str) -> dict:
    """Check whether *quote* appears verbatim in the paper's stored text.

    Returns ``{grounded, match_kind, char_start, char_end, paper_id}``. Grounding
    is exact-or-whitespace-normalized (never semantic): a False result means the
    quote is not literally in the source, not that the claim is wrong.
    """
    from research_companion.rebuttal.verify import locate_quote, verify_quote
    from research_companion.store import load_text

    text = load_text(paper_id)
    if text is None:
        return {"grounded": False, "paper_id": paper_id,
                "error": f"no stored text for paper {paper_id!r}",
                "char_start": None, "char_end": None, "match_kind": ""}

    ok, kind = verify_quote(quote, text)
    span = locate_quote(quote, text)
    return {
        "grounded": ok,
        "paper_id": paper_id,
        "match_kind": kind,
        "char_start": span[0] if span else None,
        "char_end": span[1] if span else None,
    }


def citation_coverage(*, paper_id: str) -> dict:
    """Coverage of a draft's bibliography against the local library.

    Returns ``{paper_id, counts{total,in_library,available,unchecked,unresolved},
    references}`` from the deterministic offline coverage computation.
    """
    from research_companion.citations_coverage import compute_coverage

    payload = compute_coverage(paper_id)
    return {
        "paper_id": paper_id,
        "counts": payload.get("counts", {}),
        "references": payload.get("references", []),
        "source": payload.get("source", ""),
    }


def _bm25_only(_query: str) -> None:
    """Embed-query stub that forces deterministic, key-free BM25 ranking."""
    return None


def search_library(*, query: str, k: int = 6, paper_ids: list[str] | None = None) -> dict:
    """Keyword-search the library, returning grounded snippets with provenance.

    BM25-only (no embeddings), so it needs no API key and is fully deterministic.
    Each result carries the paper id/title, section, a snippet, and absolute
    char offsets for verification.
    """
    from research_companion.qa import build_section_index
    from research_companion.rank import tokenize
    from research_companion.retrieve import rank_units

    units = build_section_index(paper_ids)
    ranked = rank_units(query, tokenize(query), units, k=k, embed_query=_bm25_only)
    results = []
    for r in ranked:
        u = r["unit"]
        text = u.get("text", "")
        results.append({
            "paper_id": u.get("paper_id", ""),
            "paper_title": u.get("paper_title", ""),
            "section_title": u.get("section_title", ""),
            "snippet": text[:300],
            "char_start": u.get("char_start"),
            "char_end": u.get("char_end"),
            "score": round(float(r.get("score", 0.0)), 4),
            "mode": r.get("mode", "bm25"),
        })
    return {"query": query, "results": results}


# --- Costed, key-requiring tools (v2) ---------------------------------------

_ASK_OUTPUT_TOKENS = 2048
_REVIEW_OUTPUT_TOKENS_PER_LANE = 2048
_REVIEW_INPUT_CHARS_PER_LANE = 20_000  # novelty caps fulltext at 20k chars
_N_LLM_LANES_FULL = 6  # novelty, citation_polarity, confidence, benchmark, severity, taxonomy


def _cap_usd() -> float:
    from research_companion.settings import get_settings
    try:
        return float(get_settings().get("mcp_cost_cap_usd", 1.0))
    except Exception:
        return 1.0


def _refusal(estimated: float, cap: float) -> dict:
    return {
        "error": (f"estimated cost ${estimated:.2f} exceeds the "
                  f"mcp_cost_cap_usd cap (${cap:.2f})"),
        "estimated_cost_usd": round(estimated, 4),
        "cap_usd": cap,
    }


def _provider_for_estimate() -> str:
    from research_companion.cost import configured_provider
    resolved = configured_provider()
    return resolved[0] if resolved else "anthropic"


def ask_library(*, question: str, k: int | None = None,
                paper_ids: list[str] | None = None, llm=None) -> dict:
    """LLM Q&A over the local library (costed). Refuses over the per-call cap.

    The input estimate uses the char_budget setting as an upper bound on the
    retrieved context (qa.answer assembles context internally, bounded by it).
    Never raises: failures return {"error": ...}.
    """
    from research_companion.cost import chars_to_tokens, estimate_cost
    from research_companion.settings import get_settings

    try:
        char_budget = int(get_settings().get("char_budget", 8000))
    except Exception:
        char_budget = 8000
    est = estimate_cost(chars_to_tokens(char_budget + len(question)),
                        _ASK_OUTPUT_TOKENS, _provider_for_estimate())
    cap = _cap_usd()
    if est > cap:
        return _refusal(est, cap)

    try:
        from dataclasses import asdict

        from research_companion.qa import answer as qa_answer
        ans = qa_answer(question, llm=llm, k_sections=k, paper_ids=paper_ids)
    except Exception as exc:  # missing key, SDK/network error, ... never raise
        return {"error": str(exc)}
    return {
        "question": question,
        "answer": ans.answer,
        "sources": [asdict(s) for s in ans.sources],
        "cited": [asdict(s) for s in ans.cited],
        "unverified_quotes": list(ans.unverified_quotes),
        "estimated_cost_usd": round(est, 4),
    }


def review_draft(*, paper_id: str, venue: str | None = None, fast: bool = False,
                 llm=None, lookup=None, search=None) -> dict:
    """Run the reviewer-style pipeline on a stored paper (costed, read-only).

    fast=True runs only the deterministic lanes (estimate ~$0). Refuses over
    the per-call cap; never raises: failures return {"error": ...}.
    """
    from research_companion.cost import chars_to_tokens, estimate_cost
    from research_companion.store import PaperMetadata, load_text

    try:
        meta = PaperMetadata.load(paper_id)
        text = load_text(paper_id)
        if meta is None and text is None:
            return {"error": f"unknown paper_id {paper_id!r} — add/ingest it first"}

        n_lanes = 0 if fast else _N_LLM_LANES_FULL + (1 if venue else 0)  # venuefit is the LLM venue lane
        in_tokens = n_lanes * chars_to_tokens(min(len(text or ""), _REVIEW_INPUT_CHARS_PER_LANE))
        est = estimate_cost(in_tokens, n_lanes * _REVIEW_OUTPUT_TOKENS_PER_LANE,
                            _provider_for_estimate())
        cap = _cap_usd()
    except Exception as exc:
        return {"error": str(exc)}
    if est > cap:
        return _refusal(est, cap)

    try:
        from research_companion import review_runner
        report = review_runner.run_review(paper_id, venue=venue, fast=fast,
                                          llm=llm, lookup=lookup, search=search)
    except Exception as exc:
        return {"error": str(exc)}
    report["estimated_cost_usd"] = round(est, 4)
    return report
