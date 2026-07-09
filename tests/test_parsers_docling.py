"""Tests for the docling parser backend (research_companion.parsers.docling_parser).

The REQUIRED, always-run test is the fast MOCKED mapping test: it stubs the
DocumentConverter so we exercise the ParsedDoc mapping (text / sections / tables /
figures) without invoking real docling models. Tests that need the real docling
package are guarded with ``importorskip`` so CI without docling still passes; the
real-conversion test is additionally ``slow`` and skipped unless RC_DOCLING_SLOW
is set (docling downloads models on first convert()).
"""
from __future__ import annotations

import os
import subprocess
import sys
import types

import pytest

import research_companion.parsers.docling_parser as dp
from research_companion.parsers import get_parser
from research_companion.parsers.base import ParsedDoc
from research_companion.parsers.docling_parser import DoclingParser, ParserError

# ---------------------------------------------------------------------------
# Stub DoclingDocument + converter (no docling import needed)
# ---------------------------------------------------------------------------

class _StubHeading:
    def __init__(self, label, text, level=None):
        self.label = label
        self.text = text
        self.level = level


class _StubTable:
    def export_to_markdown(self, doc=None):
        return "| a | b |\n|---|---|\n| 1 | 2 |"

    def caption_text(self, doc):
        return "Table 1: main results"


class _StubPicture:
    def caption_text(self, doc):
        return "Figure 1: system overview"


_MARKDOWN = (
    "# Introduction\n\n"
    "We study attention mechanisms in modern neural network architectures and "
    "how self attention scales with the length of very long input documents.\n\n"
    "## Background\n\n"
    "Prior work established the transformer architecture and characterised its "
    "quadratic cost, motivating a range of sparse and linear approximations.\n\n"
    "# Results\n\n"
    "Our sparse variant preserves answer quality while substantially reducing "
    "the compute required for full attention over long clinical documents.\n"
)


class _StubDoc:
    def export_to_markdown(self):
        return _MARKDOWN

    texts = [
        _StubHeading("section_header", "Introduction", 1),
        _StubHeading("section_header", "Background", 2),
        _StubHeading("section_header", "Results", 1),
    ]
    tables = [_StubTable()]
    pictures = [_StubPicture()]


class _StubConverter:
    def __init__(self, doc):
        self._doc = doc

    def convert(self, source):
        class _Result:
            document = self._doc
        return _Result()


# ---------------------------------------------------------------------------
# Fast MOCKED mapping test (required, always runs — no docling needed)
# ---------------------------------------------------------------------------

class TestDoclingMappingMocked:
    def test_parse_maps_text_sections_tables_figures(self, tmp_path, monkeypatch):
        monkeypatch.setattr(dp, "_get_converter", lambda: _StubConverter(_StubDoc()))

        pdf = tmp_path / "p.pdf"
        pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")

        doc = DoclingParser().parse(pdf)

        assert isinstance(doc, ParsedDoc)
        # Text: clean prose, quality gate passes, no markdown '#' image noise leaked.
        from research_companion.parsers import text_quality
        assert text_quality(doc.text)["ok"] is True
        assert "attention" in doc.text.lower()

        # Sections mapped to the internal Section dict shape.
        assert len(doc.sections) == 3
        s1, s11, s2 = doc.sections
        assert s1["section_id"] == "s1" and s1["level"] == 1 and s1["parent"] is None
        assert s1["char_start"] == 0  # preamble absorbed into the first section
        assert s11["level"] == 2 and s11["parent"] == "s1"
        assert s2["section_id"] == "s2" and s2["level"] == 1
        # Offsets are valid and non-empty, and tile in order.
        for s in doc.sections:
            assert 0 <= s["char_start"] < s["char_end"] <= len(doc.text)
            assert doc.text[s["char_start"]:s["char_end"]].strip()
        assert {s["title"] for s in doc.sections} == {"Introduction", "Background", "Results"}

        # Tables + figures best-effort.
        assert doc.tables and doc.tables[0]["caption"] == "Table 1: main results"
        assert "| a | b |" in doc.tables[0]["markdown"]
        assert doc.figures == [{"caption": "Figure 1: system overview"}]

    def test_parse_wraps_converter_errors(self, tmp_path, monkeypatch):
        class _Boom:
            def convert(self, source):
                raise RuntimeError("model load failed")

        monkeypatch.setattr(dp, "_get_converter", lambda: _Boom())
        pdf = tmp_path / "p.pdf"
        pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")

        with pytest.raises(ParserError, match="docling failed to convert"):
            DoclingParser().parse(pdf)

    def test_sections_empty_on_unmappable_document(self, tmp_path, monkeypatch):
        class _NoHeadings:
            def export_to_markdown(self):
                return "Body text with no headings at all, just a plain paragraph here."
            texts = []
        monkeypatch.setattr(dp, "_get_converter", lambda: _StubConverter(_NoHeadings()))
        pdf = tmp_path / "p.pdf"
        pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")

        doc = DoclingParser().parse(pdf)
        assert doc.sections == []  # -> heuristic sectioner runs downstream


# ---------------------------------------------------------------------------
# Forced full-page OCR converter + DoclingParser(full_page_ocr=True)
# ---------------------------------------------------------------------------

class TestForcedOcrConverter:
    def test_name_and_default(self):
        assert DoclingParser().name == "docling"
        assert DoclingParser().full_page_ocr is False
        p = DoclingParser(full_page_ocr=True)
        assert p.name == "docling+ocr"
        assert p.full_page_ocr is True

    def test_parse_routes_to_ocr_converter(self, tmp_path, monkeypatch):
        """full_page_ocr=True must use the FORCED-OCR converter, not the default."""
        called = {"default": 0, "ocr": 0}
        monkeypatch.setattr(dp, "_get_converter",
                            lambda: called.__setitem__("default", called["default"] + 1) or _StubConverter(_StubDoc()))
        monkeypatch.setattr(dp, "_get_ocr_converter",
                            lambda: called.__setitem__("ocr", called["ocr"] + 1) or _StubConverter(_StubDoc()))
        pdf = tmp_path / "p.pdf"
        pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")

        DoclingParser(full_page_ocr=True).parse(pdf)
        assert called == {"default": 0, "ocr": 1}

        called["ocr"] = 0
        DoclingParser().parse(pdf)  # default routes to the normal converter
        assert called == {"default": 1, "ocr": 0}

    def test_ocr_converter_configures_force_full_page_ocr(self, monkeypatch):
        """_get_ocr_converter builds the DocumentConverter with a PDF pipeline whose
        do_ocr and ocr_options.force_full_page_ocr are True. Docling modules are
        FAKED via sys.modules so no real docling/torch import or convert happens."""
        captured = {}

        class _FakeOcrOptions:
            def __init__(self):
                self.force_full_page_ocr = False

        class _FakePipelineOptions:
            def __init__(self):
                self.do_ocr = False
                self.ocr_options = _FakeOcrOptions()

        class _FakeInputFormat:
            PDF = "PDF"

        class _FakeFormatOption:
            def __init__(self, pipeline_options=None):
                self.pipeline_options = pipeline_options

        class _FakeConverter:
            def __init__(self, format_options=None):
                captured["format_options"] = format_options

        pipe_mod = types.ModuleType("docling.datamodel.pipeline_options")
        pipe_mod.PdfPipelineOptions = _FakePipelineOptions
        base_mod = types.ModuleType("docling.datamodel.base_models")
        base_mod.InputFormat = _FakeInputFormat
        conv_mod = types.ModuleType("docling.document_converter")
        conv_mod.DocumentConverter = _FakeConverter
        conv_mod.PdfFormatOption = _FakeFormatOption

        for name, mod in {
            "docling": types.ModuleType("docling"),
            "docling.datamodel": types.ModuleType("docling.datamodel"),
            "docling.datamodel.pipeline_options": pipe_mod,
            "docling.datamodel.base_models": base_mod,
            "docling.document_converter": conv_mod,
        }.items():
            monkeypatch.setitem(sys.modules, name, mod)

        monkeypatch.setattr(dp, "_OCR_CONVERTER", None)
        dp._get_ocr_converter()

        fmt = captured["format_options"]
        opts = fmt[_FakeInputFormat.PDF].pipeline_options
        assert opts.do_ocr is True
        assert opts.ocr_options.force_full_page_ocr is True


# ---------------------------------------------------------------------------
# extract.ocr_fallback_parse — the pipeline OCR-fallback seam (mocked)
# ---------------------------------------------------------------------------

class TestOcrFallbackParse:
    def test_returns_none_when_docling_absent(self, monkeypatch):
        import importlib.util as u

        from research_companion import extract

        real = u.find_spec
        monkeypatch.setattr(
            u, "find_spec",
            lambda name, *a, **k: None if name == "docling" else real(name, *a, **k),
        )
        assert extract.ocr_fallback_parse(types.SimpleNamespace(paper_id="local:x")) is None

    def test_parses_with_forced_ocr_when_docling_present(self, monkeypatch, tmp_path):
        import importlib.util as u

        from research_companion import extract
        from research_companion.parsers import ParsedDoc

        real = u.find_spec
        monkeypatch.setattr(
            u, "find_spec",
            lambda name, *a, **k: object() if name == "docling" else real(name, *a, **k),
        )

        captured = {}

        class _StubParser:
            def __init__(self, full_page_ocr=False):
                captured["full_page_ocr"] = full_page_ocr

            def parse(self, path):
                captured["path"] = path
                return ParsedDoc(text="recovered text from forced OCR")

        monkeypatch.setattr(dp, "DoclingParser", _StubParser)

        pdf = tmp_path / "p.pdf"
        pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
        monkeypatch.setattr(extract, "pdf_path", lambda pid: pdf)
        saved = {}
        monkeypatch.setattr(extract, "save_text", lambda pid, text: saved.update(pid=pid, text=text))

        doc = extract.ocr_fallback_parse(types.SimpleNamespace(paper_id="local:x"))
        assert captured["full_page_ocr"] is True          # forced full-page OCR
        assert doc.text == "recovered text from forced OCR"
        assert saved["text"] == "recovered text from forced OCR"  # persisted


# ---------------------------------------------------------------------------
# Lazy-import guarantee (always runs)
# ---------------------------------------------------------------------------

class TestLazyImport:
    def test_importing_parsers_does_not_pull_docling_or_torch(self):
        """Importing the parsers package (and the docling backend module) must not
        import docling/torch — those load only inside parse()."""
        code = (
            "import sys\n"
            "import research_companion.parsers\n"
            "import research_companion.parsers.docling_parser\n"
            "assert 'docling' not in sys.modules, 'docling imported at module load'\n"
            "assert 'torch' not in sys.modules, 'torch imported at module load'\n"
            "print('ok')\n"
        )
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True,
        )
        assert proc.returncode == 0, proc.stderr
        assert "ok" in proc.stdout


# ---------------------------------------------------------------------------
# Auto-selection (needs docling installed)
# ---------------------------------------------------------------------------

class TestSelection:
    def test_get_parser_auto_selects_docling(self, monkeypatch):
        pytest.importorskip("docling")
        monkeypatch.delenv("RESEARCH_COMPANION_PARSER", raising=False)
        assert get_parser().name == "docling"


# ---------------------------------------------------------------------------
# Real conversion (slow: downloads models; skipped unless RC_DOCLING_SLOW set)
# ---------------------------------------------------------------------------

@pytest.mark.slow
@pytest.mark.skipif(
    not os.environ.get("RC_DOCLING_SLOW"),
    reason="real docling conversion is slow / downloads models; set RC_DOCLING_SLOW=1 to run",
)
def test_parse_real_pdf(tmp_path, fake_pdf_bytes):
    pytest.importorskip("docling")
    # Reset the module-level converter singleton so this uses a real converter.
    dp._CONVERTER = None
    pdf = tmp_path / "p.pdf"
    pdf.write_bytes(fake_pdf_bytes)

    doc = DoclingParser().parse(pdf)
    assert isinstance(doc, ParsedDoc)
    assert isinstance(doc.text, str)
    assert isinstance(doc.sections, list)
