"""Bring a Zotero library in through Zotero's local API, read-only.

Zotero 7 and later serve the web API's paths on this machine, at
``http://localhost:23119/api/users/0/...``, once the user turns on
"Allow other applications on this computer to communicate with Zotero"
(Settings -> Advanced). No account, no cloud, no key. Zotero answers 403 while
that setting is off.

Nothing here writes to Zotero: every request is a GET.

The transport is injectable -- ``get(path, params) -> (status, headers, json)``
-- so the logic (status, pagination, what each item becomes, the import loop)
is tested without a running Zotero. The default transport is httpx against
``RESEARCH_COMPANION_ZOTERO_URL`` (default ``http://localhost:23119``) and does
not follow redirects, because the attachment ``/file`` endpoint answers with a
302 whose ``Location`` is the local file, and that location is what we want.

How an item is added, in order of preference (:func:`to_import_target`):

1. its arXiv id (from a ``10.48550/arXiv.*`` DOI, an ``arXiv:`` line in
   ``extra``, or an arxiv.org URL) -- the most reliable full-text source;
2. its DOI;
3. the PDF Zotero already holds for it;
4. otherwise its metadata alone, which is still a library entry and can be
   given a PDF later.

When a DOI or arXiv add ends without a PDF (a paywall, a refusing host) but
Zotero holds one, that PDF is used: the reader already has it.
"""
from __future__ import annotations

import os
import re
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

DEFAULT_URL = "http://localhost:23119"
USER_PREFIX = "/api/users/0"
PAGE_SIZE = 100
#: Safety bound on pagination: a misbehaving server that keeps answering full
#: pages must not keep the import running forever.
MAX_PAGES = 1000

#: Top-level entries that are not papers. Zotero can hold standalone notes,
#: attachments and annotations at the top of a library.
SKIP_ITEM_TYPES = frozenset({"note", "attachment", "annotation"})

ENABLE_HINT = ('In Zotero, open Settings → Advanced and tick "Allow other '
               'applications on this computer to communicate with Zotero".')

Transport = Callable[[str, dict | None], tuple[int, dict, Any]]


class ZoteroError(RuntimeError):
    """Zotero could not be read. The message is meant for a person."""


class ZoteroNotRunning(ZoteroError):
    """Nothing answered at the Zotero address."""


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------

def base_url() -> str:
    return (os.environ.get("RESEARCH_COMPANION_ZOTERO_URL", "").strip()
            or DEFAULT_URL).rstrip("/")


def http_get(path: str, params: dict | None = None, *,
             timeout: float = 15.0) -> tuple[int, dict, Any]:
    """The default transport: one GET to the local Zotero, no redirects.

    Raises ZoteroNotRunning when nothing is listening. A body that is not
    JSON comes back as None rather than raising, so a caller can still read
    the status and headers (the /file endpoint answers 302 with no JSON).
    """
    import httpx

    url = base_url() + path
    try:
        with httpx.Client(timeout=timeout, follow_redirects=False) as client:
            resp = client.get(url, params=params or None)
    except httpx.TransportError as exc:
        raise ZoteroNotRunning(
            f"Zotero is not running, or is not reachable at {base_url()}.") from exc
    try:
        body = resp.json()
    except ValueError:
        body = None
    return resp.status_code, dict(resp.headers), body


def _header(headers: dict, name: str) -> str | None:
    want = name.lower()
    for k, v in (headers or {}).items():
        if str(k).lower() == want:
            return v
    return None


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

def check(get: Transport | None = None) -> dict:
    """Can we read the user's Zotero library right now, and if not, why?

    Returns ``{state, ok, message, url}`` where state is one of
    ``ready``, ``disabled`` (Zotero is running but the local API is off),
    ``not_running`` or ``error``.
    """
    get = get or http_get
    url = base_url()
    try:
        status, _headers, _body = get(f"{USER_PREFIX}/collections", {"limit": 1})
    except ZoteroNotRunning:
        return {"state": "not_running", "ok": False, "url": url,
                "message": ("Zotero is not running. Open the Zotero desktop app "
                            "(version 7 or later) and try again.")}
    except Exception as exc:  # noqa: BLE001 -- any transport fault is "cannot read"
        return {"state": "error", "ok": False, "url": url,
                "message": f"Could not reach Zotero: {exc}"}
    if status == 200:
        return {"state": "ready", "ok": True, "url": url,
                "message": "Connected to Zotero."}
    if status == 403:
        return {"state": "disabled", "ok": False, "url": url,
                "message": ("Zotero is running, but it is not letting other "
                            "applications read the library. " + ENABLE_HINT)}
    if status == 404:
        return {"state": "error", "ok": False, "url": url,
                "message": ("Zotero answered, but without the local API. It "
                            "needs Zotero 7 or later. " + ENABLE_HINT)}
    return {"state": "error", "ok": False, "url": url,
            "message": f"Zotero answered with an unexpected status (HTTP {status})."}


def _require_ok(status: int, what: str) -> None:
    if status == 200:
        return
    if status == 403:
        raise ZoteroError("Zotero is not letting other applications read the "
                          "library. " + ENABLE_HINT)
    if status == 404:
        raise ZoteroError(f"Zotero could not find {what}.")
    raise ZoteroError(f"Zotero answered with HTTP {status} while reading {what}.")


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def _paged(get: Transport, path: str, what: str) -> list[dict]:
    out: list[dict] = []
    start = 0
    for _ in range(MAX_PAGES):
        status, headers, body = get(path, {"format": "json", "limit": PAGE_SIZE,
                                           "start": start})
        _require_ok(status, what)
        page = body if isinstance(body, list) else []
        out.extend(x for x in page if isinstance(x, dict))
        total_raw = _header(headers, "Total-Results")
        try:
            total = int(total_raw) if total_raw is not None else None
        except (TypeError, ValueError):
            total = None
        start += len(page)
        if not page or len(page) < PAGE_SIZE:
            break
        if total is not None and start >= total:
            break
    return out


def list_collections(get: Transport | None = None) -> list[dict]:
    """Every collection, as ``{key, name, parent, items}``, sorted by name."""
    get = get or http_get
    rows = []
    for c in _paged(get, f"{USER_PREFIX}/collections", "the collections"):
        data = c.get("data") or {}
        meta = c.get("meta") or {}
        key = c.get("key") or data.get("key")
        if not key:
            continue
        parent = data.get("parentCollection")
        rows.append({
            "key": str(key),
            "name": str(data.get("name") or key),
            "parent": str(parent) if parent else None,
            "items": meta.get("numItems"),
        })
    rows.sort(key=lambda r: r["name"].lower())
    return rows


def list_items(collection_key: str | None = None,
               get: Transport | None = None) -> list[dict]:
    """Top-level items of the library (or of one collection) that are papers.

    Notes, attachments and annotations sitting at the top level are skipped:
    they are not works that can be added.
    """
    get = get or http_get
    if collection_key:
        if not re.fullmatch(r"[A-Za-z0-9]+", collection_key):
            raise ZoteroError(f"{collection_key!r} is not a Zotero collection key.")
        path = f"{USER_PREFIX}/collections/{collection_key}/items/top"
        what = f"collection {collection_key}"
    else:
        path = f"{USER_PREFIX}/items/top"
        what = "the library"
    items = _paged(get, path, what)
    return [it for it in items
            if (it.get("data") or {}).get("itemType") not in SKIP_ITEM_TYPES]


def _file_url_to_path(url: str | None) -> Path | None:
    if not url or not isinstance(url, str):
        return None
    parsed = urlparse(url)
    if parsed.scheme != "file":
        return None
    raw = unquote(parsed.path)
    if parsed.netloc and parsed.netloc not in ("", "localhost"):
        raw = f"//{parsed.netloc}{raw}"
    try:
        return Path(url2pathname(raw))
    except (OSError, ValueError):
        return None


def find_pdf_attachment(item_key: str, get: Transport | None = None) -> Path | None:
    """The local PDF Zotero holds for this item, or None.

    Tries the attachment's ``links.enclosure.href`` and then the ``/file``
    endpoint's redirect. Only a ``file://`` location that exists on disk and
    ends in .pdf is accepted; anything else (a link-only attachment, a file
    Zotero has not synced down, an http location) is "no PDF", and the item
    is still imported by its identifier or its metadata.
    """
    get = get or http_get
    if not item_key or not re.fullmatch(r"[A-Za-z0-9]+", str(item_key)):
        return None
    try:
        status, _h, body = get(f"{USER_PREFIX}/items/{item_key}/children",
                               {"format": "json"})
    except ZoteroError:
        return None
    if status != 200 or not isinstance(body, list):
        return None
    for child in body:
        if not isinstance(child, dict):
            continue
        data = child.get("data") or {}
        if data.get("itemType") != "attachment":
            continue
        if data.get("contentType") != "application/pdf":
            continue
        candidates: list[str] = []
        href = ((child.get("links") or {}).get("enclosure") or {}).get("href")
        if href:
            candidates.append(href)
        akey = child.get("key") or data.get("key")
        if akey and re.fullmatch(r"[A-Za-z0-9]+", str(akey)):
            try:
                st, headers, _b = get(f"{USER_PREFIX}/items/{akey}/file", None)
            except ZoteroError:
                st, headers = 0, {}
            if st in (301, 302, 303, 307, 308):
                loc = _header(headers, "Location")
                if loc:
                    candidates.append(loc)
        for cand in candidates:
            path = _file_url_to_path(cand)
            if path is not None and path.suffix.lower() == ".pdf" and path.is_file():
                return path
    return None


# ---------------------------------------------------------------------------
# Planning: what each item becomes
# ---------------------------------------------------------------------------

_ARXIV_DOI_RE = re.compile(r"^10\.48550/arxiv\.(\d{4}\.\d{4,5})(?:v\d+)?$", re.IGNORECASE)
_ARXIV_EXTRA_RE = re.compile(r"arxiv:\s*(\d{4}\.\d{4,5})(?:v\d+)?", re.IGNORECASE)
_ARXIV_URL_RE = re.compile(r"arxiv\.org/(?:abs|pdf|html)/(\d{4}\.\d{4,5})(?:v\d+)?",
                           re.IGNORECASE)
_DOI_RE = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)?(10\.\d{4,9}/\S+)$",
                     re.IGNORECASE)
_YEAR_RE = re.compile(r"\b(1[5-9]\d{2}|20\d{2}|21\d{2})\b")


@dataclass
class ImportTarget:
    """How one Zotero item would be added. Nothing has been done yet."""

    key: str
    title: str
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    abstract: str = ""
    url: str = ""
    method: str = "metadata"        # "arxiv" | "doi" | "pdf" | "metadata"
    arxiv_id: str | None = None
    doi: str | None = None
    pdf_path: str | None = None

    def to_dict(self) -> dict:
        return {"key": self.key, "title": self.title, "authors": list(self.authors),
                "year": self.year, "method": self.method, "arxiv_id": self.arxiv_id,
                "doi": self.doi, "pdf_path": self.pdf_path}


def _creators(data: dict) -> list[str]:
    names = []
    for c in data.get("creators") or []:
        if not isinstance(c, dict):
            continue
        if c.get("creatorType") not in (None, "author", "contributor"):
            continue  # editors, translators, reviewers are not authors
        if c.get("name"):
            names.append(str(c["name"]).strip())
            continue
        full = " ".join(p for p in (str(c.get("firstName") or "").strip(),
                                    str(c.get("lastName") or "").strip()) if p)
        if full:
            names.append(full)
    return names


def _year(date: Any) -> int | None:
    m = _YEAR_RE.search(str(date or ""))
    return int(m.group(1)) if m else None


def _clean_doi(raw: Any) -> str | None:
    m = _DOI_RE.match(str(raw or "").strip())
    return m.group(1).rstrip(".") if m else None


def _arxiv_id(data: dict, doi: str | None) -> str | None:
    if doi:
        m = _ARXIV_DOI_RE.match(doi)
        if m:
            return m.group(1)
    m = _ARXIV_EXTRA_RE.search(str(data.get("extra") or ""))
    if m:
        return m.group(1)
    m = _ARXIV_URL_RE.search(str(data.get("url") or ""))
    if m:
        return m.group(1)
    return None


def to_import_target(item: dict, *, pdf_path: Path | str | None = None) -> ImportTarget:
    """Decide how this Zotero item would be added, without adding it.

    Pure: the caller looks up the attachment (``find_pdf_attachment``) and
    passes its path, so this decision is testable on item JSON alone.
    """
    data = item.get("data") or {}
    key = str(item.get("key") or data.get("key") or "")
    title = " ".join(str(data.get("title") or "").split())
    doi = _clean_doi(data.get("DOI"))
    arxiv = _arxiv_id(data, doi)
    target = ImportTarget(
        key=key,
        title=title,
        authors=_creators(data),
        year=_year(data.get("date")),
        abstract=str(data.get("abstractNote") or "").strip(),
        url=str(data.get("url") or "").strip(),
        doi=doi,
        arxiv_id=arxiv,
        pdf_path=str(pdf_path) if pdf_path else None,
    )
    if arxiv:
        target.method = "arxiv"
    elif doi:
        target.method = "doi"
    elif pdf_path:
        target.method = "pdf"
    else:
        target.method = "metadata"
    return target


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

def _library_duplicate(t: ImportTarget, papers: list) -> str | None:
    """A library paper that already holds this work, else None.

    Reuses the library dedup the citation auto-add loop uses
    (citations_coverage.find_library_duplicate): ids first, then title
    containment / similarity. The year is deliberately not passed: with it,
    the matcher's last-resort "same first-author surname and year" rule
    would treat two papers by one author in one year as the same work, and
    hide the second from the import.
    """
    from research_companion.citations_coverage import find_library_duplicate
    from research_companion.refcheck.validate import Reference

    ref = Reference(title=t.title, authors=[], year=None, doi=t.doi,
                    arxiv_id=t.arxiv_id, url=None, raw=t.title)
    return find_library_duplicate(ref, papers)


def _metadata_id(key: str) -> str:
    return f"zotero:{key}"


def _plan_one(t: ImportTarget, papers: list) -> tuple[str, str | None]:
    """(outcome, paper_id) for an item without doing anything.

    outcome is "already_in_library" or "new".
    """
    from research_companion import store

    if t.method == "metadata":
        mid = _metadata_id(t.key)
        if t.key and store.PaperMetadata.load(mid) is not None:
            return "already_in_library", mid
    dup = _library_duplicate(t, papers)
    if dup:
        return "already_in_library", dup
    if t.method == "pdf" and t.pdf_path:
        try:
            data = Path(t.pdf_path).read_bytes()
        except OSError:
            return "new", None
        dup = store.find_existing_paper_for(data, filename=Path(t.pdf_path).name)
        if dup:
            return "already_in_library", dup
    return "new", None


def _attach_zotero_pdf(paper_id: str, pdf_path: str | None) -> bool:
    """Give a just-added paper the PDF Zotero holds, if it ended without one."""
    from research_companion import store

    if not pdf_path or store.pdf_path(paper_id) is not None:
        return False
    try:
        data = Path(pdf_path).read_bytes()
    except OSError:
        return False
    if not data.startswith(b"%PDF-"):
        return False
    store.save_pdf(paper_id, data)
    return True


def _add_one(t: ImportTarget) -> tuple[str, str, bool]:
    """Add one planned item. Returns (outcome, paper_id, has_pdf)."""
    from research_companion import fetch, store

    if t.method == "arxiv":
        meta = fetch.add_arxiv(t.arxiv_id)
    elif t.method == "doi":
        meta = fetch.add_doi(t.doi)
    elif t.method == "pdf":
        meta = fetch.add_local_pdf(t.pdf_path, title=t.title or None,
                                   authors=t.authors or None, year=t.year)
    else:
        meta = store.PaperMetadata(
            paper_id=_metadata_id(t.key),
            title=t.title or "(untitled Zotero item)",
            authors=t.authors,
            year=t.year,
            abstract=t.abstract,
            source_url=t.url or (f"https://doi.org/{t.doi}" if t.doi else ""),
            parse_source="zotero",
        )
        meta.save()
        return "metadata_only", meta.paper_id, False
    if t.method in ("arxiv", "doi"):
        _attach_zotero_pdf(meta.paper_id, t.pdf_path)
    return "added", meta.paper_id, store.pdf_path(meta.paper_id) is not None


def import_items(items: list[dict], *, dry_run: bool,
                 get: Transport | None = None,
                 progress: Callable[[int, int, dict], None] | None = None) -> dict:
    """Add these Zotero items to the active library, one after another.

    Sequential on purpose: each DOI or arXiv add goes through the PDF
    acquisition chain, which is throttled per host, and parsing is bounded
    elsewhere. One item failing is recorded and the rest continue.

    With ``dry_run`` nothing is written anywhere: each row says what would
    happen. Zotero itself is only ever read.

    Returns ``{added, already_in_library, metadata_only, no_pdf, failed:
    [{title, reason}], total, dry_run, items: [...]}``. ``no_pdf`` counts the
    added papers that ended without a PDF, so "added" is never read as
    "readable".
    """
    from research_companion import store

    get = get or http_get
    report: dict[str, Any] = {"added": 0, "already_in_library": 0, "metadata_only": 0,
                              "no_pdf": 0, "failed": [], "total": len(items),
                              "dry_run": bool(dry_run), "items": []}
    papers = store.list_papers()
    for idx, item in enumerate(items):
        data = (item or {}).get("data") or {}
        title = " ".join(str(data.get("title") or "").split()) or "(untitled)"
        row: dict[str, Any] = {"title": title, "key": str((item or {}).get("key") or "")}
        try:
            pdf = find_pdf_attachment(row["key"], get) if row["key"] else None
            t = to_import_target(item, pdf_path=pdf)
            row.update({"method": t.method, "arxiv_id": t.arxiv_id, "doi": t.doi,
                        "has_zotero_pdf": bool(t.pdf_path)})
            outcome, pid = _plan_one(t, papers)
            if outcome == "already_in_library":
                report["already_in_library"] += 1
                row.update({"outcome": "already_in_library", "paper_id": pid})
            elif dry_run:
                kind = "metadata_only" if t.method == "metadata" else "added"
                report[kind] += 1
                row.update({"outcome": "would_add" if kind == "added"
                            else "would_add_metadata_only", "paper_id": None})
            else:
                outcome, pid, has_pdf = _add_one(t)
                report[outcome] += 1
                if outcome == "added" and not has_pdf:
                    report["no_pdf"] += 1
                row.update({"outcome": outcome, "paper_id": pid, "has_pdf": has_pdf})
                meta = store.PaperMetadata.load(pid)
                if meta is not None:
                    papers.append(meta)  # a later duplicate in this batch is caught
        except Exception as exc:  # noqa: BLE001 -- one item never stops the rest
            reason = str(exc) or exc.__class__.__name__
            report["failed"].append({"title": title, "reason": reason})
            row.update({"outcome": "failed", "reason": reason})
        report["items"].append(row)
        if progress is not None:
            # A progress display must never fail an import.
            with suppress(Exception):
                progress(idx + 1, len(items), row)
    return report
