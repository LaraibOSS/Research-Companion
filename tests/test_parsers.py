"""Tests for research_companion.parsers — pluggable parser layer + quality gate.

Fully testable without docling installed (default no-docling path).
"""
from __future__ import annotations

from research_companion.parsers import get_parser, text_quality
from research_companion.parsers.base import ParsedDoc

# A realistic paragraph: > 200 chars, overwhelmingly alphabetic.
_GOOD_PARAGRAPH = (
    "Attention mechanisms have become a central building block of modern neural "
    "network architectures. This paper studies how self attention scales with "
    "sequence length and proposes a sparse variant that keeps quality while "
    "reducing the quadratic cost of full attention over long documents."
)


# ---------------------------------------------------------------------------
# text_quality
# ---------------------------------------------------------------------------

class TestTextQuality:
    def test_empty_not_ok(self):
        q = text_quality("")
        assert q["ok"] is False
        assert q["char_count"] == 0

    def test_whitespace_only_not_ok(self):
        q = text_quality("   \n\n\t  ")
        assert q["ok"] is False
        assert q["char_count"] == 0

    def test_short_not_ok(self):
        q = text_quality("Introduction Methods Results.")
        assert q["ok"] is False

    def test_real_paragraph_ok(self):
        q = text_quality(_GOOD_PARAGRAPH)
        assert q["ok"] is True
        assert q["char_count"] >= 200
        assert q["alpha_ratio"] >= 0.5

    def test_mostly_symbols_not_ok(self):
        # Long enough by char count, but dominated by symbols/digits.
        symbols = "# $ % ^ & * ( ) 1 2 3 4 5 6 7 8 9 0 = + " * 12
        q = text_quality(symbols)
        assert len(symbols) >= 200
        assert q["alpha_ratio"] < 0.5
        assert q["ok"] is False


# ---------------------------------------------------------------------------
# get_parser selection
# ---------------------------------------------------------------------------

class TestGetParser:
    def test_default_selects_available_backend(self, monkeypatch):
        # No explicit name, no env override: docling if its package is importable
        # (Task 2 landed the backend module), else the pypdfium default.
        import importlib.util
        monkeypatch.delenv("RESEARCH_COMPANION_PARSER", raising=False)
        expected = "docling" if importlib.util.find_spec("docling") is not None else "pypdfium"
        assert get_parser().name == expected

    def test_env_override_pypdfium(self, monkeypatch):
        monkeypatch.setenv("RESEARCH_COMPANION_PARSER", "pypdfium")
        assert get_parser().name == "pypdfium"

    def test_docling_selected_when_backend_present(self, monkeypatch):
        # The Task-2 backend module is present; selecting docling returns it
        # (construction never imports docling itself, so this holds even if the
        # docling package is not installed).
        monkeypatch.setenv("RESEARCH_COMPANION_PARSER", "docling")
        assert get_parser("docling").name == "docling"

    def test_unknown_name_falls_back(self, monkeypatch):
        monkeypatch.delenv("RESEARCH_COMPANION_PARSER", raising=False)
        assert get_parser("totally-bogus").name == "pypdfium"

    def test_explicit_name_beats_env(self, monkeypatch):
        monkeypatch.setenv("RESEARCH_COMPANION_PARSER", "docling")
        assert get_parser("pypdfium").name == "pypdfium"


# ---------------------------------------------------------------------------
# PypdfiumParser.parse
# ---------------------------------------------------------------------------

class TestPypdfiumParse:
    def test_parse_extracts_text_from_real_pdf(self, tmp_path, fake_pdf_bytes):
        pdf = tmp_path / "p.pdf"
        pdf.write_bytes(fake_pdf_bytes)
        doc = get_parser("pypdfium").parse(pdf)
        assert isinstance(doc, ParsedDoc)
        assert "papergraph" in doc.text.lower()
        # pypdfium backend produces no structured output.
        assert doc.sections == []
        assert doc.tables == []
        assert doc.figures == []
