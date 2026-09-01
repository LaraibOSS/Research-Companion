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
            # extracts that on its own, so also check plain containment.
            if suffix and suffix in stem:
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
    """Parse *path* locally -- no model, no network -- and return roughly its
    first page. Mirrors what ``extract.ensure_text`` does under the hood
    (``get_parser().parse(pdf).text``), but works on a bare filesystem path
    rather than a library paper id: the file isn't a library entry yet, and
    identifying it must not write anything to the store."""
    try:
        from research_companion.parsers import get_parser

        text = get_parser().parse(Path(path)).text or ""
    except Exception:  # noqa: BLE001 - an unparseable PDF is not a crash
        return ""
    return text[:3000]


class ArmedWatcher:
    """Polls one directory for a hand-downloaded PDF, only while armed.

    ``now`` and ``read_page1`` are injected so tests need neither wall-clock
    time nor real PDFs. ``poll()`` does its own work synchronously and holds
    no thread -- the caller's own tick calls it.
    """

    # A file discovered this long (per the injected clock) after arming is
    # trusted on sight: the user was off in their browser downloading it, so
    # by the time this tick got around to looking, the write was long since
    # done. A file that shows up in the SAME instant we armed gets no such
    # benefit of the doubt -- it might still be mid-write -- and has to prove
    # itself stable across a second poll instead.
    _SETTLE_GRACE = 0.5

    def __init__(self, directory, *, now=time.monotonic, read_page1=None):
        self.directory = Path(directory)
        self._now = now
        self._read_page1 = read_page1 if read_page1 is not None else _default_read_page1
        self._expiry: float | None = None
        self._armed_since_wall: float = 0.0
        self._armed_at: float = 0.0
        self._paper_ids: set[str] = set()
        self._queued_by_id: dict[str, dict] = {}
        self._seen: dict[Path, dict] = {}

    def arm(self, paper_ids, ttl: float = 600, queued=()) -> None:
        """Arm (or re-arm) the watcher. Additive: extends the window and adds
        papers rather than replacing what is already armed."""
        if not self.is_armed:
            self._armed_since_wall = time.time()
            self._armed_at = self._now()
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
        if not self.is_armed:
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
            if stat.st_mtime < self._armed_since_wall:
                continue

            size = stat.st_size
            prev = self._seen.get(path)
            if prev is None:
                already_settled = (self._now() - self._armed_at) >= self._SETTLE_GRACE
                self._seen[path] = {"size": size, "claimed": False}
                if not already_settled:
                    continue  # first sighting -- wait for a second, matching poll
                prev = self._seen[path]
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
