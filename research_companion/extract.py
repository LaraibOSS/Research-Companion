"""LLM-driven structured extraction from a paper PDF.

Pipeline per paper:
    PDF -> parser text -> truncated text -> Anthropic/OpenAI with EXTRACTION_PROMPT
                                       -> JSON dict
                                       -> validated + cached on disk

Caching: keyed on the SHA256 of EXTRACTION_PROMPT, so changing the prompt invalidates
the cache automatically.

The extracted JSON is validated against a small schema; missing keys are filled with
empty lists rather than failing, so a partial LLM response is recoverable.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from research_companion.prompts import extraction_prompt_sha256, render_extraction_prompt
from research_companion.store import (
    PaperMetadata,
    load_extraction,
    load_text,
    pdf_path,
    save_extraction,
    save_text,
)

# Cap on text fed to the extractor. ~50k chars ≈ ~12k tokens, fits comfortably in
# Claude/GPT context with room for the prompt and response. Most papers are 10-30 pages.
MAX_PAPER_CHARS = 50_000

# Default models per provider — single source of truth used by resolve_model().
_DEFAULT_MODELS_BY_PROVIDER: dict[str, str] = {
    "anthropic": "claude-sonnet-4-7",
    "openai": "gpt-4o-2024-11-20",
}


def resolve_model(provider: str, model: str | None = None) -> str:
    """Return the model to use for *provider*, falling back to its default."""
    if model:
        return model
    return _DEFAULT_MODELS_BY_PROVIDER.get(provider, _DEFAULT_MODELS_BY_PROVIDER["anthropic"])


# ---------------------------------------------------------------------------
# PDF -> text
# ---------------------------------------------------------------------------

def pdf_to_text(pdf_file: Path) -> str:
    """Extract plain text from a PDF via the configured parser (pypdfium2 default).

    Kept for back-compat; delegates to the pluggable parser layer. No OCR on the
    default path — a scanned PDF yields "", which the ingest quality gate rejects.
    """
    from research_companion.parsers import get_parser
    return get_parser().parse(pdf_file).text


def get_paper_text(meta: PaperMetadata, *, force: bool = False) -> str:
    """Cached text extraction. Re-extracts if `force` is True."""
    if not force:
        cached = load_text(meta.paper_id)
        if cached is not None:
            return cached
    pdf = pdf_path(meta.paper_id)
    if pdf is None:
        raise FileNotFoundError(f"no PDF on disk for {meta.paper_id}")
    text = pdf_to_text(pdf)
    save_text(meta.paper_id, text)
    return text


def get_paper_parsed(meta: PaperMetadata, *, force: bool = False):
    """Parse the PDF via the pluggable parser, returning the full ParsedDoc and
    caching its text.

    When text is already cached (and not `force`), the parser is NOT re-run: a
    text-only ParsedDoc is returned (structural fields empty) so the heuristic
    sectioner handles structure downstream. This keeps an expensive layout-aware
    conversion (docling) to at most once per paper while still surfacing its
    sections/tables/figures on the fresh-parse path.
    """
    from research_companion.parsers import ParsedDoc, get_parser

    if not force:
        cached = load_text(meta.paper_id)
        if cached is not None:
            return ParsedDoc(text=cached)
    pdf = pdf_path(meta.paper_id)
    if pdf is None:
        raise FileNotFoundError(f"no PDF on disk for {meta.paper_id}")
    doc = get_parser().parse(pdf)
    save_text(meta.paper_id, doc.text)
    return doc


def ocr_fallback_parse(meta: PaperMetadata):
    """Re-parse the PDF with Docling FORCED full-page OCR — the fallback for
    scanned/image-only PDFs whose normal extraction recovered no usable text.

    Returns the OCR ``ParsedDoc`` (its text persisted via ``save_text``), or
    ``None`` when docling is not importable (so the caller can distinguish
    "OCR unavailable" from "OCR ran but still failed" and pick an honest error).

    Slow (minutes/paper) — the caller must invoke it only after the normal
    parse fails the quality gate, never on the digital-PDF happy path. All
    docling imports stay lazy (inside DoclingParser).
    """
    import importlib.util

    if importlib.util.find_spec("docling") is None:
        return None
    from research_companion.parsers.docling_parser import DoclingParser

    pdf = pdf_path(meta.paper_id)
    if pdf is None:
        raise FileNotFoundError(f"no PDF on disk for {meta.paper_id}")
    doc = DoclingParser(full_page_ocr=True).parse(pdf)
    save_text(meta.paper_id, doc.text)
    return doc


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------

class ExtractionError(RuntimeError):
    """Raised when the LLM response cannot be parsed into the expected schema."""


def _truncate(text: str, max_chars: int = MAX_PAPER_CHARS) -> str:
    if len(text) <= max_chars:
        return text
    # Keep the head (intro + methods usually) and a tail slice (results + conclusion).
    head = text[: int(max_chars * 0.7)]
    tail = text[-int(max_chars * 0.3):]
    return head + "\n\n[... text truncated for length ...]\n\n" + tail


def _call_anthropic(prompt: str, *, model: str, max_output_tokens: int = 2048) -> tuple[str, dict]:
    """Returns (text, usage_dict)."""
    from anthropic import Anthropic
    client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    resp = client.messages.create(
        model=model,
        max_tokens=max_output_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(block.text for block in resp.content if getattr(block, "type", "") == "text")
    usage = {
        "input_tokens": resp.usage.input_tokens,
        "output_tokens": resp.usage.output_tokens,
    }
    return text, usage


def _openai_request_kwargs(*, model: str, max_output_tokens: int, json_mode: bool) -> dict:
    """Request kwargs for the OpenAI chat call. json_mode forces a JSON object
    response (extraction/novelty/alignment need it); prose callers (qa, compare
    narrative) must pass json_mode=False or the model mangles free text."""
    kwargs = {
        "model": model,
        "max_tokens": max_output_tokens,
        "temperature": 0.0,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    return kwargs


def _call_openai(prompt: str, *, model: str, max_output_tokens: int = 2048,
                 json_mode: bool = True) -> tuple[str, dict]:
    from openai import OpenAI
    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    resp = client.chat.completions.create(
        messages=[{"role": "user", "content": prompt}],
        **_openai_request_kwargs(model=model, max_output_tokens=max_output_tokens,
                                 json_mode=json_mode),
    )
    text = (resp.choices[0].message.content or "").strip()
    usage = {
        "input_tokens": resp.usage.prompt_tokens if resp.usage else 0,
        "output_tokens": resp.usage.completion_tokens if resp.usage else 0,
    }
    return text, usage


def _strip_code_fences(s: str) -> str:
    """LLMs sometimes wrap JSON in ```json ...``` despite instructions. Strip if present."""
    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()


# Validation: ensures all required keys present (even if empty).
_REQUIRED_KEYS = ("concepts", "methods", "datasets", "claims", "results", "related_work")


def _validate_extraction(data: Any) -> dict[str, list]:
    if not isinstance(data, dict):
        raise ExtractionError(f"extraction is not a JSON object: got {type(data).__name__}")
    out: dict[str, list] = {}
    for key in _REQUIRED_KEYS:
        v = data.get(key, [])
        if v is None:
            v = []
        if not isinstance(v, list):
            raise ExtractionError(f"extraction[{key!r}] is not a list: got {type(v).__name__}")
        out[key] = v
    return out


# Bibliographic backfill: the extractor also returns the paper's own metadata as
# an OPTIONAL `paper_meta` object. We write it back onto PaperMetadata for WEAK
# fields only (never clobber trusted arxiv/doi/s2 data).
_MAX_BACKFILL_AUTHORS = 25
_MAX_BACKFILL_TITLE = 300


def _backfilled_metadata(meta: PaperMetadata, paper_meta: Any) -> dict[str, Any]:
    """Pure decision: which weak fields to fill from `paper_meta`. Never raises.

    Returns a dict of {field: new_value} for fields that should change (may be empty).
    Rules:
      - year: only when meta.year is None and paper_meta.year coerces to int in 1900..2100.
      - authors: only when meta.authors is empty and paper_meta.authors is a non-empty
        list of non-empty strings (stripped, blanks dropped, capped).
      - title: only when meta.source_url is an ``upload://`` and paper_meta.title is a
        non-empty string (stripped, length-capped). Never for arxiv/doi/s2.
    """
    if not isinstance(paper_meta, dict):
        return {}
    changes: dict[str, Any] = {}

    if meta.year is None:
        try:
            y = int(paper_meta.get("year"))
        except (TypeError, ValueError):
            y = None
        if y is not None and 1900 <= y <= 2100:
            changes["year"] = y

    if not meta.authors:
        raw = paper_meta.get("authors")
        if isinstance(raw, list):
            cleaned = [a.strip() for a in raw if isinstance(a, str) and a.strip()]
            if cleaned:
                changes["authors"] = cleaned[:_MAX_BACKFILL_AUTHORS]

    if isinstance(meta.source_url, str) and meta.source_url.startswith("upload://"):
        raw_title = paper_meta.get("title")
        if isinstance(raw_title, str) and raw_title.strip():
            changes["title"] = raw_title.strip()[:_MAX_BACKFILL_TITLE]

    return changes


def _apply_backfill(meta: PaperMetadata, extraction: dict) -> None:
    """Apply _backfilled_metadata to `meta` and persist iff anything changed. Never raises."""
    try:
        changes = _backfilled_metadata(meta, extraction.get("paper_meta"))
    except Exception:
        return
    if not changes:
        return
    for k, v in changes.items():
        setattr(meta, k, v)
    meta.save()


def extract_paper(
    meta: PaperMetadata,
    *,
    provider: str = "anthropic",
    model: str | None = None,
    force: bool = False,
) -> tuple[dict, dict]:
    """Run the LLM extractor on one paper. Returns (extraction_dict, usage_dict).

    Caches the extraction on disk keyed on the prompt SHA. Cached calls return
    `usage_dict = {"input_tokens": 0, "output_tokens": 0, "cached": True}`.
    """
    prompt_sha = extraction_prompt_sha256()

    if not force:
        cached = load_extraction(meta.paper_id, prompt_sha=prompt_sha)
        if cached is not None:
            # Cache hit: still backfill weak metadata (cached extraction may carry paper_meta).
            _apply_backfill(meta, cached)
            return cached, {"input_tokens": 0, "output_tokens": 0, "cached": True}

    text = get_paper_text(meta)
    truncated = _truncate(text)

    # Build section outline (heuristics only; LLM fallback skipped here).
    # Any exception is swallowed so section failure never blocks extraction.
    # Import here to avoid a circular import (sections.py imports get_paper_text from extract.py).
    from research_companion import sections  # noqa: PLC0415

    section_outline = ""
    section_ids: set[str] = set()
    try:
        paper_sections = sections.build_and_save_sections(meta.paper_id)
        section_ids = {s.section_id for s in paper_sections}
        section_outline = "\n".join(
            f"{s.section_id} {s.title}" for s in paper_sections
        )
    except Exception:
        section_outline = ""
        section_ids = set()

    prompt = render_extraction_prompt(
        title=meta.title,
        authors=", ".join(meta.authors) or "(unknown)",
        paper_text=truncated,
        section_outline=section_outline,
    )

    if provider == "anthropic":
        raw, usage = _call_anthropic(prompt, model=resolve_model(provider, model))
    elif provider == "openai":
        raw, usage = _call_openai(prompt, model=resolve_model(provider, model))
    else:
        raise ValueError(f"unknown provider {provider!r} (expected 'anthropic' or 'openai')")

    raw = _strip_code_fences(raw)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ExtractionError(
            f"LLM did not return valid JSON for {meta.paper_id}: {e}\nRaw response:\n{raw[:500]}"
        ) from e

    extraction = _validate_extraction(parsed)

    # Sanitize "section" fields: any value not in the known section ids is set to None.
    # related_work is a list of strings and never has a "section" field — skip it.
    # When section_ids is empty (sections unavailable), all "section" values become None.
    _ENTITY_LIST_KEYS = ("concepts", "methods", "datasets", "claims", "results")
    for key in _ENTITY_LIST_KEYS:
        for entity in extraction.get(key, []):
            if isinstance(entity, dict) and "section" in entity and entity["section"] not in section_ids:
                entity["section"] = None

    # Preserve the optional paper_meta block for backfill + future cache hits;
    # _validate_extraction only keeps the required entity lists.
    if isinstance(parsed, dict) and isinstance(parsed.get("paper_meta"), dict):
        extraction["paper_meta"] = parsed["paper_meta"]

    save_extraction(meta.paper_id, extraction, prompt_sha=prompt_sha)
    _apply_backfill(meta, extraction)
    usage["cached"] = False
    return extraction, usage
