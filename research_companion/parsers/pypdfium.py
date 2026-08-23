"""Default text-only parser backed by pypdfium2 (permissive, no OCR).

Better layout fidelity than pypdf; still returns "" for scanned/image PDFs,
which the ingest quality gate turns into an honest failure.

This is also the FALLBACK when docling fails, so its own failure modes matter
more than they look: if it aborts, the user sees pypdfium's error and never
learns why docling failed. It is therefore written to salvage what it can and
to report a page it could not read rather than losing the document over it.
"""
from __future__ import annotations

import contextlib
import re
from pathlib import Path

from research_companion.parsers.base import ParsedDoc


class PypdfiumParser:
    name = "pypdfium"

    def parse(self, pdf_path: Path) -> ParsedDoc:
        import pypdfium2 as pdfium

        try:
            pdf = pdfium.PdfDocument(str(pdf_path))
        except Exception as exc:  # noqa: BLE001
            # Only here does "the file is unreadable" actually mean that.
            raise ValueError(
                f"pypdfium could not open {pdf_path.name}: {exc}"
            ) from exc

        parts: list[str] = []
        failed_pages = 0
        try:
            # Index rather than iterate: iterating raises "Failed to load page"
            # from inside the generator, which aborts the whole document. One
            # unreadable page in a forty-page paper should cost that page, not
            # the paper -- and under memory pressure the late pages are exactly
            # the ones that fail.
            try:
                n_pages = len(pdf)
            except Exception:  # noqa: BLE001
                n_pages = 0
            for i in range(n_pages):
                try:
                    page = pdf[i]
                    textpage = page.get_textpage()
                    parts.append(textpage.get_text_range() or "")
                except Exception:  # noqa: BLE001 - a bad page is not a bad file
                    failed_pages += 1
                    continue
        finally:
            with contextlib.suppress(Exception):
                pdf.close()

        text = "\n\n".join(p for p in parts if p.strip())
        # Same whitespace normalization as the legacy pdf_to_text.
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return ParsedDoc(
            text=text.strip(),
            meta={"pages": n_pages, "unreadable_pages": failed_pages} if failed_pages else {},
        )
