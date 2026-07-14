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
The costed, key-requiring tools (ask_library / review_draft) are deferred to 0.7.1.
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
