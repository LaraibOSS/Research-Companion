"""Catch a PDF the user downloaded themselves, and attach it to the right paper.

Armed by a click, never running otherwise. The properties below are the reason
this design was chosen over a permanent watcher, so they are invariants:

  * nothing is read while disarmed
  * only files created AFTER the arming instant are considered
  * only *.pdf, and only page one, and only to find an identifier
  * a file that matches nothing is reported and otherwise untouched
  * nothing leaves the machine

Identification is three tiers, cheapest and most reliable first:

  1. an arXiv id or DOI embedded in the *filename* -- ACM in particular names
     its downloads after the DOI suffix ("3676641.3716025.pdf"), so this tier
     often wins outright without ever having to look inside the file.
  2. a DOI found on page one, for publishers (IEEE) whose filenames are
     opaque sequence numbers that identify nothing.
  3. the queued paper's title found on page one, via the longest-contiguous-
     run title matcher already hardened in ``refcheck.matching``.

Tiers 1 and 2 reuse the arXiv-id/DOI regexes from ``store.py`` verbatim -- do
not re-derive them here.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

from research_companion.refcheck.matching import title_is_cited
from research_companion.store import (
    _ARXIV_IN_NAME_RE,
    _DOI_IN_NAME_RE,
    make_arxiv_id,
    make_doi_id,
)

# Browsers write these while a download is still in flight and rename to the
# final name only on completion. A file still wearing one of these is not a
# PDF yet, no matter what comes before the suffix.
_IGNORED_SUFFIXES = (".crdownload", ".part", ".tmp", ".download")

# `_armed_since_wall` (time.time() at arm()) and a file's st_mtime (set by
# the OS at write time) are two separate clock reads a few microseconds
# apart; float rounding can make a file written AFTER arming compare as
# fractionally older. A tolerance well under any real "was this here before
# arming" gap (which is seconds to minutes, not microseconds) absorbs that
# noise without letting a genuinely pre-existing file slip through.
_MTIME_TOLERANCE = 0.05


def _ids_from_text(text: str) -> set[str]:
    """arXiv ids and DOIs findable in *text*, as full paper ids."""
    ids: set[str] = set()
    if not text:
        return ids
    for m in _ARXIV_IN_NAME_RE.finditer(text):
        ids.add(make_arxiv_id(m.group(1)))
    for m in _DOI_IN_NAME_RE.finditer(text):
        ids.add(make_doi_id(m.group(1)))
    return ids


def _queued_id(paper) -> str | None:
    return paper.get("paper_id") if isinstance(paper, dict) else None


def _queued_title(paper) -> str | None:
    return paper.get("title") if isinstance(paper, dict) else None


def _contains_as_whole_token(stem: str, needle: str) -> bool:
    """Is *needle* present in *stem* as a whole token -- bounded by the start/
    end of the string or a non-alphanumeric character on each side -- rather
    than merely as a substring? Guards against a short DOI suffix
    false-positiving inside an unrelated, longer filename."""
    pattern = r"(?<![A-Za-z0-9])" + re.escape(needle) + r"(?![A-Za-z0-9])"
    return re.search(pattern, stem) is not None


def _by_filename(filename, queued) -> str | None:
    """Tier 1: an identifier embedded in the filename itself."""
    if not filename:
        return None
    stem = re.sub(r"\.pdf$", "", str(filename), flags=re.IGNORECASE)
    # Filesystems can't hold a literal "/", so a DOI is sometimes written with
    # underscores standing in for it ("10.1145_3676641.3716025"); try both.
    candidates = _ids_from_text(stem) | _ids_from_text(stem.replace("_", "/"))
    for paper in queued:
        pid = _queued_id(paper)
        if not pid:
            continue
        if pid in candidates:
            return pid
        if pid.startswith("doi:"):
            doi = pid[len("doi:"):]
            suffix = doi.split("/", 1)[1] if "/" in doi else doi
            # ACM's own download names are the bare DOI suffix with no
            # prefix at all ("3676641.3716025.pdf") -- neither regex above
            # extracts that on its own, so also check whole-token containment
            # (bounded, not a raw substring match -- a short suffix must not
            # false-positive inside an unrelated, longer filename).
            if suffix and _contains_as_whole_token(stem, suffix):
                return pid
    return None


def _by_page1_identifier(page1_text, queued) -> str | None:
    """Tier 2: an arXiv id or DOI printed on page one."""
    candidates = _ids_from_text(page1_text)
    if not candidates:
        return None
    for paper in queued:
        pid = _queued_id(paper)
        if pid and pid in candidates:
            return pid
    return None


def _by_title(page1_text, queued) -> str | None:
    """Tier 3: the queued paper's title found on page one."""
    if not page1_text:
        return None
    for paper in queued:
        pid = _queued_id(paper)
        title = _queued_title(paper)
        if pid and title and title_is_cited(page1_text, title):
            return pid
    return None


def identify_pdf(filename, page1_text, queued) -> str | None:
    """Which queued paper is this file, if any? Three tiers, cheapest first."""
    try:
        queued = list(queued) if queued else []
        return (
            _by_filename(filename, queued)
            or _by_page1_identifier(page1_text, queued)
            or _by_title(page1_text, queued)
        )
    except Exception:  # noqa: BLE001 - identification must never crash the poll
        return None


def _default_read_page1(path: Path) -> str:
    """Read page index 0 ONLY -- no model, no network, and never the rest of
    the document. A file this watcher doesn't recognize is, by definition,
    something the user never asked it to look at (a bank statement, a private
    preprint); parsing the whole thing before discarding it would betray the
    one invariant this design exists to provide. ``research_companion.parsers``
    only exposes whole-document parsing (``get_parser().parse()`` loops over
    every page before returning), so this calls pypdfium2 directly for random
    single-page access, mirroring what ``parsers/pypdfium.py`` already does
    per page inside its own loop -- just for page 0 alone."""
    try:
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(str(path))
        try:
            if len(pdf) == 0:
                return ""
            text = pdf[0].get_textpage().get_text_range() or ""
        finally:
            pdf.close()
    except Exception:  # noqa: BLE001 - an unparseable PDF is not a crash
        return ""
    return text[:3000]


class ArmedWatcher:
    """Polls one directory for a hand-downloaded PDF, only while armed.

    ``now`` and ``read_page1`` are injected so tests need neither wall-clock
    time nor real PDFs. ``poll()`` does its own work synchronously and holds
    no thread -- the caller's own tick calls it.
    """

    def __init__(self, directory, *, now=time.monotonic, read_page1=None):
        # None means "no downloads directory is known". It is NOT the same as
        # the working directory: falling back to "." made an armed watcher
        # read page one of every new PDF in whatever directory the server
        # happened to be started from, invisibly. poll() returns nothing in
        # that state, and lab_api refuses to arm and says why.
        self.directory = Path(directory) if directory is not None else None
        self._now = now
        self._read_page1 = read_page1 if read_page1 is not None else _default_read_page1
        self._expiry: float | None = None
        self._armed_since_wall: float = 0.0
        self._paper_ids: set[str] = set()
        self._queued_by_id: dict[str, dict] = {}
        self._seen: dict[Path, dict] = {}

    def arm(self, paper_ids, ttl: float = 600, queued=()) -> None:
        """Arm (or re-arm) the watcher. Additive: extends the window and adds
        papers rather than replacing what is already armed. ``_armed_since_wall``
        (the mtime-eligibility cutoff) is set only on the disarmed-to-armed
        transition and stays put across a re-arm -- a file downloaded after
        the FIRST click of a session is still eligible, even once a second
        click has extended the window."""
        if not self.is_armed:
            self._armed_since_wall = time.time()
            self._seen = {}
        self._expiry = self._now() + ttl
        self._paper_ids |= {str(p) for p in paper_ids}
        for paper in queued or ():
            pid = _queued_id(paper)
            if pid:
                self._queued_by_id[pid] = paper

    def disarm(self) -> None:
        self._expiry = None
        self._paper_ids = set()
        self._queued_by_id = {}
        self._seen = {}

    @property
    def is_armed(self) -> bool:
        return self._expiry is not None and self._now() < self._expiry

    @property
    def seconds_left(self) -> float:
        if self._expiry is None:
            return 0.0
        return max(0.0, self._expiry - self._now())

    @property
    def armed_paper_ids(self) -> set:
        return set(self._paper_ids)

    def _is_pdf_candidate(self, name: str) -> bool:
        lower = name.lower()
        if lower.endswith(_IGNORED_SUFFIXES):
            return False
        return lower.endswith(".pdf")

    def poll(self) -> list[tuple[Path, str | None]]:
        """One synchronous look at the directory. Returns newly-settled PDFs
        as ``(path, paper_id_or_None)``. Reads nothing unless armed."""
        if not self.is_armed or self.directory is None:
            return []
        try:
            entries = list(self.directory.iterdir())
        except OSError:
            return []

        results: list[tuple[Path, str | None]] = []
        for path in entries:
            try:
                if not path.is_file():
                    continue
            except OSError:
                continue
            if not self._is_pdf_candidate(path.name):
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            if stat.st_mtime < self._armed_since_wall - _MTIME_TOLERANCE:
                continue

            size = stat.st_size
            prev = self._seen.get(path)
            if prev is None:
                self._seen[path] = {"size": size, "claimed": False}
                continue  # first sighting -- wait for a second poll to confirm size
            if prev["claimed"]:
                continue  # already reported once, never again
            if prev["size"] != size:
                prev["size"] = size
                continue  # still growing

            prev["claimed"] = True
            page1 = self._read_page1(path)
            queued = [
                paper
                for pid, paper in self._queued_by_id.items()
                if pid in self._paper_ids
            ]
            paper_id = identify_pdf(path.name, page1, queued)
            results.append((path, paper_id))
        return results

    def release(self, path: Path) -> None:
        """Un-claim *path* so a later poll() offers it again.

        For when a caller's own handling of a returned match fails after
        poll() already marked it claimed (e.g. the file was mid-write or
        briefly locked by an antivirus scan when the caller tried to read
        it) -- without this, that claim is permanent and the file is lost
        for the rest of the arming window, silently, since poll() never
        offers an already-claimed path again. Dropping the entry entirely
        (not just flipping ``claimed`` back to False) also drops the
        recorded size, so the size-stability check runs again from scratch
        rather than trusting a stale reading of a file that may still have
        been changing. A no-op if *path* isn't currently tracked."""
        self._seen.pop(path, None)
