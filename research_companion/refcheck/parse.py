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


#: Headings that start a bibliography. Matched on a line of their own so a
#: sentence mentioning "references" mid-paragraph never triggers a split.
_BIB_HEADING_RE = re.compile(
    r"^\s*(?:\d+\.?\s*)?(references|bibliography|works\s+cited|literature\s+cited)"
    r"\s*:?\s*$",
    re.IGNORECASE,
)

#: Headings that END the bibliography — appendices routinely follow it.
_POST_BIB_HEADING_RE = re.compile(
    r"^\s*(?:\d+\.?\s*|[A-Z]\.?\s*)?(appendix|appendices|supplementary"
    r"|supplemental)\b.*$",
    re.IGNORECASE,
)

#: A numbered entry marker: "[12]" or "12." at the start of a line.
_ENTRY_MARKER_RE = re.compile(r"^\s*(?:\[\d{1,3}\]|\(\d{1,3}\)|\d{1,3}\.)\s+")

#: Below this an "entry" is a stray fragment (a page number, a running header)
#: rather than a bibliography line worth looking up.
MIN_ENTRY_CHARS = 25


def bibliography_section(text: str) -> str:
    """The bibliography portion of a paper's plain text, or "" if not found.

    Takes the LAST matching heading: papers cite the word "References" in prose
    and some include a per-section reference list, and the real bibliography is
    the final one. Stops at an appendix heading so appendix prose is not parsed
    as citations.
    """
    lines = (text or "").splitlines()
    start = None
    for i, line in enumerate(lines):
        if _BIB_HEADING_RE.match(line):
            start = i + 1
    if start is None:
        return ""
    end = len(lines)
    for j in range(start, len(lines)):
        if _POST_BIB_HEADING_RE.match(lines[j]):
            end = j
            break
    return "\n".join(lines[start:end]).strip()


def split_reference_entries(section: str) -> tuple[list[str], list[str]]:
    """Split a bibliography into entries.

    Returns ``(entries, unparsed)``. Anything too short or too fragmentary to
    be a reference is returned in ``unparsed`` rather than dropped -- a checker
    that silently discards half a bibliography reports a clean result over
    references it never looked at.

    Two layouts are handled: numbered entries ("[1] ...", "1. ..."), and
    blank-line-separated blocks. Numbered wins when present, because wrapped
    lines within one entry must not become separate references.
    """
    section = (section or "").strip()
    if not section:
        return [], []

    lines = section.splitlines()
    if any(_ENTRY_MARKER_RE.match(ln) for ln in lines):
        blocks, current = [], []
        for ln in lines:
            if _ENTRY_MARKER_RE.match(ln):
                if current:
                    blocks.append(" ".join(current))
                current = [_ENTRY_MARKER_RE.sub("", ln).strip()]
            elif current:
                current.append(ln.strip())
        if current:
            blocks.append(" ".join(current))
    else:
        blocks = [" ".join(b.split()) for b in re.split(r"\n\s*\n", section)]

    entries, unparsed = [], []
    for b in blocks:
        b = " ".join(b.split())
        if not b:
            continue
        (entries if len(b) >= MIN_ENTRY_CHARS else unparsed).append(b)
    return entries, unparsed


def references_from_text(text: str) -> tuple[list[Reference], list[str]]:
    """References parsed straight from a paper's text, with no model call.

    ``references_from_extraction`` needs an LLM build first. This path is
    deterministic and free, so a bibliography can be verified without paying to
    extract the whole paper.

    Returns ``(references, unparsed)``. Report the ``unparsed`` count -- it is
    the honest measure of how much of the bibliography was actually covered.
    """
    entries, unparsed = split_reference_entries(bibliography_section(text))
    return [parse_reference_string(e) for e in entries], unparsed


def references_from_extraction(extraction: dict) -> list[Reference]:
    """Build References from a research-companion extraction's `related_work` strings."""
    return [
        parse_reference_string(entry)
        for entry in extraction.get("related_work", [])
        if entry and entry.strip()
    ]
