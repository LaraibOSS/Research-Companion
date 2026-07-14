"""RIS export — deterministic, no dependencies.

RIS is the tag-based format EndNote, Zotero, and most reference managers import.
Accepts ``PaperMetadata`` instances or plain dicts.
"""
from __future__ import annotations

from typing import Any

from research_companion.interop.bibtex import _get


def paper_to_ris(rec: Any, type_tag: str = "JOUR") -> str:
    """Render a single record as an RIS entry (ending with the ER tag)."""
    lines = [f"TY  - {type_tag}"]
    title = _get(rec, "title")
    if title:
        lines.append(f"TI  - {str(title).strip()}")
    for author in (_get(rec, "authors") or []):
        lines.append(f"AU  - {str(author).strip()}")
    year = _get(rec, "year")
    if year:
        lines.append(f"PY  - {year}")
    doi = _get(rec, "doi")
    if doi:
        lines.append(f"DO  - {str(doi).strip()}")
    url = _get(rec, "url") or _get(rec, "source_url")
    if url:
        lines.append(f"UR  - {str(url).strip()}")
    abstract = _get(rec, "abstract")
    if abstract:
        lines.append(f"AB  - {str(abstract).strip()}")
    lines.append("ER  - ")
    return "\n".join(lines)


def papers_to_ris(records: list[Any]) -> str:
    """Render a list of records as an RIS document."""
    return "\n\n".join(paper_to_ris(r) for r in records) + ("\n" if records else "")
