"""Fetch papers from arXiv URLs or local PDF paths into the papergraph store.

arXiv flow:
    URL -> arxiv_id -> arxiv API for metadata -> download PDF -> store

Local PDF flow:
    Path -> read bytes -> sha256-derived ID -> read first-page metadata heuristically -> store

The arxiv API (export.arxiv.org/api/query) is free, no auth, returns Atom XML.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

import feedparser
import httpx

from papergraph.store import (
    PaperMetadata,
    make_arxiv_id,
    make_local_id,
    paper_dir,
    save_pdf,
)


ARXIV_ABS_RE = re.compile(
    r"arxiv\.org/(?:abs|pdf|html)/(?P<id>\d{4}\.\d{4,5})(?:v\d+)?",
    re.IGNORECASE,
)
ARXIV_API = "https://export.arxiv.org/api/query"
ARXIV_PDF_URL = "https://arxiv.org/pdf/{arxiv_id}.pdf"

USER_AGENT = "papergraph/0.1 (https://github.com/azizur1992/papergraph)"


class FetchError(RuntimeError):
    """Raised when a paper cannot be fetched."""


def parse_arxiv_id(url_or_id: str) -> str | None:
    """Extract a bare arXiv ID like '2410.05779' from a URL or raw ID string.

    Returns None if the input doesn't look like an arXiv reference.
    """
    s = url_or_id.strip()
    m = ARXIV_ABS_RE.search(s)
    if m:
        return m.group("id")
    # Bare ID like "2410.05779" or "2410.05779v3"
    if re.fullmatch(r"\d{4}\.\d{4,5}(?:v\d+)?", s):
        return re.sub(r"v\d+$", "", s)
    return None


def _arxiv_metadata(arxiv_id: str, *, timeout: float = 30.0) -> dict:
    """Query the arXiv API for one paper's metadata. Returns a dict (may be empty on miss)."""
    params = {"id_list": arxiv_id, "max_results": "1"}
    with httpx.Client(timeout=timeout, headers={"User-Agent": USER_AGENT}) as client:
        resp = client.get(ARXIV_API, params=params)
        resp.raise_for_status()
        feed = feedparser.parse(resp.text)
    if not feed.entries:
        return {}
    e = feed.entries[0]
    authors = [a.get("name", "") for a in getattr(e, "authors", [])]
    year = None
    published = e.get("published", "")
    if published:
        m = re.match(r"(\d{4})", published)
        if m:
            year = int(m.group(1))
    categories = [t.get("term", "") for t in getattr(e, "tags", [])]
    return {
        "title": (e.get("title", "") or "").strip().replace("\n", " "),
        "authors": authors,
        "year": year,
        "abstract": (e.get("summary", "") or "").strip().replace("\n", " "),
        "arxiv_categories": categories,
    }


def _download_pdf(url: str, *, timeout: float = 60.0) -> bytes:
    with httpx.Client(timeout=timeout, headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()
        if not resp.content:
            raise FetchError(f"empty PDF from {url}")
        if not resp.content.startswith(b"%PDF-"):
            raise FetchError(f"response from {url} does not look like a PDF")
        return resp.content


def add_arxiv(url_or_id: str) -> PaperMetadata:
    """Fetch an arXiv paper by URL or ID. Idempotent: skips download if already present."""
    arxiv_id = parse_arxiv_id(url_or_id)
    if arxiv_id is None:
        raise FetchError(f"could not parse arXiv ID from {url_or_id!r}")

    paper_id = make_arxiv_id(arxiv_id)

    # Idempotency: if metadata.json already exists, return it.
    existing = PaperMetadata.load(paper_id)
    if existing is not None and (paper_dir(paper_id) / "paper.pdf").exists():
        return existing

    meta_dict = _arxiv_metadata(arxiv_id)
    if not meta_dict:
        raise FetchError(f"arXiv API returned no entry for id {arxiv_id!r}")

    pdf_bytes = _download_pdf(ARXIV_PDF_URL.format(arxiv_id=arxiv_id))
    save_pdf(paper_id, pdf_bytes)

    meta = PaperMetadata(
        paper_id=paper_id,
        title=meta_dict["title"],
        authors=meta_dict["authors"],
        year=meta_dict["year"],
        abstract=meta_dict["abstract"],
        source_url=f"https://arxiv.org/abs/{arxiv_id}",
        arxiv_categories=meta_dict["arxiv_categories"],
        added_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    )
    meta.save()
    return meta


def add_local_pdf(path: Path | str, *, title: str | None = None,
                  authors: list[str] | None = None, year: int | None = None) -> PaperMetadata:
    """Add a local PDF. Title/authors/year are optional but recommended (no API to look them up)."""
    p = Path(path)
    if not p.exists():
        raise FetchError(f"PDF not found: {p}")
    pdf_bytes = p.read_bytes()
    if not pdf_bytes.startswith(b"%PDF-"):
        raise FetchError(f"file does not look like a PDF: {p}")

    paper_id = make_local_id(pdf_bytes)
    existing = PaperMetadata.load(paper_id)
    if existing is not None and (paper_dir(paper_id) / "paper.pdf").exists():
        return existing

    save_pdf(paper_id, pdf_bytes)

    meta = PaperMetadata(
        paper_id=paper_id,
        title=title or p.stem,
        authors=authors or [],
        year=year,
        abstract="",
        source_url=str(p.resolve()),
        added_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    )
    meta.save()
    return meta


def add_paper(url_or_path: str, **local_kwargs) -> PaperMetadata:
    """Single entry point: routes to arXiv or local-PDF path based on input shape.

    local_kwargs (title, authors, year) are forwarded only when the input is a local PDF.
    """
    if parse_arxiv_id(url_or_path) is not None:
        return add_arxiv(url_or_path)
    return add_local_pdf(url_or_path, **local_kwargs)
