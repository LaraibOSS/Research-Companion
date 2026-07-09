"""Docling parser backend: layout-aware text, reading order (fixes multi-column),
real sections, tables, figures/captions, and OCR for scanned PDFs.

Optional and auto-selected when the ``docling`` package is importable (the
parsers selector prefers "docling"). ``docling`` (and the torch stack it pulls)
is imported LAZILY inside :meth:`DoclingParser.parse` and :func:`_get_converter`,
so importing this module — or the parsers package — never pulls torch.
"""
from __future__ import annotations

import re
from pathlib import Path

from research_companion.parsers.base import ParsedDoc


class ParserError(RuntimeError):
    """Raised when the docling backend fails to convert a PDF.

    The ingest gate treats this like any parse failure (records it, moves on).
    """


# Module-level lazy singletons: docling's DocumentConverter is expensive to build
# (loads models), so we construct each variant once and reuse it across papers.
# _CONVERTER is the normal (default-OCR) converter; _OCR_CONVERTER is a separate
# converter configured for FORCED full-page OCR (used only as a fallback for
# scanned/image-only PDFs whose normal extraction yields no usable text — it is
# slow, so digital PDFs never touch it). The underlying models are shared.
_CONVERTER = None
_OCR_CONVERTER = None


def _get_converter():
    """Return the shared default DocumentConverter, importing docling on first use."""
    global _CONVERTER
    if _CONVERTER is None:
        from docling.document_converter import DocumentConverter
        _CONVERTER = DocumentConverter()
    return _CONVERTER


def _get_ocr_converter():
    """Return the shared forced-full-page-OCR DocumentConverter (lazy singleton).

    Built with ``PdfPipelineOptions(do_ocr=True, ocr_options.force_full_page_ocr=
    True)`` — the only configuration empirically shown to recover text from the
    user's image-only scanned PDFs (docling's default region-based OCR returns
    nothing on them). Slow (~minutes/paper), so this is a fallback path only.
    """
    global _OCR_CONVERTER
    if _OCR_CONVERTER is None:
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption
        opts = PdfPipelineOptions()
        opts.do_ocr = True
        opts.ocr_options.force_full_page_ocr = True
        _OCR_CONVERTER = DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
        )
    return _OCR_CONVERTER


# Markdown image syntax + docling's HTML image placeholders — stripped so the
# extracted prose is clean (matches the pypdfium path's text-only philosophy).
_IMG_MD_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_IMG_HTML_RE = re.compile(r"<!--\s*image\s*-->", re.IGNORECASE)


def _normalize(text: str) -> str:
    """Strip images and normalize whitespace like the pypdfium path."""
    text = text or ""
    text = _IMG_MD_RE.sub("", text)
    text = _IMG_HTML_RE.sub("", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _export_text(doc) -> str:
    """Export clean prose from a DoclingDocument.

    Prefers markdown (preserves headings + reading order); falls back to the
    plain-text export.
    """
    for meth in ("export_to_markdown", "export_to_text"):
        fn = getattr(doc, meth, None)
        if callable(fn):
            try:
                out = fn()
            except Exception:
                continue
            if isinstance(out, str) and out.strip():
                return out
    return ""


def _is_heading(label: str) -> bool:
    return "section_header" in label or "title" in label


def _extract_sections(doc, text: str) -> list[dict]:
    """Derive sections from docling's document structure, mapped to the internal
    Section dict shape ({section_id, title, level, parent, char_start, char_end}).

    Headings are located in ``text`` (by their verbatim string) to compute
    offsets; level-1 sections tile the text with the preamble absorbed into the
    first section, mirroring the heuristic sectioner. Robust: returns [] on any
    failure so the heuristic sectioner still runs downstream.
    """
    try:
        # Collect (title, level) in document (reading) order.
        raw: list[tuple[str, int]] = []
        for item in getattr(doc, "texts", []) or []:
            label = str(getattr(item, "label", "")).lower()
            if not _is_heading(label):
                continue
            title = (getattr(item, "text", "") or "").strip()
            if not title:
                continue
            # A document TITLE is level 1; section headers may carry a level.
            if "title" in label and "section" not in label:
                level = 1
            else:
                try:
                    level = int(getattr(item, "level", 1) or 1)
                except (TypeError, ValueError):
                    level = 1
            level = max(1, min(2, level))
            raw.append((title, level))

        # Locate each heading in the exported text, advancing a cursor so
        # repeated titles resolve to distinct positions in document order.
        located: list[tuple[int, str, int]] = []
        cursor = 0
        for title, level in raw:
            idx = text.find(title, cursor)
            if idx == -1:
                idx = text.find(title)
            if idx == -1:
                continue
            located.append((idx, title, level))
            cursor = idx + len(title)

        if not located:
            return []
        located.sort(key=lambda t: t[0])

        sections: list[dict] = []
        l1 = 0
        l2_by_parent: dict[str, int] = {}
        current_l1: str | None = None
        for i, (start, title, level) in enumerate(located):
            end = located[i + 1][0] if i + 1 < len(located) else len(text)
            if level == 1:
                l1 += 1
                sid = f"s{l1}"
                current_l1 = sid
                parent = None
            else:
                parent = current_l1
                key = parent or "_root"
                l2_by_parent[key] = l2_by_parent.get(key, 0) + 1
                sid = f"{parent}.{l2_by_parent[key]}" if parent else f"s0.{l2_by_parent[key]}"
            sections.append({
                "section_id": sid,
                "title": title,
                "level": level,
                "parent": parent,
                "char_start": start,
                "char_end": end,
            })

        # Absorb any preamble before the first heading into the first section so
        # level-1 sections tile the whole text from offset 0.
        if sections and sections[0]["char_start"] > 0:
            sections[0]["char_start"] = 0
        return sections
    except Exception:
        return []


def _caption(item, doc) -> str | None:
    """Best-effort caption text for a docling table/figure item."""
    fn = getattr(item, "caption_text", None)
    if callable(fn):
        try:
            c = fn(doc)
        except Exception:
            c = None
        if isinstance(c, str) and c.strip():
            return c.strip()
    c = getattr(item, "caption", None)
    if isinstance(c, str) and c.strip():
        return c.strip()
    return None


def _table_markdown(item, doc) -> str | None:
    fn = getattr(item, "export_to_markdown", None)
    if not callable(fn):
        return None
    # docling's TableItem.export_to_markdown signature varies by version
    # (some require the doc, some take no args) — try both.
    for args in ((doc,), ()):
        try:
            md = fn(*args)
        except TypeError:
            continue
        except Exception:
            return None
        if isinstance(md, str) and md.strip():
            return md.strip()
    return None


def _extract_tables(doc) -> list[dict]:
    out: list[dict] = []
    try:
        for t in getattr(doc, "tables", []) or []:
            entry: dict = {}
            md = _table_markdown(t, doc)
            if md:
                entry["markdown"] = md
            cap = _caption(t, doc)
            if cap:
                entry["caption"] = cap
            if entry:
                out.append(entry)
    except Exception:
        return []
    return out


def _extract_figures(doc) -> list[dict]:
    out: list[dict] = []
    try:
        for p in getattr(doc, "pictures", []) or []:
            out.append({"caption": _caption(p, doc) or ""})
    except Exception:
        return []
    return out


def _extract_meta(doc) -> dict:
    try:
        for item in getattr(doc, "texts", []) or []:
            label = str(getattr(item, "label", "")).lower()
            if "title" in label and "section" not in label:
                title = (getattr(item, "text", "") or "").strip()
                if title:
                    return {"title": title}
    except Exception:
        pass
    return {}


class DoclingParser:
    def __init__(self, full_page_ocr: bool = False):
        # full_page_ocr selects the forced full-page OCR converter (fallback for
        # scanned PDFs). Default stays the fast, layout-aware normal converter.
        self.full_page_ocr = full_page_ocr
        self.name = "docling+ocr" if full_page_ocr else "docling"

    def parse(self, pdf_path: Path) -> ParsedDoc:
        try:
            converter = _get_ocr_converter() if self.full_page_ocr else _get_converter()
            result = converter.convert(str(pdf_path))
            doc = result.document
        except Exception as exc:  # docling runtime / model error -> clear parse failure
            raise ParserError(f"docling failed to convert {pdf_path}: {exc}") from exc

        text = _normalize(_export_text(doc))
        return ParsedDoc(
            text=text,
            sections=_extract_sections(doc, text),
            tables=_extract_tables(doc),
            figures=_extract_figures(doc),
            meta=_extract_meta(doc),
        )
