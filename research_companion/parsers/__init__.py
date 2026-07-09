"""Pluggable PDF parser layer.

Selection order (get_parser): explicit name -> RESEARCH_COMPANION_PARSER env ->
"docling" if the docling package is importable -> else "pypdfium". docling is
resolved LAZILY and its backend module (parsers/docling_parser.py, added by a
later task) is imported only when present; if it is absent we fall back to the
pypdfium2 default. This module never imports docling itself.
"""
from __future__ import annotations

import importlib.util
import os

from research_companion.parsers.base import (
    MIN_ALPHA_RATIO,
    MIN_CHARS,
    ParsedDoc,
    Parser,
    text_quality,
)
from research_companion.parsers.docling_parser import ParserError
from research_companion.parsers.pypdfium import PypdfiumParser

__all__ = [
    "MIN_ALPHA_RATIO",
    "MIN_CHARS",
    "ParsedDoc",
    "Parser",
    "ParserError",
    "PypdfiumParser",
    "get_parser",
    "text_quality",
]

_ENV_VAR = "RESEARCH_COMPANION_PARSER"
_DOCLING_BACKEND = "research_companion.parsers.docling_parser"


def _docling_available() -> bool:
    return importlib.util.find_spec("docling") is not None


def get_parser(name: str | None = None) -> Parser:
    """Return a Parser. See module docstring for the resolution order."""
    resolved = name or os.environ.get(_ENV_VAR) or (
        "docling" if _docling_available() else "pypdfium"
    )

    if resolved == "docling":
        # Seam for the future docling backend: use it only if its module exists.
        if importlib.util.find_spec(_DOCLING_BACKEND) is not None:
            from research_companion.parsers.docling_parser import DoclingParser
            return DoclingParser()
        # Backend not implemented yet -> honest fallback to the default.
        return PypdfiumParser()

    # "pypdfium" and any unknown name -> the permissive default.
    return PypdfiumParser()
