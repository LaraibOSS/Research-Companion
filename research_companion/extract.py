"""LLM-driven structured extraction from a paper PDF.

Pipeline per paper:
    PDF -> pypdf text -> truncated text -> Anthropic/OpenAI with EXTRACTION_PROMPT
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

import pypdf

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
    """Extract plain text from a PDF using pypdf. No OCR (out of scope for v0.1)."""
    reader = pypdf.PdfReader(str(pdf_file))
    parts: list[str] = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            continue
    text = "\n\n".join(p for p in parts if p.strip())
    # Collapse whitespace to keep token cost manageable.
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


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


def _call_openai(prompt: str, *, model: str, max_output_tokens: int = 2048) -> tuple[str, dict]:
    from openai import OpenAI
    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_output_tokens,
        temperature=0.0,
        response_format={"type": "json_object"},
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
    _ENTITY_LIST_KEYS = ("concepts", "methods", "datasets", "claims", "results")
    if section_ids:
        for key in _ENTITY_LIST_KEYS:
            for entity in extraction.get(key, []):
                if isinstance(entity, dict) and "section" in entity:
                    if entity["section"] not in section_ids:
                        entity["section"] = None

    save_extraction(meta.paper_id, extraction, prompt_sha=prompt_sha)
    usage["cached"] = False
    return extraction, usage
