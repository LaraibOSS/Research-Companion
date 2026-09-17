"""A parser failure must name its own cause.

Found in the wild: a valid 574,982-byte PDF, downloaded correctly, was recorded
as ``Failed to load document (PDFium: Data format error)``. The file was fine.
Docling had exhausted memory (26 x ``std::bad_alloc``), the subprocess wrapper
discarded its stderr and reported only an exit code, the caller fell back to
pypdfium, and pypdfium's own unrelated error became the recorded reason.

Three separate failures compounded: the real cause was thrown away, the
fallback aborted a whole document over one page, and the surviving message sent
the user to inspect a file that was not the problem.
"""
from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from research_companion.extract import _docling_failure_message
from research_companion.parsers.pypdfium import PypdfiumParser

# ---------------------------------------------------------------------------
# Out of memory must not read as malformed input
# ---------------------------------------------------------------------------

def _proc(returncode: int, stderr: bytes = b""):
    return SimpleNamespace(returncode=returncode, stderr=stderr)


def test_native_out_of_memory_is_named_as_such():
    """std::bad_alloc is what docling actually emitted in the real incident."""
    msg = _docling_failure_message(_proc(
        1, b"Stage preprocess failed for run 2, pages [10]: std::bad_alloc\n"))
    assert "out of memory" in msg.lower()
    assert "not corrupt" in msg.lower(), "must say the file is fine"


def test_oom_message_suggests_what_to_actually_do():
    msg = _docling_failure_message(_proc(1, b"std::bad_alloc"))
    assert "concurrent" in msg.lower() or "ocr" in msg.lower()


@pytest.mark.parametrize("stderr", [
    b"MemoryError",
    b"Cannot allocate memory",
    b"terminate called after throwing an instance of 'std::bad_alloc'",
])
def test_other_out_of_memory_signatures_are_recognised(stderr):
    assert "out of memory" in _docling_failure_message(_proc(1, stderr)).lower()


def test_a_process_killed_by_the_oom_killer_is_recognised_without_stderr():
    """SIGKILL leaves no message, and -9/137 is how it surfaces."""
    for code in (-9, 137):
        assert "out of memory" in _docling_failure_message(_proc(code)).lower()


def test_a_non_memory_failure_carries_its_own_stderr():
    """The point is to stop discarding the cause, not to blame memory for
    everything."""
    msg = _docling_failure_message(_proc(2, b"ImportError: no module named x\n"))
    assert "out of memory" not in msg.lower()
    assert "ImportError" in msg


def test_a_silent_failure_still_reports_the_exit_code():
    msg = _docling_failure_message(_proc(3))
    assert "exit 3" in msg


def test_building_the_message_never_raises():
    """This runs on an error path; it must not fail there."""
    for bad in (SimpleNamespace(returncode=1, stderr=None),
                SimpleNamespace(returncode=1, stderr=b"\xff\xfe invalid utf8")):
        assert isinstance(_docling_failure_message(bad), str)


# ---------------------------------------------------------------------------
# One bad page must not cost the whole document
# ---------------------------------------------------------------------------

class _Page:
    def __init__(self, text, ok=True):
        self._text, self._ok = text, ok

    def get_textpage(self):
        if not self._ok:
            raise RuntimeError("Failed to load page.")
        return SimpleNamespace(get_text_range=lambda: self._text)


class _Doc:
    """Stands in for pypdfium2.PdfDocument, including its habit of raising
    from inside iteration rather than at a page boundary."""

    def __init__(self, pages):
        self._pages = pages
        self.closed = False

    def __len__(self):
        return len(self._pages)

    def __getitem__(self, i):
        return self._pages[i]

    def __iter__(self):
        for p in self._pages:
            if not p._ok:
                raise RuntimeError("Failed to load page.")
            yield p

    def close(self):
        self.closed = True


def _parse_with(monkeypatch, doc):
    import sys

    fake = SimpleNamespace(PdfDocument=lambda path: doc)
    monkeypatch.setitem(sys.modules, "pypdfium2", fake)
    return PypdfiumParser().parse(Path("whatever.pdf"))


def test_a_readable_pdf_parses(monkeypatch):
    out = _parse_with(monkeypatch, _Doc([_Page("page one"), _Page("page two")]))
    assert "page one" in out.text and "page two" in out.text


def test_one_unreadable_page_does_not_lose_the_document(monkeypatch):
    """Under memory pressure the LATE pages fail — losing a forty-page paper
    over page 30 is what turned a partial parse into a total failure."""
    doc = _Doc([_Page("good one"), _Page("", ok=False), _Page("good two")])
    out = _parse_with(monkeypatch, doc)
    assert "good one" in out.text
    assert "good two" in out.text, "text after the bad page must survive"


def test_unreadable_pages_are_reported_not_hidden(monkeypatch):
    doc = _Doc([_Page("kept"), _Page("", ok=False)])
    out = _parse_with(monkeypatch, doc)
    assert out.meta.get("unreadable_pages") == 1
    assert out.meta.get("pages") == 2


def test_a_clean_parse_reports_no_unreadable_pages(monkeypatch):
    out = _parse_with(monkeypatch, _Doc([_Page("all good")]))
    assert not out.meta.get("unreadable_pages")


def test_the_document_is_always_closed(monkeypatch):
    doc = _Doc([_Page("x", ok=False)])
    _parse_with(monkeypatch, doc)
    assert doc.closed is True


def test_a_genuinely_unopenable_file_still_raises(monkeypatch):
    """The fix must not swallow the one case where the file really is bad."""
    import sys

    def boom(path):
        raise RuntimeError("Data format error")

    monkeypatch.setitem(sys.modules, "pypdfium2", SimpleNamespace(PdfDocument=boom))
    with pytest.raises(ValueError, match="could not open"):
        PypdfiumParser().parse(Path("broken.pdf"))


# ---------------------------------------------------------------------------
# The incident, pinned
# ---------------------------------------------------------------------------

def test_the_reported_message_no_longer_blames_the_file():
    """Regression for the exact wording that misled the investigation."""
    msg = _docling_failure_message(_proc(1, b"std::bad_alloc"))
    assert not re.search(r"data format|corrupt file|invalid pdf", msg, re.I)
