"""Generate tests/fixtures/sample_paper.pdf — a small, digital, text-layer
mini research paper used by tests/test_ingestion_e2e.py to exercise the REAL
offline ingestion pipeline (no mocks).

Re-runnable from anywhere: the output path is derived from __file__.

Usage:
    python tests/fixtures/make_sample_paper.py
"""
from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas

FIXTURES_DIR = Path(__file__).parent
OUTPUT_PDF = FIXTURES_DIR / "sample_paper.pdf"

# Each entry is a "paragraph": a list of plain lines to be drawn one after
# another. Keeping layout dead simple (single column, default Helvetica,
# one drawString call per line) means pypdfium extracts clean, predictable
# text with minimal reflow surprises.
TITLE = "Structured Retrieval for Verifiable Scientific Question Answering"

ABSTRACT_HEADING = "Abstract"
ABSTRACT_BODY = [
    "This paper presents a pipeline for grounded question answering over",
    "scientific literature. We combine a heuristic section tree with a",
    "BM25 retrieval layer over a knowledge graph of extracted claims, and",
    "show that the resulting citations remain verifiable against source text.",
]

SECTIONS = [
    (
        "1. Introduction",
        [
            "Scientific papers are long and unevenly structured, which makes",
            "locating the right evidence for a claim difficult for both humans",
            "and automated systems. We study how a lightweight, fully offline",
            "pipeline can turn a raw PDF into retrievable, provenance-tracked units.",
        ],
    ),
    (
        "2. Methods",
        [
            "Our system builds a knowledge graph from parsed sections and ranks",
            "candidate passages with BM25, a classical sparse ranking method that",
            "requires no network access or embedding model. Each retrieval unit",
            "records its exact character offsets so every ranked result can be",
            "traced back to the original document text.",
        ],
    ),
    (
        "3. Results",
        [
            "We evaluate the pipeline on a multi-hop question answering benchmark",
            "we call SciQA-Mini, a small curated set of research questions that",
            "each require combining evidence from two or more sections. The",
            "sparse retrieval layer alone recovers the correct section for the",
            "large majority of SciQA-Mini questions without any learned ranker.",
        ],
    ),
    (
        "4. Conclusion",
        [
            "Grounding answers in verifiable citations keeps the system honest:",
            "every claim can be traced to a specific passage in the source PDF.",
            "We argue that this offline-first design is a practical baseline for",
            "research assistants that must work without external services.",
        ],
    ),
]

REFERENCES_HEADING = "References"
REFERENCES_BODY = [
    "[1] A. Researcher and B. Scholar. Sparse and Structured Retrieval for",
    "    Scientific Papers. Journal of Made-Up Studies, 2026.",
]


def build_pdf(output_path: Path) -> None:
    c = canvas.Canvas(str(output_path), pagesize=LETTER)
    width, height = LETTER
    left_margin = 72
    top = height - 72
    line_height = 16
    y = top

    def draw_line(text: str, *, font: str = "Helvetica", size: int = 11) -> None:
        nonlocal y
        if y < 72:
            c.showPage()
            y = top
        c.setFont(font, size)
        c.drawString(left_margin, y, text)
        y -= line_height

    def blank_line() -> None:
        nonlocal y
        y -= line_height * 0.5

    # Title
    draw_line(TITLE, font="Helvetica-Bold", size=14)
    blank_line()

    # Abstract
    draw_line(ABSTRACT_HEADING, font="Helvetica-Bold", size=12)
    for line in ABSTRACT_BODY:
        draw_line(line)
    blank_line()

    # Numbered sections
    for heading, body_lines in SECTIONS:
        draw_line(heading, font="Helvetica-Bold", size=12)
        for line in body_lines:
            draw_line(line)
        blank_line()

    # References
    draw_line(REFERENCES_HEADING, font="Helvetica-Bold", size=12)
    for line in REFERENCES_BODY:
        draw_line(line)

    c.showPage()
    c.save()


if __name__ == "__main__":
    build_pdf(OUTPUT_PDF)
    size = OUTPUT_PDF.stat().st_size
    print(f"Wrote {OUTPUT_PDF} ({size} bytes)")
