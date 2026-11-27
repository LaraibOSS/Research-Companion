"""Interoperability with the tools researchers already use.

Deterministic, LLM-free import/export between Research Companion's library and the
common bibliography formats:

- ``bibtex`` — export the library (or a draft's citations) to BibTeX, and parse
  ``.bib`` files (the format Zotero, Mendeley, and Overleaf export).
- ``ris`` — export to RIS (EndNote / Zotero / most reference managers).
- ``latex`` — read ``\\cite`` keys from a ``.tex`` draft and resolve them against a
  ``.bib`` file, so LaTeX-native drafts get citation coverage without a PDF.
- ``zotero`` — read a Zotero library through Zotero's local API (no account, no
  key, read-only) and add its items by arXiv id, DOI, the PDF Zotero holds, or
  metadata alone. Imported lazily: ``from research_companion.interop import zotero``.
"""
from research_companion.interop.bibtex import papers_to_bibtex, parse_bibtex
from research_companion.interop.latex import extract_cite_keys, resolve_tex_citations
from research_companion.interop.ris import papers_to_ris

__all__ = [
    "papers_to_bibtex",
    "parse_bibtex",
    "papers_to_ris",
    "extract_cite_keys",
    "resolve_tex_citations",
]
