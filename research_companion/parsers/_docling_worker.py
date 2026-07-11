"""Subprocess worker that runs a single Docling conversion in isolation.

Docling (RapidOCR / the torch stack) can crash NATIVELY — e.g. ``std::bad_alloc``
on a low-memory machine — which a Python ``try/except`` cannot catch; the crash
takes the whole process down (exit 139). Running the conversion here, in a child
process, means such a crash kills only this worker. The parent
(``extract._run_docling_subprocess``) sees the non-zero exit and falls back to
pypdfium, so the Lab server survives.

CLI:  python -m research_companion.parsers._docling_worker <pdf> <out.json> <ocr:0|1>

On success: writes ``{text, sections, tables, figures, meta}`` JSON to <out.json>
and exits 0. On any failure: non-zero exit (or a native crash → negative/abnormal
exit code), which the parent treats as a Docling failure.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        sys.stderr.write("usage: _docling_worker <pdf> <out.json> <ocr:0|1>\n")
        return 2
    pdf, out_path, ocr_flag = argv
    from research_companion.parsers.docling_parser import DoclingParser

    doc = DoclingParser(full_page_ocr=(ocr_flag == "1")).parse(Path(pdf))
    payload = {
        "text": doc.text,
        "sections": doc.sections,
        "tables": doc.tables,
        "figures": doc.figures,
        "meta": doc.meta,
    }
    Path(out_path).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
