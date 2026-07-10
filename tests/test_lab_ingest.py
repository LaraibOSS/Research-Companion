"""Tests for research_companion.lab — folder ingestion pipeline (Task 8).

All pipeline seams are injected; no real LLM or PDF extraction is performed.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from research_companion.agents.bus import Bus
from research_companion.agents.events import (
    AlignmentReady,
    EmbeddingsReady,
    GraphDelta,
    IngestFailed,
    IngestProgress,
    IngestSkipped,
    JobDone,
    PaperAdded,
    SectionExtracted,
    SectionTreeBuilt,
    StrengthUpdated,
    SuggestionsUpdated,
    event_to_dict,
)
from research_companion.lab import IngestResult, ingest_folder, scan_pdfs
from research_companion.store import PaperMetadata

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

# A realistic paper body (>200 chars, mostly letters) that passes the ingest
# text-quality gate. Tiny stubs would now be rejected as scanned/empty.
_GOOD_TEXT = (
    "Introduction. This paper studies graph based retrieval augmented generation. "
    "Methods. We build a knowledge graph over the corpus and rank sections with BM25. "
    "Results. The approach improves multi hop question answering over strong baselines. "
    "Conclusion. Structured retrieval yields more grounded and verifiable answers."
)


def _make_pdf(tmp_path: Path, name: str) -> Path:
    """Write a minimal valid PDF file and return its path."""
    pdf = tmp_path / name
    pdf.write_bytes(
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R>>endobj\n"
        b"4 0 obj<</Length 44>>stream\n"
        b"BT /F1 12 Tf 50 750 Td (Hello papergraph) Tj ET\n"
        b"endstream endobj\n"
        b"xref\n0 5\n0000000000 65535 f\n0000000009 00000 n\n0000000058 00000 n\n"
        b"0000000109 00000 n\n0000000189 00000 n\n"
        b"trailer<</Size 5/Root 1 0 R>>\n"
        b"startxref\n279\n%%EOF\n"
    )
    return pdf


def _make_meta(paper_id: str, title: str = "Test Paper") -> PaperMetadata:
    return PaperMetadata(
        paper_id=paper_id,
        title=title,
        authors=["Author"],
        year=2025,
        abstract="",
        source_url="",
        added_at="2025-01-01T00:00:00",
    )


def _fake_section(section_id: str = "s1", title: str = "Introduction"):
    """Return a minimal Section-like object (uses sections.Section dataclass)."""
    from research_companion.sections import Section
    return Section(
        section_id=section_id,
        title=title,
        level=1,
        parent=None,
        char_start=0,
        char_end=100,
    )


def _make_fakes(paper_ids: list[str], extraction: dict | None = None):
    """Return fake seam callables for the given list of paper IDs (in order).

    The fake add_pdf saves metadata and a stub text.txt to the store so that
    get_paper_text() (called in stage 2) doesn't fail.
    """
    from research_companion import store as _store

    _ids = list(paper_ids)
    _idx = [0]

    def fake_add_pdf(path):
        idx = _idx[0]
        _idx[0] += 1
        pid = _ids[idx] if idx < len(_ids) else f"local:fake{idx}"
        meta = _make_meta(pid, title=f"Paper {idx+1}")
        meta.save()
        # Save stub text so get_paper_text() works without a real PDF
        _store.save_text(pid, f"{_GOOD_TEXT} Paper {pid}.")
        return meta

    def fake_sectioner(paper_id, **kwargs):
        return [_fake_section("s1", "Introduction"), _fake_section("s2", "Methods")]

    _ext = extraction or {
        "concepts": [{"name": "Test Concept", "section": "s1"}],
        "methods": [{"name": "Test Method", "section": "s2"}],
        "datasets": [],
        "claims": [],
        "results": [],
        "related_work": [],
    }

    def fake_extractor(meta, *, provider="anthropic", model=None, force=False):
        return _ext, {"input_tokens": 10, "output_tokens": 5, "cached": False}

    def fake_aligner(draft_id, candidate_id, *, llm, force=False, persist=None):
        return {"verdict": "medium", "score": 0.5, "band": 0.1}

    def fake_strengther(paper_id, **kwargs):
        return {"score": 0.7, "band": "strong", "color": "#3fb950"}

    return fake_add_pdf, fake_sectioner, fake_extractor, fake_aligner, fake_strengther


# ---------------------------------------------------------------------------
# scan_pdfs tests
# ---------------------------------------------------------------------------

class TestScanPdfs:
    def test_sorted_recursive_discovery(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        p1 = _make_pdf(tmp_path, "a.pdf")
        p2 = _make_pdf(sub, "b.pdf")
        p3 = _make_pdf(tmp_path, "c.pdf")
        found = scan_pdfs(tmp_path)
        assert found == sorted([p1, p2, p3])

    def test_empty_folder(self, tmp_path):
        found = scan_pdfs(tmp_path)
        assert found == []

    def test_missing_folder_raises(self, tmp_path):
        with pytest.raises(ValueError, match="does not exist"):
            scan_pdfs(tmp_path / "nonexistent")

    def test_file_not_dir_raises(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("hello")
        with pytest.raises(ValueError, match="not a directory"):
            scan_pdfs(f)

    def test_only_pdfs_returned(self, tmp_path):
        p = _make_pdf(tmp_path, "real.pdf")
        (tmp_path / "other.txt").write_text("text")
        (tmp_path / "doc.docx").write_bytes(b"docx")
        found = scan_pdfs(tmp_path)
        assert found == [p]


# ---------------------------------------------------------------------------
# Happy path — 2 papers
# ---------------------------------------------------------------------------

class TestHappyPath:
    def test_two_papers_event_order(self, tmp_path, isolated_papergraph_dir):
        """Event order: progress, paper_added, section_tree_built, section_extracted...,
        graph_delta, strength_updated, ..., job_done."""
        _make_pdf(tmp_path, "p1.pdf")
        _make_pdf(tmp_path, "p2.pdf")

        add, sect, ext, align, strength = _make_fakes(["local:aaa", "local:bbb"])
        bus = Bus()

        asyncio.run(
            ingest_folder(
                tmp_path,
                bus=bus,
                add_pdf=add,
                extractor=ext,
                sectioner=sect,
                aligner=None,     # skip alignment in this test
                strengther=strength,
                align=True,
            )
        )

        kinds = [type(e).__name__ for e in bus.history]

        # Must start with IngestProgress and end with JobDone
        assert kinds[0] == "IngestProgress"
        assert kinds[-1] == "JobDone"

        # Must have PaperAdded for each paper
        assert kinds.count("PaperAdded") == 2

        # Must have SectionTreeBuilt for each paper
        assert kinds.count("SectionTreeBuilt") == 2

        # Must have at least one SectionExtracted
        assert "SectionExtracted" in kinds

        # Must have GraphDelta for each paper
        assert kinds.count("GraphDelta") == 2

        # Must have StrengthUpdated for each paper
        assert kinds.count("StrengthUpdated") == 2

        # JobDone must be last
        assert isinstance(bus.history[-1], JobDone)
        assert bus.history[-1].job == "ingest"

        # PaperAdded from a folder ingest carries the ingested file's path
        added_events = [e for e in bus.history if isinstance(e, PaperAdded)]
        assert len(added_events) == 2
        added_paths = {e.path for e in added_events}
        assert added_paths == {str(tmp_path / "p1.pdf"), str(tmp_path / "p2.pdf")}
        for e in added_events:
            assert e.path != ""

    def test_two_papers_ingest_result_counts(self, tmp_path, isolated_papergraph_dir):
        _make_pdf(tmp_path, "p1.pdf")
        _make_pdf(tmp_path, "p2.pdf")

        add, sect, ext, align, strength = _make_fakes(["local:aaa", "local:bbb"])
        bus = Bus()

        result = asyncio.run(
            ingest_folder(
                tmp_path,
                bus=bus,
                add_pdf=add,
                extractor=ext,
                sectioner=sect,
                aligner=None,
                strengther=None,
            )
        )

        assert len(result.added) == 2
        assert len(result.skipped) == 0
        assert len(result.failed) == 0

    def test_progress_before_each_file(self, tmp_path, isolated_papergraph_dir):
        _make_pdf(tmp_path, "p1.pdf")
        _make_pdf(tmp_path, "p2.pdf")

        add, sect, ext, _, _ = _make_fakes(["local:aaa", "local:bbb"])
        bus = Bus()

        asyncio.run(
            ingest_folder(
                tmp_path,
                bus=bus,
                add_pdf=add,
                extractor=ext,
                sectioner=sect,
                aligner=None,
                strengther=None,
            )
        )

        progress_events = [e for e in bus.history if isinstance(e, IngestProgress)]
        # At least one per file + final
        assert len(progress_events) >= 3

    def test_paths_param_ingests_only_the_given_subset(self, tmp_path, isolated_papergraph_dir):
        """When paths= is given, ingest exactly those files, even if the folder
        contains more PDFs (e.g. a caller-selected subset)."""
        p1 = _make_pdf(tmp_path, "p1.pdf")
        p2 = _make_pdf(tmp_path, "p2.pdf")
        _make_pdf(tmp_path, "p3.pdf")  # present in folder, but not selected

        add, sect, ext, _, _ = _make_fakes(["local:aaa", "local:bbb"])
        bus = Bus()

        result = asyncio.run(
            ingest_folder(
                tmp_path,
                paths=[p1, p2],
                bus=bus,
                add_pdf=add,
                extractor=ext,
                sectioner=sect,
                aligner=None,
                strengther=None,
            )
        )

        assert len(result.added) == 2

        progress_events = [e for e in bus.history if isinstance(e, IngestProgress)]
        assert progress_events[0].total == 2

        added_events = [e for e in bus.history if isinstance(e, PaperAdded)]
        added_paths = {e.path for e in added_events}
        assert added_paths == {str(p1), str(p2)}


# ---------------------------------------------------------------------------
# Failure at extract stage
# ---------------------------------------------------------------------------

class TestExtractFailure:
    def test_ingest_failed_published_on_extract_error(self, tmp_path, isolated_papergraph_dir):
        """IngestFailed published, failure recorded, run continues."""
        from research_companion import store

        _make_pdf(tmp_path, "p1.pdf")
        _make_pdf(tmp_path, "p2.pdf")

        _idx = [0]

        def add_pdf(path):
            idx = _idx[0]
            _idx[0] += 1
            pid = f"local:{'aaa' if idx == 0 else 'bbb'}"
            meta = _make_meta(pid)
            meta.save()
            store.save_text(pid, f"{_GOOD_TEXT} Paper {pid}.")
            return meta

        def bad_extractor(meta, *, provider="anthropic", model=None, force=False):
            if meta.paper_id == "local:aaa":
                raise RuntimeError("extraction failed for p1")
            return (
                {"concepts": [], "methods": [], "datasets": [], "claims": [], "results": [], "related_work": []},
                {"input_tokens": 1, "output_tokens": 1, "cached": False},
            )

        def sectioner(paper_id, **kwargs):
            return [_fake_section()]

        bus = Bus()
        result = asyncio.run(
            ingest_folder(
                tmp_path,
                bus=bus,
                add_pdf=add_pdf,
                extractor=bad_extractor,
                sectioner=sectioner,
                aligner=None,
                strengther=None,
            )
        )

        # One failed, one added
        assert len(result.failed) == 1
        assert len(result.added) == 1

        # IngestFailed published for the first paper
        failed_events = [e for e in bus.history if isinstance(e, IngestFailed)]
        assert len(failed_events) == 1
        assert failed_events[0].stage == "extract"
        assert "extraction failed" in failed_events[0].error

        # Failure recorded in store
        path_str = str(sorted(tmp_path.glob("*.pdf"))[0])
        failures = store.list_failures()
        assert any(k == path_str for k in failures)

    def test_run_continues_after_failure(self, tmp_path, isolated_papergraph_dir):
        """After one failure, remaining papers still get processed."""
        from research_companion import store

        _make_pdf(tmp_path, "a_bad.pdf")
        _make_pdf(tmp_path, "b_good.pdf")

        _idx = [0]

        def add_pdf(path):
            idx = _idx[0]
            _idx[0] += 1
            pid = f"local:{'fail' if idx == 0 else 'good'}"
            meta = _make_meta(pid)
            meta.save()
            store.save_text(pid, f"{_GOOD_TEXT} Paper {pid}.")
            return meta

        def extractor(meta, *, provider="anthropic", model=None, force=False):
            if meta.paper_id == "local:fail":
                raise RuntimeError("boom")
            return (
                {"concepts": [], "methods": [], "datasets": [], "claims": [], "results": [], "related_work": []},
                {"input_tokens": 1, "output_tokens": 1, "cached": False},
            )

        bus = Bus()
        result = asyncio.run(
            ingest_folder(
                tmp_path,
                bus=bus,
                add_pdf=add_pdf,
                extractor=extractor,
                sectioner=lambda pid, **kw: [_fake_section()],
                aligner=None,
                strengther=None,
            )
        )

        assert len(result.added) == 1
        assert len(result.failed) == 1
        assert isinstance(bus.history[-1], JobDone)

    def test_failed_paper_clear_failure_on_success(self, tmp_path, isolated_papergraph_dir):
        """On successful re-run, clear_failure is called."""
        from research_companion import store

        p1 = _make_pdf(tmp_path, "p1.pdf")

        # First run: record a failure manually
        path_str = str(p1)
        store.record_failure(path_str, {"stage": "extract", "error": "old error"})
        assert path_str in store.list_failures()

        # Second run: succeeds (using _make_fakes which saves text to store)
        add, sect, ext, _, _ = _make_fakes(["local:aaa"])
        bus = Bus()
        result = asyncio.run(
            ingest_folder(
                tmp_path,
                bus=bus,
                add_pdf=add,
                extractor=ext,
                sectioner=sect,
                aligner=None,
                strengther=None,
            )
        )

        assert len(result.added) == 1
        # Failure should be cleared
        assert path_str not in store.list_failures()


# ---------------------------------------------------------------------------
# Empty / degenerate text quality gate (scanned-PDF honesty fix)
# ---------------------------------------------------------------------------

class TestEmptyTextGate:
    def test_empty_text_fails_with_scanned_reason(self, tmp_path, isolated_papergraph_dir, monkeypatch):
        """A PDF whose extracted text is empty, with OCR unavailable -> paper FAILS
        (not done), with the scanned-PDF reason recorded, extract never reached."""
        from research_companion import extract, store
        from research_companion.lab import EMPTY_TEXT_ERROR

        _make_pdf(tmp_path, "scanned.pdf")

        # OCR fallback unavailable (docling absent) -> None. Avoids running a real
        # ~7-minute forced-OCR convert against the stub PDF when docling is installed.
        monkeypatch.setattr(extract, "ocr_fallback_parse", lambda meta: None)

        def add_pdf(path):
            meta = _make_meta("local:scanned")
            meta.save()
            store.save_text("local:scanned", "")  # empty extraction (scanned/image)
            return meta

        extract_calls = []

        def extractor(meta, *, provider="anthropic", model=None, force=False):
            extract_calls.append(meta.paper_id)
            return ({"concepts": [], "methods": [], "datasets": [], "claims": [],
                     "results": [], "related_work": []}, {"cached": False})

        bus = Bus()
        result = asyncio.run(
            ingest_folder(
                tmp_path,
                bus=bus,
                add_pdf=add_pdf,
                extractor=extractor,
                sectioner=lambda pid, **kw: [_fake_section()],
                aligner=None,
                strengther=None,
            )
        )

        # Failed, not added; extractor never called (gate is before extract).
        assert len(result.failed) == 1
        assert len(result.added) == 0
        assert extract_calls == []

        # IngestFailed published at the extract stage with the scanned reason.
        failed_events = [e for e in bus.history if isinstance(e, IngestFailed)]
        assert len(failed_events) == 1
        assert failed_events[0].stage == "extract"
        assert "scanned" in failed_events[0].error.lower()
        assert failed_events[0].error == EMPTY_TEXT_ERROR

        # Failure recorded (keyed by path, so re-runs can clear it).
        path_str = str(sorted(tmp_path.glob("*.pdf"))[0])
        assert path_str in store.list_failures()

    def test_good_text_still_succeeds(self, tmp_path, isolated_papergraph_dir):
        """A healthy text PDF still ingests successfully (gate does not over-fire)."""
        _make_pdf(tmp_path, "good.pdf")
        add, sect, ext, _, _ = _make_fakes(["local:good"])

        bus = Bus()
        result = asyncio.run(
            ingest_folder(
                tmp_path,
                bus=bus,
                add_pdf=add,
                extractor=ext,
                sectioner=sect,
                aligner=None,
                strengther=None,
            )
        )

        assert len(result.added) == 1
        assert len(result.failed) == 0


# ---------------------------------------------------------------------------
# OCR fallback for scanned PDFs (forced full-page OCR) — all MOCKED, no real OCR
# ---------------------------------------------------------------------------

class TestOcrFallback:
    """Stage 2: when normal extraction yields no usable text, a forced full-page
    OCR fallback is attempted. All docling/OCR is MOCKED via extract.* seams so
    the gate never runs real OCR (which takes minutes)."""

    def _empty_parsed(self):
        from research_companion.parsers import ParsedDoc
        return ParsedDoc(text="")  # scanned/image-only -> fails the quality gate

    def _ocr_parsed(self):
        from research_companion.parsers import ParsedDoc
        return ParsedDoc(
            text=_GOOD_TEXT,
            sections=[
                {"section_id": "s1", "title": "Introduction", "level": 1,
                 "parent": None, "char_start": 0, "char_end": 80},
                {"section_id": "s2", "title": "Methods", "level": 1,
                 "parent": None, "char_start": 80, "char_end": len(_GOOD_TEXT)},
            ],
        )

    def test_ocr_fallback_recovers_scanned_pdf(
        self, tmp_path, isolated_papergraph_dir, monkeypatch
    ):
        """Normal parse empty + OCR (mocked) returns good text -> SUCCESS, OCR
        sections persisted with method='docling'."""
        from research_companion import extract, store

        _make_pdf(tmp_path, "scanned.pdf")
        add, sect, ext, _, _ = _make_fakes(["local:scan"])

        monkeypatch.setattr(extract, "get_paper_parsed", lambda meta, **kw: self._empty_parsed())
        ocr_calls = []

        def fake_ocr(meta):
            ocr_calls.append(meta.paper_id)
            return self._ocr_parsed()

        monkeypatch.setattr(extract, "ocr_fallback_parse", fake_ocr)

        sectioner_calls = []

        def tracking_sectioner(pid, **kw):
            sectioner_calls.append(pid)
            return sect(pid)

        bus = Bus()
        result = asyncio.run(
            ingest_folder(
                tmp_path, bus=bus, add_pdf=add, extractor=ext,
                sectioner=tracking_sectioner, aligner=None, strengther=None,
            )
        )

        assert len(result.added) == 1
        assert len(result.failed) == 0
        assert ocr_calls == ["local:scan"]         # OCR fallback WAS invoked
        assert sectioner_calls == []               # OCR sections win over heuristic
        saved = store.load_sections("local:scan")
        assert saved is not None and saved["method"] == "docling"
        assert [s["section_id"] for s in saved["sections"]] == ["s1", "s2"]
        # No IngestFailed on the success path.
        assert [e for e in bus.history if isinstance(e, IngestFailed)] == []
        # Provenance recorded on meta and persisted to disk.
        loaded_meta = store.PaperMetadata.load("local:scan")
        assert loaded_meta is not None
        assert loaded_meta.ocr_used is True
        assert loaded_meta.parse_source == "docling+ocr"
        # OCR-progress message is the clearer, user-facing string.
        progress = [e for e in bus.history if isinstance(e, IngestProgress)]
        assert any("OCR-ing scanned PDF (may take a few minutes)" in e.current for e in progress)

    def test_ocr_fallback_unavailable_fails_with_install_message(
        self, tmp_path, isolated_papergraph_dir, monkeypatch
    ):
        """Normal parse empty + docling not importable (OCR returns None) -> FAILED
        with the install-docling message."""
        from research_companion import extract, store
        from research_companion.lab import EMPTY_TEXT_ERROR

        _make_pdf(tmp_path, "scanned.pdf")
        add, sect, ext, _, _ = _make_fakes(["local:scan"])

        monkeypatch.setattr(extract, "get_paper_parsed", lambda meta, **kw: self._empty_parsed())
        monkeypatch.setattr(extract, "ocr_fallback_parse", lambda meta: None)

        bus = Bus()
        result = asyncio.run(
            ingest_folder(
                tmp_path, bus=bus, add_pdf=add, extractor=ext,
                sectioner=sect, aligner=None, strengther=None,
            )
        )

        assert len(result.failed) == 1
        assert len(result.added) == 0
        failed = [e for e in bus.history if isinstance(e, IngestFailed)]
        assert len(failed) == 1
        assert failed[0].stage == "extract"
        assert failed[0].error == EMPTY_TEXT_ERROR
        assert str(sorted(tmp_path.glob("*.pdf"))[0]) in store.list_failures()

    def test_ocr_fallback_ran_but_still_empty_fails(
        self, tmp_path, isolated_papergraph_dir, monkeypatch
    ):
        """Normal parse empty + OCR ran (docling present) but still returned no
        usable text -> FAILED with the 'even with OCR' message."""
        from research_companion import extract
        from research_companion.lab import OCR_FAILED_ERROR

        _make_pdf(tmp_path, "scanned.pdf")
        add, sect, ext, _, _ = _make_fakes(["local:scan"])

        monkeypatch.setattr(extract, "get_paper_parsed", lambda meta, **kw: self._empty_parsed())
        # OCR ran (non-None) but recovered nothing usable.
        monkeypatch.setattr(extract, "ocr_fallback_parse", lambda meta: self._empty_parsed())

        bus = Bus()
        result = asyncio.run(
            ingest_folder(
                tmp_path, bus=bus, add_pdf=add, extractor=ext,
                sectioner=sect, aligner=None, strengther=None,
            )
        )

        assert len(result.failed) == 1
        assert len(result.added) == 0
        failed = [e for e in bus.history if isinstance(e, IngestFailed)]
        assert len(failed) == 1
        assert failed[0].stage == "extract"
        assert failed[0].error == OCR_FAILED_ERROR

    def test_digital_pdf_does_not_invoke_ocr(
        self, tmp_path, isolated_papergraph_dir, monkeypatch
    ):
        """A digital PDF (good text) must NOT pay the OCR cost: the fallback is
        never called."""
        from research_companion import extract

        _make_pdf(tmp_path, "digital.pdf")
        add, sect, ext, _, _ = _make_fakes(["local:digital"])

        ocr_calls = []

        def fake_ocr(meta):
            ocr_calls.append(meta.paper_id)
            raise AssertionError("OCR fallback must not run for a digital PDF")

        monkeypatch.setattr(extract, "ocr_fallback_parse", fake_ocr)

        bus = Bus()
        result = asyncio.run(
            ingest_folder(
                tmp_path, bus=bus, add_pdf=add, extractor=ext,
                sectioner=sect, aligner=None, strengther=None,
            )
        )

        assert len(result.added) == 1
        assert ocr_calls == []

        # Digital happy path: no OCR involved, provenance reflects the
        # configured parser (conftest pins RESEARCH_COMPANION_PARSER=pypdfium).
        loaded_meta = PaperMetadata.load("local:digital")
        assert loaded_meta is not None
        assert loaded_meta.ocr_used is False
        assert loaded_meta.parse_source == "pypdfium"

    def test_reingest_on_cached_text_preserves_prior_ocr_provenance(
        self, tmp_path, isolated_papergraph_dir, monkeypatch
    ):
        """Re-ingesting a paper whose usable text is already cached must NOT
        re-run the parser or downgrade prior provenance. A previously-OCR'd
        paper keeps ocr_used=True / parse_source='docling+ocr' — otherwise the
        OCR badge would vanish on a plain re-add even though the on-disk text is
        still the OCR-recovered text."""
        from research_companion import extract, store
        from research_companion.lab import ingest_one
        from research_companion.parsers import ParsedDoc

        pid = "local:scan"
        _make_pdf(tmp_path, "scanned.pdf")
        # Prior state, as left by a first successful OCR ingest: OCR-recovered
        # text cached on disk + meta flagged OCR.
        store.save_text(pid, _GOOD_TEXT)
        meta = store.PaperMetadata(
            paper_id=pid, title="Scanned", authors=["A"],
            parse_source="docling+ocr", ocr_used=True,
        )
        meta.save()

        # This pass serves the cached text (quality gate passes) — the parser
        # does NOT re-run and OCR must not run.
        monkeypatch.setattr(extract, "get_paper_parsed",
                            lambda m, **kw: ParsedDoc(text=_GOOD_TEXT))

        def _no_ocr(m):
            raise AssertionError("OCR must not run when cached text is usable")

        monkeypatch.setattr(extract, "ocr_fallback_parse", _no_ocr)

        _, sect, ext, _, _ = _make_fakes([pid])
        bus = Bus()
        ok = asyncio.run(ingest_one(
            meta, str(tmp_path / "scanned.pdf"), bus=bus,
            provider="anthropic", model=None, align=False,
            aligner=None, strengther=None, extractor=ext, sectioner=sect,
        ))
        assert ok is True
        reloaded = store.PaperMetadata.load(pid)
        assert reloaded.ocr_used is True
        assert reloaded.parse_source == "docling+ocr"


# ---------------------------------------------------------------------------
# Docling structural sections wiring (stage 2)
# ---------------------------------------------------------------------------

class TestParserSectionsWiring:
    """When the parser (docling) returns non-empty sections, stage 2 persists
    them via the store and does NOT call the heuristic sectioner. When the parser
    returns no sections, the heuristic sectioner still runs (fallback preserved).
    """

    def _parsed(self, tables=None, figures=None):
        from research_companion.parsers import ParsedDoc
        return ParsedDoc(
            text=_GOOD_TEXT,
            sections=[
                {"section_id": "s1", "title": "Introduction", "level": 1,
                 "parent": None, "char_start": 0, "char_end": 80},
                {"section_id": "s2", "title": "Methods", "level": 1,
                 "parent": None, "char_start": 80, "char_end": len(_GOOD_TEXT)},
            ],
            tables=tables or [],
            figures=figures or [],
        )

    def test_docling_sections_persisted_and_sectioner_skipped(
        self, tmp_path, isolated_papergraph_dir, monkeypatch
    ):
        from research_companion import extract, store

        _make_pdf(tmp_path, "p1.pdf")
        add, sect, ext, _, _ = _make_fakes(["local:aaa"])

        sectioner_calls = []

        def tracking_sectioner(paper_id, **kw):
            sectioner_calls.append(paper_id)
            return sect(paper_id)

        monkeypatch.setattr(
            extract, "get_paper_parsed",
            lambda meta, **kw: self._parsed(
                tables=[{"markdown": "| a |\n|---|\n| 1 |", "caption": "T1"}],
                figures=[{"caption": "F1"}],
            ),
        )

        bus = Bus()
        result = asyncio.run(
            ingest_folder(
                tmp_path, bus=bus, add_pdf=add, extractor=ext,
                sectioner=tracking_sectioner, aligner=None, strengther=None,
            )
        )

        assert len(result.added) == 1
        # Heuristic sectioner NOT invoked — docling sections win.
        assert sectioner_calls == []
        # Sections persisted with method="docling".
        saved = store.load_sections("local:aaa")
        assert saved is not None
        assert saved["method"] == "docling"
        assert [s["section_id"] for s in saved["sections"]] == ["s1", "s2"]
        # Tables/figures persisted to structure.json.
        structure = store.load_structure("local:aaa")
        assert structure is not None
        assert structure["tables"][0]["caption"] == "T1"
        assert structure["figures"] == [{"caption": "F1"}]
        # SectionTreeBuilt reflects the docling section count.
        built = [e for e in bus.history if isinstance(e, SectionTreeBuilt)]
        assert built[0].n_sections == 2

    def test_empty_parser_sections_falls_back_to_sectioner(
        self, tmp_path, isolated_papergraph_dir, monkeypatch
    ):
        from research_companion import extract, store
        from research_companion.parsers import ParsedDoc

        _make_pdf(tmp_path, "p1.pdf")
        add, sect, ext, _, _ = _make_fakes(["local:aaa"])

        sectioner_calls = []

        def tracking_sectioner(paper_id, **kw):
            sectioner_calls.append(paper_id)
            return sect(paper_id)

        monkeypatch.setattr(
            extract, "get_paper_parsed",
            lambda meta, **kw: ParsedDoc(text=_GOOD_TEXT),  # no structural sections
        )

        bus = Bus()
        result = asyncio.run(
            ingest_folder(
                tmp_path, bus=bus, add_pdf=add, extractor=ext,
                sectioner=tracking_sectioner, aligner=None, strengther=None,
            )
        )

        assert len(result.added) == 1
        # Heuristic sectioner IS invoked (fallback preserved).
        assert sectioner_calls == ["local:aaa"]
        # No structure.json written when there are no tables/figures.
        assert store.load_structure("local:aaa") is None


# ---------------------------------------------------------------------------
# Skip path
# ---------------------------------------------------------------------------

class TestSkipPath:
    def test_already_ingested_paper_skipped(self, tmp_path, isolated_papergraph_dir):
        """Already-ingested-and-extracted paper -> skipped, no PaperAdded."""
        from research_companion import store
        from research_companion.prompts import extraction_prompt_sha256

        _make_pdf(tmp_path, "p1.pdf")

        # Pre-populate extraction cache so it looks already ingested
        paper_id = "local:skip_me"
        meta = _make_meta(paper_id)
        meta.save()
        # Save cached extraction so skip check finds it
        store.save_extraction(paper_id, {"concepts": [], "methods": [], "datasets": [],
                                         "claims": [], "results": [], "related_work": []},
                              prompt_sha=extraction_prompt_sha256())

        def add_pdf(path):
            return meta  # returns same meta (simulates idempotent add)

        bus = Bus()
        result = asyncio.run(
            ingest_folder(
                tmp_path,
                bus=bus,
                add_pdf=add_pdf,
                extractor=lambda m, **kw: ({}, {}),  # should not be called
                sectioner=lambda pid, **kw: [],
                aligner=None,
                strengther=None,
            )
        )

        assert len(result.skipped) == 1
        assert len(result.added) == 0
        # No PaperAdded event
        added_events = [e for e in bus.history if isinstance(e, PaperAdded)]
        assert len(added_events) == 0
        # IngestSkipped event published with the right path/paper_id
        skipped_events = [e for e in bus.history if isinstance(e, IngestSkipped)]
        assert len(skipped_events) == 1
        assert skipped_events[0].path == str(tmp_path / "p1.pdf")
        assert skipped_events[0].paper_id == paper_id
        assert skipped_events[0].reason == "already in library"


# ---------------------------------------------------------------------------
# Alignment scenarios
# ---------------------------------------------------------------------------

class TestAlignment:
    def test_align_skipped_when_no_draft(self, tmp_path, isolated_papergraph_dir):
        """No AlignmentReady when draft not set."""
        _make_pdf(tmp_path, "p1.pdf")
        add, sect, ext, align, strength = _make_fakes(["local:aaa"])
        bus = Bus()

        asyncio.run(
            ingest_folder(
                tmp_path,
                bus=bus,
                add_pdf=add,
                extractor=ext,
                sectioner=sect,
                aligner=align,
                strengther=None,
                align=True,
            )
        )

        align_events = [e for e in bus.history if isinstance(e, AlignmentReady)]
        assert len(align_events) == 0

    def test_align_skipped_when_no_align_flag(self, tmp_path, isolated_papergraph_dir):
        """No AlignmentReady when align=False."""
        from research_companion import store as _store

        _store.set_draft_paper_id("local:draft")
        _make_pdf(tmp_path, "p1.pdf")
        add, sect, ext, align, _ = _make_fakes(["local:candidate"])
        bus = Bus()

        asyncio.run(
            ingest_folder(
                tmp_path,
                bus=bus,
                add_pdf=add,
                extractor=ext,
                sectioner=sect,
                aligner=align,
                strengther=None,
                align=False,  # --no-align
            )
        )

        align_events = [e for e in bus.history if isinstance(e, AlignmentReady)]
        assert len(align_events) == 0

    def test_align_skipped_for_draft_itself(self, tmp_path, isolated_papergraph_dir):
        """No AlignmentReady when the paper being ingested IS the draft."""
        from research_companion import store as _store

        paper_id = "local:draft_paper"
        _store.set_draft_paper_id(paper_id)
        _make_pdf(tmp_path, "p1.pdf")

        # Use _make_fakes (which saves text) but override add_pdf to return draft paper
        add, sect, ext, align, _ = _make_fakes([paper_id])
        bus = Bus()

        asyncio.run(
            ingest_folder(
                tmp_path,
                bus=bus,
                add_pdf=add,
                extractor=ext,
                sectioner=sect,
                aligner=align,
                strengther=None,
                align=True,
            )
        )

        align_events = [e for e in bus.history if isinstance(e, AlignmentReady)]
        assert len(align_events) == 0

    def test_align_ready_published_when_draft_set(self, tmp_path, isolated_papergraph_dir):
        """AlignmentReady published when draft is set and paper is not the draft."""
        from research_companion import store as _store

        draft_id = "local:draft_paper"
        candidate_id = "local:candidate_paper"
        _store.set_draft_paper_id(draft_id)

        _make_pdf(tmp_path, "p1.pdf")
        add, sect, ext, align, _ = _make_fakes([candidate_id])
        bus = Bus()

        asyncio.run(
            ingest_folder(
                tmp_path,
                bus=bus,
                add_pdf=add,
                extractor=ext,
                sectioner=sect,
                aligner=align,
                strengther=None,
                align=True,
            )
        )

        align_events = [e for e in bus.history if isinstance(e, AlignmentReady)]
        assert len(align_events) == 1
        assert align_events[0].verdict == "medium"
        assert align_events[0].score == 0.5
        assert align_events[0].draft_paper_id == draft_id

    def test_aligner_none_no_crash(self, tmp_path, isolated_papergraph_dir):
        """aligner=None -> no AlignmentReady, no crash."""
        from research_companion import store as _store

        _store.set_draft_paper_id("local:draft")
        _make_pdf(tmp_path, "p1.pdf")
        add, sect, ext, _, _ = _make_fakes(["local:candidate"])
        bus = Bus()

        result = asyncio.run(
            ingest_folder(
                tmp_path,
                bus=bus,
                add_pdf=add,
                extractor=ext,
                sectioner=sect,
                aligner=None,  # explicitly None -> skip
                strengther=None,
                align=True,
            )
        )

        align_events = [e for e in bus.history if isinstance(e, AlignmentReady)]
        assert len(align_events) == 0
        assert len(result.added) == 1


# ---------------------------------------------------------------------------
# Align / strength non-fatal failures publish IngestFailed
# ---------------------------------------------------------------------------

class TestAlignStrengthFailures:
    """Stages 5 and 6: failures publish IngestFailed but do NOT count as file failures."""

    def test_align_failure_publishes_ingest_failed(self, tmp_path, isolated_papergraph_dir):
        """Aligner raising -> IngestFailed(stage='align') published; paper still added."""
        from research_companion import store as _store

        draft_id = "local:draft"
        candidate_id = "local:candidate"
        _store.set_draft_paper_id(draft_id)

        _make_pdf(tmp_path, "p1.pdf")
        add, sect, ext, _, _ = _make_fakes([candidate_id])

        def bad_aligner(draft, cand, *, llm, **kw):
            raise RuntimeError("align kaboom")

        bus = Bus()
        result = asyncio.run(
            ingest_folder(
                tmp_path,
                bus=bus,
                add_pdf=add,
                extractor=ext,
                sectioner=sect,
                aligner=bad_aligner,
                strengther=None,
                align=True,
            )
        )

        # Paper still added — non-fatal
        assert len(result.added) == 1
        assert len(result.failed) == 0

        # IngestFailed with stage='align' published
        failed_events = [e for e in bus.history if isinstance(e, IngestFailed)]
        assert len(failed_events) == 1
        assert failed_events[0].stage == "align"
        assert "kaboom" in failed_events[0].error
        assert failed_events[0].paper_id == candidate_id

        # Failure NOT recorded in store (non-fatal)
        assert not _store.list_failures()

    def test_strength_failure_publishes_ingest_failed(self, tmp_path, isolated_papergraph_dir):
        """Strengther raising -> IngestFailed(stage='strength') published; paper still added."""
        from research_companion import store as _store

        _make_pdf(tmp_path, "p1.pdf")
        add, sect, ext, _, _ = _make_fakes(["local:aaa"])

        def bad_strengther(paper_id, **kw):
            raise RuntimeError("strength kaboom")

        bus = Bus()
        result = asyncio.run(
            ingest_folder(
                tmp_path,
                bus=bus,
                add_pdf=add,
                extractor=ext,
                sectioner=sect,
                aligner=None,
                strengther=bad_strengther,
            )
        )

        # Paper still added — non-fatal
        assert len(result.added) == 1
        assert len(result.failed) == 0

        # IngestFailed with stage='strength' published
        failed_events = [e for e in bus.history if isinstance(e, IngestFailed)]
        assert len(failed_events) == 1
        assert failed_events[0].stage == "strength"
        assert "kaboom" in failed_events[0].error
        assert failed_events[0].paper_id == "local:aaa"

        # Failure NOT recorded in store (non-fatal)
        assert not _store.list_failures()

    def test_align_failure_does_not_affect_job_done(self, tmp_path, isolated_papergraph_dir):
        """After align failure, pipeline still emits JobDone."""
        from research_companion import store as _store

        _store.set_draft_paper_id("local:draft")
        _make_pdf(tmp_path, "p1.pdf")
        add, sect, ext, _, _ = _make_fakes(["local:cand"])

        def bad_aligner(draft, cand, *, llm, **kw):
            raise RuntimeError("align err")

        bus = Bus()
        asyncio.run(
            ingest_folder(
                tmp_path,
                bus=bus,
                add_pdf=add,
                extractor=ext,
                sectioner=sect,
                aligner=bad_aligner,
                strengther=None,
                align=True,
            )
        )

        assert isinstance(bus.history[-1], JobDone)


# ---------------------------------------------------------------------------
# Embed stage (stage 7) tests
# ---------------------------------------------------------------------------

class TestEmbedStage:
    """Stage 7: embed — non-fatal, publishes EmbeddingsReady or IngestFailed."""

    def test_embed_happy_path_publishes_embeddings_ready(self, tmp_path, isolated_papergraph_dir):
        """Embedder returning payload -> EmbeddingsReady with correct n_vectors."""
        _make_pdf(tmp_path, "p1.pdf")
        add, sect, ext, _, strength = _make_fakes(["local:aaa"])

        def fake_embedder(paper_id):
            return {
                "embed_model": "test-model",
                "vectors": {"s1": {"vector": [0.1, 0.2]}, "s2": {"vector": [0.3, 0.4]}},
            }

        bus = Bus()
        asyncio.run(
            ingest_folder(
                tmp_path,
                bus=bus,
                add_pdf=add,
                extractor=ext,
                sectioner=sect,
                aligner=None,
                strengther=None,
                embedder=fake_embedder,
                suggester=None,
            )
        )

        embed_events = [e for e in bus.history if isinstance(e, EmbeddingsReady)]
        assert len(embed_events) == 1
        assert embed_events[0].paper_id == "local:aaa"
        assert embed_events[0].n_vectors == 2

    def test_embed_returns_none_no_event_no_failure(self, tmp_path, isolated_papergraph_dir):
        """Embedder returning None (no HF token) -> no EmbeddingsReady, no IngestFailed."""
        _make_pdf(tmp_path, "p1.pdf")
        add, sect, ext, _, _ = _make_fakes(["local:aaa"])

        def fake_embedder(paper_id):
            return None  # simulates missing HF_TOKEN

        bus = Bus()
        result = asyncio.run(
            ingest_folder(
                tmp_path,
                bus=bus,
                add_pdf=add,
                extractor=ext,
                sectioner=sect,
                aligner=None,
                strengther=None,
                embedder=fake_embedder,
                suggester=None,
            )
        )

        embed_events = [e for e in bus.history if isinstance(e, EmbeddingsReady)]
        failed_events = [e for e in bus.history if isinstance(e, IngestFailed)]
        assert len(embed_events) == 0
        assert len(failed_events) == 0
        assert len(result.added) == 1

    def test_embed_raises_publishes_ingest_failed_file_still_succeeds(
        self, tmp_path, isolated_papergraph_dir
    ):
        """Embedder raising -> IngestFailed(stage='embed') + paper still added."""
        _make_pdf(tmp_path, "p1.pdf")
        add, sect, ext, _, _ = _make_fakes(["local:aaa"])

        def bad_embedder(paper_id):
            raise RuntimeError("embed kaboom")

        bus = Bus()
        result = asyncio.run(
            ingest_folder(
                tmp_path,
                bus=bus,
                add_pdf=add,
                extractor=ext,
                sectioner=sect,
                aligner=None,
                strengther=None,
                embedder=bad_embedder,
                suggester=None,
            )
        )

        # Paper still added — non-fatal
        assert len(result.added) == 1
        assert len(result.failed) == 0

        # IngestFailed with stage='embed' published
        failed_events = [e for e in bus.history if isinstance(e, IngestFailed)]
        assert len(failed_events) == 1
        assert failed_events[0].stage == "embed"
        assert "kaboom" in failed_events[0].error
        assert failed_events[0].paper_id == "local:aaa"

        # Failure NOT recorded in store (non-fatal)
        from research_companion import store as _store
        assert not _store.list_failures()

    def test_embedder_none_skips_embed_stage(self, tmp_path, isolated_papergraph_dir):
        """embedder=None -> no EmbeddingsReady, no failure, file still succeeds."""
        _make_pdf(tmp_path, "p1.pdf")
        add, sect, ext, _, _ = _make_fakes(["local:aaa"])

        bus = Bus()
        result = asyncio.run(
            ingest_folder(
                tmp_path,
                bus=bus,
                add_pdf=add,
                extractor=ext,
                sectioner=sect,
                aligner=None,
                strengther=None,
                embedder=None,  # explicitly skip
                suggester=None,
            )
        )

        embed_events = [e for e in bus.history if isinstance(e, EmbeddingsReady)]
        assert len(embed_events) == 0
        assert len(result.added) == 1


# ---------------------------------------------------------------------------
# Suggestions auto-regen at end of ingest
# ---------------------------------------------------------------------------

class TestSuggestionsAutoRegen:
    """Post-loop: SuggestionsUpdated published once per run when draft is configured."""

    def test_suggestions_updated_published_when_draft_set(self, tmp_path, isolated_papergraph_dir):
        """When draft is configured and suggester returns payload, SuggestionsUpdated published."""
        from research_companion import store as _store

        draft_id = "local:draft"
        _store.set_draft_paper_id(draft_id)

        _make_pdf(tmp_path, "p1.pdf")
        add, sect, ext, _, _ = _make_fakes(["local:candidate"])

        def fake_suggester(*, draft_id):
            return {
                "draft_paper_id": draft_id,
                "suggestions": [
                    {"status": "open", "title": "Sug1"},
                    {"status": "open", "title": "Sug2"},
                    {"status": "addressed", "title": "Sug3"},
                    {"status": "dismissed", "title": "Sug4"},
                ],
            }

        bus = Bus()
        asyncio.run(
            ingest_folder(
                tmp_path,
                bus=bus,
                add_pdf=add,
                extractor=ext,
                sectioner=sect,
                aligner=None,
                strengther=None,
                embedder=None,
                suggester=fake_suggester,
            )
        )

        sug_events = [e for e in bus.history if isinstance(e, SuggestionsUpdated)]
        assert len(sug_events) == 1
        assert sug_events[0].draft_paper_id == draft_id
        assert sug_events[0].open == 2
        assert sug_events[0].addressed == 1
        assert sug_events[0].dismissed == 1

    def test_suggestions_not_published_when_no_draft(self, tmp_path, isolated_papergraph_dir):
        """No SuggestionsUpdated when no draft is configured."""
        _make_pdf(tmp_path, "p1.pdf")
        add, sect, ext, _, _ = _make_fakes(["local:candidate"])

        def fake_suggester(*, draft_id):
            return {"draft_paper_id": draft_id, "suggestions": []}

        bus = Bus()
        asyncio.run(
            ingest_folder(
                tmp_path,
                bus=bus,
                add_pdf=add,
                extractor=ext,
                sectioner=sect,
                aligner=None,
                strengther=None,
                embedder=None,
                suggester=fake_suggester,
            )
        )

        sug_events = [e for e in bus.history if isinstance(e, SuggestionsUpdated)]
        assert len(sug_events) == 0

    def test_suggestions_published_once_even_for_multiple_papers(
        self, tmp_path, isolated_papergraph_dir
    ):
        """SuggestionsUpdated is published exactly once after the loop, not per-paper."""
        from research_companion import store as _store

        draft_id = "local:draft"
        _store.set_draft_paper_id(draft_id)

        _make_pdf(tmp_path, "p1.pdf")
        _make_pdf(tmp_path, "p2.pdf")
        add, sect, ext, _, _ = _make_fakes(["local:aaa", "local:bbb"])

        call_count = [0]

        def counting_suggester(*, draft_id):
            call_count[0] += 1
            return {"draft_paper_id": draft_id, "suggestions": []}

        bus = Bus()
        asyncio.run(
            ingest_folder(
                tmp_path,
                bus=bus,
                add_pdf=add,
                extractor=ext,
                sectioner=sect,
                aligner=None,
                strengther=None,
                embedder=None,
                suggester=counting_suggester,
            )
        )

        assert call_count[0] == 1
        sug_events = [e for e in bus.history if isinstance(e, SuggestionsUpdated)]
        assert len(sug_events) == 1

    def test_suggester_error_is_non_fatal(self, tmp_path, isolated_papergraph_dir):
        """Suggester raising -> run still completes, JobDone still published."""
        from research_companion import store as _store

        _store.set_draft_paper_id("local:draft")
        _make_pdf(tmp_path, "p1.pdf")
        add, sect, ext, _, _ = _make_fakes(["local:aaa"])

        def bad_suggester(*, draft_id):
            raise RuntimeError("suggestions kaboom")

        bus = Bus()
        result = asyncio.run(
            ingest_folder(
                tmp_path,
                bus=bus,
                add_pdf=add,
                extractor=ext,
                sectioner=sect,
                aligner=None,
                strengther=None,
                embedder=None,
                suggester=bad_suggester,
            )
        )

        assert len(result.added) == 1
        assert isinstance(bus.history[-1], JobDone)


# ---------------------------------------------------------------------------
# Event serialization round-trips
# ---------------------------------------------------------------------------

class TestEventSerialization:
    def _roundtrip(self, ev):
        d = event_to_dict(ev)
        json_str = json.dumps(d)
        parsed = json.loads(json_str)
        return parsed

    def test_paper_added(self):
        ev = PaperAdded(paper_id="local:abc", title="A paper", source="file://foo.pdf")
        d = self._roundtrip(ev)
        assert d["event"] == "paper_added"
        assert d["paper_id"] == "local:abc"
        assert d["title"] == "A paper"
        assert d["source"] == "file://foo.pdf"

    def test_paper_added_default_source(self):
        ev = PaperAdded(paper_id="local:abc", title="A paper")
        d = self._roundtrip(ev)
        assert d["source"] == ""

    def test_paper_added_default_path(self):
        ev = PaperAdded(paper_id="local:abc", title="A paper")
        d = self._roundtrip(ev)
        assert d["path"] == ""

    def test_paper_added_with_path(self):
        ev = PaperAdded(paper_id="local:abc", title="A paper", source="file://foo.pdf",
                         path="/f/a.pdf")
        d = self._roundtrip(ev)
        assert d["event"] == "paper_added"
        assert d["path"] == "/f/a.pdf"

    def test_section_tree_built(self):
        ev = SectionTreeBuilt(paper_id="local:abc", n_sections=5)
        d = self._roundtrip(ev)
        assert d["event"] == "section_tree_built"
        assert d["n_sections"] == 5

    def test_section_extracted(self):
        ev = SectionExtracted(paper_id="local:abc", section_id="s1",
                               title="Intro", counts={"concepts": 3})
        d = self._roundtrip(ev)
        assert d["event"] == "section_extracted"
        assert d["counts"] == {"concepts": 3}

    def test_graph_delta(self):
        ev = GraphDelta(paper_id="local:abc",
                        nodes_added=[{"id": "n1", "kind": "concept", "label": "X"}],
                        edges_added=[])
        d = self._roundtrip(ev)
        assert d["event"] == "graph_delta"
        assert len(d["nodes_added"]) == 1

    def test_alignment_ready(self):
        ev = AlignmentReady(paper_id="local:abc", draft_paper_id="local:draft",
                             verdict="high", score=0.85)
        d = self._roundtrip(ev)
        assert d["event"] == "alignment_ready"
        assert d["verdict"] == "high"
        assert d["score"] == 0.85

    def test_strength_updated(self):
        ev = StrengthUpdated(paper_id="local:abc", score=0.7, band="strong", color="#3fb950")
        d = self._roundtrip(ev)
        assert d["event"] == "strength_updated"
        assert d["band"] == "strong"

    def test_strength_updated_score_none(self):
        ev = StrengthUpdated(paper_id="local:abc", score=None, band="unscored", color="#8b949e")
        d = self._roundtrip(ev)
        assert d["score"] is None

    def test_ingest_failed(self):
        ev = IngestFailed(path="/foo/bar.pdf", stage="extract", error="boom", paper_id="local:abc")
        d = self._roundtrip(ev)
        assert d["event"] == "ingest_failed"
        assert d["stage"] == "extract"

    def test_ingest_failed_default_paper_id(self):
        ev = IngestFailed(path="/foo/bar.pdf", stage="add", error="not found")
        d = self._roundtrip(ev)
        assert d["paper_id"] == ""

    def test_ingest_progress(self):
        ev = IngestProgress(done=2, total=5, current="foo.pdf")
        d = self._roundtrip(ev)
        assert d["event"] == "ingest_progress"
        assert d["done"] == 2
        assert d["total"] == 5

    def test_job_done(self):
        ev = JobDone(job="ingest")
        d = self._roundtrip(ev)
        assert d["event"] == "job_done"
        assert d["job"] == "ingest"

    def test_job_done_default(self):
        ev = JobDone()
        d = self._roundtrip(ev)
        assert d["job"] == "ingest"

    def test_embeddings_ready(self):
        ev = EmbeddingsReady(paper_id="local:abc", n_vectors=5)
        d = self._roundtrip(ev)
        assert d["event"] == "embeddings_ready"
        assert d["paper_id"] == "local:abc"
        assert d["n_vectors"] == 5

    def test_ingest_skipped(self):
        ev = IngestSkipped(path="a.pdf", paper_id="local:x")
        d = self._roundtrip(ev)
        assert d["event"] == "ingest_skipped"
        assert d["path"] == "a.pdf"
        assert d["paper_id"] == "local:x"
        assert d["reason"] == "already in library"

    def test_ingest_skipped_default_reason_and_paper_id(self):
        ev = IngestSkipped(path="b.pdf")
        d = self._roundtrip(ev)
        assert d["paper_id"] == ""
        assert d["reason"] == "already in library"

    def test_suggestions_updated(self):
        ev = SuggestionsUpdated(
            draft_paper_id="local:draft", open=3, addressed=1, dismissed=0
        )
        d = self._roundtrip(ev)
        assert d["event"] == "suggestions_updated"
        assert d["draft_paper_id"] == "local:draft"
        assert d["open"] == 3


# ---------------------------------------------------------------------------
# Fixture regression test
# ---------------------------------------------------------------------------

class TestFixtureRegression:
    """Replay tests/fixtures/lab_events.jsonl and assert it matches re-serialized events."""

    FIXTURE_PATH = Path(__file__).parent / "fixtures" / "lab_events.jsonl"

    def test_fixture_exists(self):
        assert self.FIXTURE_PATH.exists(), (
            f"Fixture not found: {self.FIXTURE_PATH}. "
            "Run test_generate_fixture to create it."
        )

    def test_fixture_roundtrip(self):
        """Re-serializing the fixture events produces the same JSON lines."""
        lines = self.FIXTURE_PATH.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) > 0

        # Parse each line and ensure it's valid JSON with an 'event' key
        for line in lines:
            d = json.loads(line)
            assert "event" in d, f"Missing 'event' key in: {d}"

    def test_fixture_contains_expected_event_kinds(self):
        """Fixture must contain the core lab event kinds."""
        lines = self.FIXTURE_PATH.read_text(encoding="utf-8").strip().splitlines()
        kinds = {json.loads(line)["event"] for line in lines}

        required = {
            "ingest_progress",
            "paper_added",
            "section_tree_built",
            "graph_delta",
            "strength_updated",
            "ingest_failed",
            "job_done",
        }
        missing = required - kinds
        assert not missing, f"Fixture missing event kinds: {missing}"

    def test_fixture_field_names_stable(self):
        """Check specific field names haven't drifted (frozen API contract)."""
        lines = self.FIXTURE_PATH.read_text(encoding="utf-8").strip().splitlines()
        events_by_kind: dict[str, list[dict]] = {}
        for line in lines:
            d = json.loads(line)
            events_by_kind.setdefault(d["event"], []).append(d)

        # paper_added fields
        if "paper_added" in events_by_kind:
            e = events_by_kind["paper_added"][0]
            assert {"event", "paper_id", "title", "source"} <= e.keys()

        # graph_delta fields
        if "graph_delta" in events_by_kind:
            e = events_by_kind["graph_delta"][0]
            assert {"event", "paper_id", "nodes_added", "edges_added"} <= e.keys()

        # ingest_failed fields
        if "ingest_failed" in events_by_kind:
            e = events_by_kind["ingest_failed"][0]
            assert {"event", "path", "stage", "error", "paper_id"} <= e.keys()

        # ingest_progress fields
        if "ingest_progress" in events_by_kind:
            e = events_by_kind["ingest_progress"][0]
            assert {"event", "done", "total", "current"} <= e.keys()

        # strength_updated fields
        if "strength_updated" in events_by_kind:
            e = events_by_kind["strength_updated"][0]
            assert {"event", "paper_id", "score", "band", "color"} <= e.keys()

        # job_done fields
        if "job_done" in events_by_kind:
            e = events_by_kind["job_done"][0]
            assert {"event", "job"} <= e.keys()

    def test_fixture_replay_exact(self, tmp_path, isolated_papergraph_dir):
        """Re-run the same deterministic fake ingest and assert line-by-line JSON
        equality with the committed fixture (compares parsed dicts, not raw bytes,
        to be key-order-independent).  Any event shape or value drift causes failure.
        """
        import research_companion.lab as _lab

        add_pdf, sectioner, extractor, strengther, fake_scan = _fixture_fakes()

        original_scan = _lab.scan_pdfs
        _lab.scan_pdfs = fake_scan
        try:
            bus = Bus()
            asyncio.run(
                ingest_folder(
                    tmp_path,  # ignored by fake_scan
                    bus=bus,
                    add_pdf=add_pdf,
                    extractor=extractor,
                    sectioner=sectioner,
                    aligner=None,
                    strengther=strengther,
                    embedder=None,   # keep fixture stable: no embed events
                    suggester=None,  # keep fixture stable: no suggestions events
                )
            )
        finally:
            _lab.scan_pdfs = original_scan

        live_dicts = [event_to_dict(e) for e in bus.history]

        fixture_lines = self.FIXTURE_PATH.read_text(encoding="utf-8").strip().splitlines()
        fixture_dicts = [json.loads(line) for line in fixture_lines]

        assert len(live_dicts) == len(fixture_dicts), (
            f"Event count mismatch: live={len(live_dicts)}, fixture={len(fixture_dicts)}\n"
            f"Live kinds: {[d['event'] for d in live_dicts]}\n"
            f"Fixture kinds: {[d['event'] for d in fixture_dicts]}"
        )

        for i, (live, expected) in enumerate(zip(live_dicts, fixture_dicts, strict=False)):
            assert live.keys() == expected.keys(), (
                f"Line {i}: key set mismatch\n  live={set(live.keys())}\n  expected={set(expected.keys())}"
            )
            assert live == expected, (
                f"Line {i} ({live.get('event')!r}) value mismatch:\n  live={live}\n  expected={expected}"
            )


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------

class TestCliLab:
    def test_lab_ingest_parser_wiring(self, tmp_path, isolated_papergraph_dir, monkeypatch):
        """CLI parses lab ingest args and calls ingest_folder (monkeypatched)."""
        import research_companion.cli as cli

        folder = tmp_path / "papers"
        folder.mkdir()

        calls = []

        async def fake_ingest(folder, *, bus, **kwargs):
            calls.append({"folder": folder, "kwargs": kwargs})
            return IngestResult(added=["p1"], skipped=[], failed=[])

        monkeypatch.setitem(cli.LAB_INGEST_OVERRIDES, "ingest_folder", fake_ingest)

        rc = cli.main(["lab", "ingest", str(folder)])
        assert rc == 0
        assert len(calls) == 1
        assert calls[0]["folder"] == folder

    def test_lab_ingest_no_align_flag(self, tmp_path, isolated_papergraph_dir, monkeypatch):
        """--no-align passes align=False to ingest_folder."""
        import research_companion.cli as cli

        folder = tmp_path / "papers"
        folder.mkdir()

        calls = []

        async def fake_ingest(folder, *, bus, align=True, **kwargs):
            calls.append(align)
            return IngestResult(added=[], skipped=[], failed=[])

        monkeypatch.setitem(cli.LAB_INGEST_OVERRIDES, "ingest_folder", fake_ingest)
        cli.main(["lab", "ingest", "--no-align", str(folder)])

        assert calls[0] is False

    def test_lab_ingest_returns_rc2_on_failures(self, tmp_path, isolated_papergraph_dir, monkeypatch):
        """rc 2 when there are failures."""
        import research_companion.cli as cli

        folder = tmp_path / "papers"
        folder.mkdir()

        async def fake_ingest(folder, *, bus, **kwargs):
            return IngestResult(
                added=[],
                skipped=[],
                failed=[{"path": "/foo.pdf", "stage": "extract", "error": "boom"}],
            )

        monkeypatch.setitem(cli.LAB_INGEST_OVERRIDES, "ingest_folder", fake_ingest)
        rc = cli.main(["lab", "ingest", str(folder)])
        assert rc == 2

    def test_lab_ingest_missing_folder_rc1(self, tmp_path, isolated_papergraph_dir, monkeypatch):
        """rc 1 when folder doesn't exist."""
        import research_companion.cli as cli

        # Don't inject fake — use real lab which will raise ValueError
        monkeypatch.delitem(cli.LAB_INGEST_OVERRIDES, "ingest_folder", raising=False)
        rc = cli.main(["lab", "ingest", str(tmp_path / "no_such_folder")])
        assert rc == 1

    def test_lab_failures_no_failures(self, isolated_papergraph_dir, capsys):
        """lab failures prints 'none' when no failures recorded."""
        import research_companion.cli as cli

        rc = cli.main(["lab", "failures"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "none" in out.lower()

    def test_lab_failures_shows_recorded(self, isolated_papergraph_dir, capsys):
        """lab failures prints recorded failures."""
        import research_companion.cli as cli
        from research_companion import store

        store.record_failure("/path/to/paper.pdf", {
            "stage": "extract",
            "error": "connection timeout",
        })

        rc = cli.main(["lab", "failures"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "extract" in out
        assert "/path/to/paper.pdf" in out


# ---------------------------------------------------------------------------
# Fixture generation (run once to create the fixture file)
# ---------------------------------------------------------------------------

def _generate_fixture(fixture_path: Path) -> None:
    """Generate the lab_events.jsonl fixture from a synthetic 3-paper run
    (one failing at extract stage). Writes to fixture_path."""
    import os
    import tempfile

    fixture_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmpdir:
        # Override RESEARCH_COMPANION_DIR for isolated fixture generation
        old_env = os.environ.get("RESEARCH_COMPANION_DIR")
        rc_dir = Path(tmpdir) / "rc"
        rc_dir.mkdir()
        os.environ["RESEARCH_COMPANION_DIR"] = str(rc_dir)
        try:
            _run_fixture_generation(Path(tmpdir), fixture_path)
        finally:
            if old_env is None:
                del os.environ["RESEARCH_COMPANION_DIR"]
            else:
                os.environ["RESEARCH_COMPANION_DIR"] = old_env


def _fixture_fakes():
    """Return the canonical fake seams used for fixture generation and replay.

    scan_pdfs is also returned so callers can monkeypatch lab.scan_pdfs to
    return basename-only paths, keeping the fixture portable.
    """
    from research_companion import store as _store

    _ids = ["local:fixa", "local:fixb", "local:fixc"]
    _idx = [0]

    def add_pdf(path):
        idx = _idx[0]
        _idx[0] += 1
        pid = _ids[idx]
        meta = _make_meta(pid, title=f"Fixture Paper {idx+1}")
        meta.save()
        # Save stub text so get_paper_text() works without a real PDF
        _store.save_text(pid, f"{_GOOD_TEXT} Paper {pid}.")
        return meta

    def sectioner(paper_id, **kwargs):
        return [_fake_section("s1", "Introduction"), _fake_section("s2", "Methods")]

    def extractor(meta, *, provider="anthropic", model=None, force=False):
        # paper_b fails at extract
        if meta.paper_id == "local:fixb":
            raise RuntimeError("fixture extraction error")
        return (
            {
                "concepts": [{"name": "Test Concept", "section": "s1"}],
                "methods": [{"name": "Test Method", "section": "s2"}],
                "datasets": [],
                "claims": [],
                "results": [],
                "related_work": [],
            },
            {"input_tokens": 10, "output_tokens": 5, "cached": False},
        )

    def strengther(paper_id, **kwargs):
        return {"score": 0.6, "band": "moderate", "color": "#d29922"}

    # Deterministic basename-only scan: always returns the three synthetic papers
    # as bare filename Paths so IngestProgress.current is portable.
    def fake_scan(folder):
        return [Path("paper_a.pdf"), Path("paper_b.pdf"), Path("paper_c.pdf")]

    return add_pdf, sectioner, extractor, strengther, fake_scan


def _run_fixture_generation(tmp_path: Path, fixture_path: Path) -> None:
    """Internal: run synthetic ingest and capture events to fixture."""
    import research_companion.lab as _lab
    from research_companion.agents.bus import Bus
    from research_companion.agents.events import event_to_dict

    add_pdf, sectioner, extractor, strengther, fake_scan = _fixture_fakes()

    # Monkeypatch scan_pdfs so that path strings in events are basenames only.
    # This keeps the fixture free of machine-specific absolute temp paths.
    original_scan = _lab.scan_pdfs
    _lab.scan_pdfs = fake_scan
    try:
        bus = Bus()
        asyncio.run(
            ingest_folder(
                tmp_path,  # folder arg is ignored by fake_scan
                bus=bus,
                add_pdf=add_pdf,
                extractor=extractor,
                sectioner=sectioner,
                aligner=None,
                strengther=strengther,
                embedder=None,   # keep fixture stable: no embed events
                suggester=None,  # keep fixture stable: no suggestions events
            )
        )
    finally:
        _lab.scan_pdfs = original_scan

    with fixture_path.open("w", encoding="utf-8") as f:
        for event in bus.history:
            f.write(json.dumps(event_to_dict(event), ensure_ascii=False) + "\n")


# Run as script to regenerate fixture
if __name__ == "__main__":
    fixture_path = Path(__file__).parent / "fixtures" / "lab_events.jsonl"
    print(f"Generating fixture: {fixture_path}")
    _generate_fixture(fixture_path)
    print("Done.")
