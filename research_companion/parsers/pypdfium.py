"""Default text-only parser backed by pypdfium2 (permissive, no OCR).

Better layout fidelity than pypdf; still returns "" for scanned/image PDFs,
which the ingest quality gate turns into an honest failure.
"""
from __future__ import annotations

import re
from pathlib import Path

from research_companion.parsers.base import ParsedDoc


class PypdfiumParser:
    name = "pypdfium"

    def parse(self, pdf_path: Path) -> ParsedDoc:
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(str(pdf_path))
        parts: list[str] = []
        try:
            for page in pdf:
                try:
                    textpage = page.get_textpage()
                    parts.append(textpage.get_text_range() or "")
                except Exception:
                    continue
        finally:
            pdf.close()

        text = "\n\n".join(p for p in parts if p.strip())
        # Same whitespace normalization as the legacy pdf_to_text.
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return ParsedDoc(text=text.strip())
