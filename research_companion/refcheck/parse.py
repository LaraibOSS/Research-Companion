"""Turn bibliography text into Reference objects.

Deterministic, best-effort parsing: pull out DOI / arXiv id / year with regexes
and treat the remaining text as the title. No LLM, no network.
"""
from __future__ import annotations

import re

from research_companion.refcheck.validate import Reference

_DOI_RE = re.compile(r"10\.\d{4,9}/[^\s,;]+", re.IGNORECASE)
_ARXIV_RE = re.compile(r"\b(\d{4}\.\d{4,5})(?:v\d+)?\b")
_YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")
_PMID_RE = re.compile(r"\bPMID:?\s*(\d{4,9})\b", re.IGNORECASE)
_PMCID_RE = re.compile(r"\b(PMC\d{4,9})\b", re.IGNORECASE)

# Tokens to strip out before treating what remains as the title.
_ARXIV_TOKEN_RE = re.compile(r"arxiv:\s*\d{4}\.\d{4,5}(?:v\d+)?", re.IGNORECASE)
_DOI_TOKEN_RE = re.compile(r"(?:doi:\s*)?10\.\d{4,9}/[^\s,;]+", re.IGNORECASE)
_YEAR_TOKEN_RE = re.compile(r"\(?\b(?:19\d{2}|20\d{2})\b\)?")
_PMID_TOKEN_RE = re.compile(r"\bPMID:?\s*\d{4,9}\b", re.IGNORECASE)
_PMCID_TOKEN_RE = re.compile(r"\bPMC\d{4,9}\b", re.IGNORECASE)


def extract_doi(raw: str) -> str | None:
    m = _DOI_RE.search(raw)
    return m.group(0).rstrip(".") if m else None


def extract_arxiv_id(raw: str) -> str | None:
    m = _ARXIV_RE.search(raw)
    return m.group(1) if m else None


def extract_year(raw: str) -> int | None:
    m = _YEAR_RE.search(raw)
    return int(m.group(1)) if m else None


def extract_pmid(raw: str) -> str | None:
    m = _PMID_RE.search(raw)
    return m.group(1) if m else None


def extract_pmcid(raw: str) -> str | None:
    m = _PMCID_RE.search(raw)
    return m.group(1).upper() if m else None


def _title_from(raw: str) -> str:
    """Best-effort title: the text left after removing identifiers and the year."""
    text = _ARXIV_TOKEN_RE.sub("", raw)
    text = _DOI_TOKEN_RE.sub("", text)
    text = _YEAR_TOKEN_RE.sub("", text)
    text = _PMID_TOKEN_RE.sub("", text)
    text = _PMCID_TOKEN_RE.sub("", text)
    # Collapse leftover punctuation/whitespace runs and trim stray separators.
    text = re.sub(r"\s+", " ", text)
    return text.strip(" .,;-").strip()


def parse_reference_string(raw: str) -> Reference:
    """Parse one freeform bibliography entry into a Reference (best-effort)."""
    return Reference(
        title=_title_from(raw),
        year=extract_year(raw),
        doi=extract_doi(raw),
        arxiv_id=extract_arxiv_id(raw),
        pmid=extract_pmid(raw),
        pmcid=extract_pmcid(raw),
        raw=raw,
    )


def references_from_extraction(extraction: dict) -> list[Reference]:
    """Build References from a research-companion extraction's `related_work` strings."""
    return [
        parse_reference_string(entry)
        for entry in extraction.get("related_work", [])
        if entry and entry.strip()
    ]
