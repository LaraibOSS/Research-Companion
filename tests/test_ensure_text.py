"""Deterministic checks must not require an LLM-costing ingest first.

statcheck/GRIM and self-overlap need nothing but the paper's text, and
extracting text is a local parse -- no model, no network, no cost. Only the
ingest path saved it though, so a freshly added local PDF failed both checks
with "no text for <id>. Add or ingest the paper first", sending the user to a
paid step to satisfy a free one.
"""
from __future__ import annotations

import json

import pytest

from research_companion import store
from research_companion.extract import ensure_text


def _add_paper(paper_id: str = "local:t1", *, pdf: bytes | None = None) -> None:
    store.PaperMetadata(paper_id=paper_id, title="T", authors=["A"],
                        added_at="2026-01-01T00:00:00Z").save()
    if pdf is not None:
        d = store.paper_dir(paper_id)
        (d / "paper.pdf").write_bytes(pdf)


def test_stored_text_is_returned_without_touching_the_parser(isolated_papergraph_dir, monkeypatch):
    _add_paper()
    store.save_text("local:t1", "already extracted")

    def boom():
        raise AssertionError("parser must not run when text is cached")

    monkeypatch.setattr("research_companion.parsers.get_parser", boom)
    assert ensure_text("local:t1") == "already extracted"


def test_text_is_parsed_on_demand_when_only_a_pdf_exists(isolated_papergraph_dir, monkeypatch):
    _add_paper(pdf=b"%PDF-1.4 fake")

    class _Doc:
        text = "Extracted body text."

    monkeypatch.setattr("research_companion.parsers.get_parser",
                        lambda: type("P", (), {"parse": lambda self, p: _Doc()})())
    assert ensure_text("local:t1") == "Extracted body text."
    # and it is cached, so the second call is free
    assert store.load_text("local:t1") == "Extracted body text."


def test_nothing_to_work_from_returns_none(isolated_papergraph_dir):
    _add_paper()                       # metadata only: no text, no PDF
    assert ensure_text("local:t1") is None
    assert ensure_text("local:missing") is None


def test_an_unparseable_pdf_is_not_a_crash(isolated_papergraph_dir, monkeypatch):
    _add_paper(pdf=b"not really a pdf")

    def explode():
        raise RuntimeError("corrupt")

    monkeypatch.setattr("research_companion.parsers.get_parser", explode)
    assert ensure_text("local:t1") is None


def test_an_empty_parse_is_not_cached_as_checked(isolated_papergraph_dir, monkeypatch):
    """A scanned PDF yields "" on the no-OCR default path. Caching that would
    remember the paper as "text extracted, genuinely empty" and every later
    check would silently pass on nothing."""
    _add_paper(pdf=b"%PDF-1.4 scan")

    class _Blank:
        text = "   "

    monkeypatch.setattr("research_companion.parsers.get_parser",
                        lambda: type("P", (), {"parse": lambda self, p: _Blank()})())
    assert ensure_text("local:t1") is None
    assert store.load_text("local:t1") is None


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cmd", ["check-stats", "check-overlap"])
def test_deterministic_checks_run_on_a_pdf_only_paper(isolated_papergraph_dir, monkeypatch,
                                                      capsys, cmd):
    from research_companion.cli import main

    _add_paper(pdf=b"%PDF-1.4 fake")

    class _Doc:
        text = "We report t(28) = 2.20, p = .04 across conditions."

    monkeypatch.setattr("research_companion.parsers.get_parser",
                        lambda: type("P", (), {"parse": lambda self, p: _Doc()})())

    assert main([cmd, "local:t1", "--json"]) == 0


def test_the_progress_notice_never_corrupts_json_stdout(isolated_papergraph_dir, monkeypatch,
                                                        capsys):
    """These commands support --json, so anything chatty must go to stderr."""
    from research_companion.cli import main

    _add_paper(pdf=b"%PDF-1.4 fake")

    class _Doc:
        text = "We report t(28) = 2.20, p = .04 across conditions."

    monkeypatch.setattr("research_companion.parsers.get_parser",
                        lambda: type("P", (), {"parse": lambda self, p: _Doc()})())

    main(["check-stats", "local:t1", "--json"])
    out = capsys.readouterr()
    json.loads(out.out)                       # stdout must be pure JSON
    assert "extracting text" in out.err       # the notice went to stderr


def test_a_genuinely_missing_paper_still_fails_with_a_useful_message(
        isolated_papergraph_dir, capsys):
    from research_companion.cli import main

    assert main(["check-stats", "local:nope", "--json"]) == 1
    err = capsys.readouterr().err
    assert "none could be extracted" in err
    # it must not send the user to a paid ingest for a free check
    assert "Add or ingest the paper first" not in err
