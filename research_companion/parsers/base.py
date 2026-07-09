"""Parser layer contracts: the ParsedDoc payload, the Parser protocol, and the
empty-text quality gate shared by the ingest pipeline.

Backends (pypdfium2 by default, docling later) return a ParsedDoc. Structured
fields (sections/tables/figures) may be empty for text-only backends.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

# Quality-gate thresholds. A scanned/image-only PDF extracts to "" (or a few
# stray glyphs), which must fail; a real paper page is hundreds of chars of
# mostly-alphabetic text.
MIN_CHARS = 200
MIN_ALPHA_RATIO = 0.5


@dataclass
class ParsedDoc:
    """Result of parsing a PDF. sections/tables/figures are empty for backends
    (like pypdfium2) that only recover flat text."""
    text: str
    sections: list[dict] = field(default_factory=list)
    tables: list[dict] = field(default_factory=list)
    figures: list[dict] = field(default_factory=list)
    meta: dict = field(default_factory=dict)


@runtime_checkable
class Parser(Protocol):
    name: str

    def parse(self, pdf_path: Path) -> ParsedDoc: ...


def text_quality(text: str) -> dict:
    """Cheap heuristic on extracted text. `ok` is True only when the text is
    long enough AND dominated by letters — so an empty/scanned or mostly-symbol
    extraction is reported as not ok."""
    text = text or ""
    char_count = len(text.strip())
    alpha = sum(1 for c in text if c.isalpha())
    alpha_ratio = (alpha / len(text)) if text else 0.0
    ok = char_count >= MIN_CHARS and alpha_ratio >= MIN_ALPHA_RATIO
    return {"char_count": char_count, "alpha_ratio": alpha_ratio, "ok": ok}
