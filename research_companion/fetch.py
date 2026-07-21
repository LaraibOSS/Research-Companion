"""Fetch papers from arXiv URLs, DOIs, Semantic Scholar, PubMed/PMC, or local PDF paths.

arXiv flow:
    URL -> arxiv_id -> arxiv API for metadata -> download PDF -> store

DOI flow:
    URL/DOI string -> doi -> Crossref API for metadata -> try PDF download -> store

Semantic Scholar flow:
    URL/ID -> s2_id -> S2 API for metadata -> try PDF via DOI/arXiv -> store

PubMed / PMC flow:
    PMID/PMCID -> Europe PMC + PubMed APIs for metadata -> fetch fulltext from PMC -> store

Local PDF flow:
    Path -> read bytes -> sha256-derived ID -> read first-page metadata heuristically -> store

The arxiv API (export.arxiv.org/api/query) is free, no auth, returns Atom XML.
The Crossref API (api.crossref.org) is free, no auth, returns JSON.
The Semantic Scholar API (api.semanticscholar.org) is free, no auth, returns JSON.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

import feedparser
import httpx

from research_companion.oa_locator import locate_pdf
from research_companion.store import (
    PaperMetadata,
    find_existing_paper_for,
    make_arxiv_id,
    make_doi_id,
    make_local_id,
    make_pmcid_id,
    make_pmid_id,
    make_s2_id,
    paper_dir,
    save_pdf,
    save_text,
)

ARXIV_ABS_RE = re.compile(
    r"arxiv\.org/(?:abs|pdf|html)/(?P<id>\d{4}\.\d{4,5})(?:v\d+)?",
    re.IGNORECASE,
)
ARXIV_API = "https://export.arxiv.org/api/query"
ARXIV_PDF_URL = "https://arxiv.org/pdf/{arxiv_id}.pdf"

DOI_RE = re.compile(r"10\.\d{4,9}/[^\s]+")
DOI_URL_RE = re.compile(
    r"https?://(?:dx\.)?doi\.org/(?P<doi>10\.\d{4,9}/[^\s]+)",
    re.IGNORECASE,
)
CROSSREF_API = "https://api.crossref.org/works/{doi}"

S2_URL_RE = re.compile(
    r"semanticscholar\.org/paper/[^/]*/(?P<id>[0-9a-f]{40})",
    re.IGNORECASE,
)
S2_HEX_RE = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
S2_API = "https://api.semanticscholar.org/graph/v1/paper/{s2_id}"

PUBMED_URL_RE = re.compile(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d{4,9})")

USER_AGENT = "research-companion (https://github.com/Laraib-Hasan-Future/Research-Companion)"


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
    try:
        with httpx.Client(timeout=timeout, headers={"User-Agent": USER_AGENT}) as client:
            resp = client.get(ARXIV_API, params=params)
            resp.raise_for_status()
            feed = feedparser.parse(resp.text)
    except httpx.HTTPError as exc:
        raise FetchError(f"arXiv API request failed for {arxiv_id}: {exc}") from exc
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
    from research_companion.net import MAX_DOWNLOAD_BYTES, MAX_REDIRECTS, UrlNotAllowed, validate_public_url
    current = url
    try:
        with httpx.Client(timeout=timeout, headers={"User-Agent": USER_AGENT},
                          follow_redirects=False) as client:
            for _ in range(MAX_REDIRECTS + 1):
                validate_public_url(current)          # re-validate EVERY hop
                with client.stream("GET", current) as resp:
                    if resp.is_redirect:
                        loc = resp.headers.get("location")
                        if not loc:
                            raise FetchError(f"redirect without Location from {current}")
                        current = str(resp.url.join(loc))
                        continue
                    resp.raise_for_status()
                    declared = resp.headers.get("content-length")
                    if declared and declared.isdigit() and int(declared) > MAX_DOWNLOAD_BYTES:
                        raise FetchError(f"PDF exceeds size cap ({MAX_DOWNLOAD_BYTES} bytes): {url}")
                    chunks: list[bytes] = []
                    total = 0
                    for chunk in resp.iter_bytes():
                        total += len(chunk)
                        if total > MAX_DOWNLOAD_BYTES:
                            raise FetchError(f"PDF exceeds size cap ({MAX_DOWNLOAD_BYTES} bytes): {url}")
                        chunks.append(chunk)
                    body = b"".join(chunks)
                    if not body:
                        raise FetchError(f"empty PDF from {url}")
                    if not body.startswith(b"%PDF-"):
                        raise FetchError(f"response from {url} does not look like a PDF")
                    return body
            raise FetchError(f"too many redirects for {url}")
    except UrlNotAllowed as exc:
        raise FetchError(str(exc)) from exc
    except httpx.HTTPError as exc:
        raise FetchError(f"download failed for {url}: {exc}") from exc


def _try_download_pdf(url: str, *, timeout: float = 60.0) -> bytes | None:
    """Attempt to download a PDF, returning None on failure instead of raising."""
    try:
        return _download_pdf(url, timeout=timeout)
    except (httpx.HTTPStatusError, httpx.TimeoutException, FetchError):
        return None


def _strip_html_tags(text: str) -> str:
    """Remove HTML/JATS tags from a string (e.g. Crossref abstracts)."""
    return re.sub(r"<[^>]+>", "", text).strip()


# ---------------------------------------------------------------------------
# DOI / Crossref
# ---------------------------------------------------------------------------


def parse_doi(url_or_doi: str) -> str | None:
    """Extract a DOI from a raw DOI string or a doi.org / dx.doi.org URL.

    Returns None if the input doesn't look like a DOI.
    """
    s = url_or_doi.strip()
    # Try URL form first (more specific).
    m = DOI_URL_RE.search(s)
    if m:
        return m.group("doi")
    # Bare DOI like "10.1145/1234567.1234568"
    m = DOI_RE.match(s)
    if m:
        return m.group(0)
    return None


def _doi_metadata(doi: str, *, timeout: float = 30.0) -> dict:
    """Query the Crossref API for metadata about a DOI. Returns empty dict on miss."""
    url = CROSSREF_API.format(doi=doi)
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    try:
        with httpx.Client(timeout=timeout, headers=headers) as client:
            resp = client.get(url)
            resp.raise_for_status()
    except (httpx.HTTPStatusError, httpx.TimeoutException):
        return {}

    data = resp.json()
    message = data.get("message", {})

    title_list = message.get("title", [])
    title = title_list[0].strip() if title_list else ""

    authors = []
    for a in message.get("author", []):
        given = a.get("given", "")
        family = a.get("family", "")
        name = f"{given} {family}".strip()
        if name:
            authors.append(name)

    year = None
    for date_key in ("published-print", "created"):
        date_info = message.get(date_key, {})
        parts = date_info.get("date-parts", [[]])
        if parts and parts[0] and parts[0][0]:
            year = int(parts[0][0])
            break

    abstract = _strip_html_tags(message.get("abstract", ""))

    return {
        "title": title,
        "authors": authors,
        "year": year,
        "abstract": abstract,
    }


def add_doi(url_or_doi: str) -> PaperMetadata:
    """Fetch a paper by DOI. Idempotent: skips download if already present."""
    doi = parse_doi(url_or_doi)
    if doi is None:
        raise FetchError(f"could not parse DOI from {url_or_doi!r}")

    paper_id = make_doi_id(doi)

    # Idempotency: if metadata.json already exists, return it.
    existing = PaperMetadata.load(paper_id)
    if existing is not None:
        return existing

    meta_dict = _doi_metadata(doi)
    if not meta_dict:
        raise FetchError(f"Crossref API returned no entry for DOI {doi!r}")

    # Try to download the PDF by following the DOI URL (may be paywalled).
    doi_url = f"https://doi.org/{doi}"
    pdf_bytes = _try_download_pdf(doi_url)
    if pdf_bytes is None:
        # Direct DOI fetch failed (usually a paywalled landing page). Ask the
        # open-access aggregators before giving up.
        _stub = PaperMetadata(paper_id=paper_id, title=meta_dict["title"],
                              authors=meta_dict["authors"], year=meta_dict["year"])
        _loc = locate_pdf(_stub)
        if _loc.pdf_url:
            pdf_bytes = _try_download_pdf(_loc.pdf_url)
    if pdf_bytes is not None:
        save_pdf(paper_id, pdf_bytes)
    else:
        print(f"warning: could not download PDF for DOI {doi} "
              f"(likely paywalled). Metadata saved, but text extraction "
              f"will not work without a PDF.")

    meta = PaperMetadata(
        paper_id=paper_id,
        title=meta_dict["title"],
        authors=meta_dict["authors"],
        year=meta_dict["year"],
        abstract=meta_dict["abstract"],
        source_url=doi_url,
        added_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    )
    meta.save()
    return meta


# ---------------------------------------------------------------------------
# Semantic Scholar
# ---------------------------------------------------------------------------


def parse_s2_id(url_or_id: str) -> str | None:
    """Extract a Semantic Scholar paper ID from a URL or raw 40-char hex ID.

    Returns None if the input doesn't look like an S2 reference.
    """
    s = url_or_id.strip()
    m = S2_URL_RE.search(s)
    if m:
        return m.group("id")
    if S2_HEX_RE.fullmatch(s):
        return s
    return None


def _s2_metadata(s2_id: str, *, timeout: float = 30.0) -> dict:
    """Query the Semantic Scholar API for one paper. Returns empty dict on miss."""
    url = S2_API.format(s2_id=s2_id)
    params = {"fields": "title,authors,year,abstract,externalIds"}
    headers = {"User-Agent": USER_AGENT}
    try:
        with httpx.Client(timeout=timeout, headers=headers) as client:
            resp = client.get(url, params=params)
            resp.raise_for_status()
    except (httpx.HTTPStatusError, httpx.TimeoutException):
        return {}

    data = resp.json()
    authors = [a.get("name", "") for a in data.get("authors", [])]
    return {
        "title": (data.get("title") or "").strip(),
        "authors": authors,
        "year": data.get("year"),
        "abstract": (data.get("abstract") or "").strip(),
        "external_ids": data.get("externalIds", {}),
    }


def add_s2(url_or_id: str) -> PaperMetadata:
    """Fetch a paper by Semantic Scholar ID or URL. Idempotent."""
    s2_id = parse_s2_id(url_or_id)
    if s2_id is None:
        raise FetchError(f"could not parse Semantic Scholar ID from {url_or_id!r}")

    paper_id = make_s2_id(s2_id)

    # Idempotency: if metadata.json already exists, return it.
    existing = PaperMetadata.load(paper_id)
    if existing is not None:
        return existing

    meta_dict = _s2_metadata(s2_id)
    if not meta_dict:
        raise FetchError(f"Semantic Scholar API returned no entry for ID {s2_id!r}")

    # Try to get a PDF: prefer arXiv, then DOI, then give up gracefully.
    pdf_bytes = None
    source_url = f"https://www.semanticscholar.org/paper/{s2_id}"
    ext_ids = meta_dict.get("external_ids", {})

    arxiv_ext = ext_ids.get("ArXiv")
    doi_ext = ext_ids.get("DOI")

    if arxiv_ext:
        pdf_bytes = _try_download_pdf(ARXIV_PDF_URL.format(arxiv_id=arxiv_ext))
    if pdf_bytes is None and doi_ext:
        pdf_bytes = _try_download_pdf(f"https://doi.org/{doi_ext}")

    if pdf_bytes is None:
        # Direct arXiv/DOI attempts failed. Ask the open-access aggregators
        # before giving up.
        _stub = PaperMetadata(paper_id=paper_id, title=meta_dict["title"],
                              authors=meta_dict["authors"], year=meta_dict["year"])
        _loc = locate_pdf(_stub)
        if _loc.pdf_url:
            pdf_bytes = _try_download_pdf(_loc.pdf_url)

    if pdf_bytes is not None:
        save_pdf(paper_id, pdf_bytes)
    else:
        print(f"warning: could not download PDF for S2 paper {s2_id}. "
              f"Metadata saved, but text extraction will not work without a PDF.")

    meta = PaperMetadata(
        paper_id=paper_id,
        title=meta_dict["title"],
        authors=meta_dict["authors"],
        year=meta_dict["year"],
        abstract=meta_dict["abstract"],
        source_url=source_url,
        added_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    )
    meta.save()
    return meta


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


def add_local_pdf_bytes(pdf_bytes: bytes, *, source: str = "", title: str | None = None,
                        authors: list[str] | None = None,
                        year: int | None = None) -> PaperMetadata:
    """Bytes-based core shared by add_local_pdf and the Lab's upload endpoint.

    `source` is a human-readable origin (a resolved path or upload://<filename>)
    stored as source_url and used in error messages.
    """
    if not pdf_bytes or not pdf_bytes.startswith(b"%PDF-"):
        raise FetchError(f"file does not look like a PDF: {source or '<bytes>'}")

    # Dedup across id namespaces: the same work may already be in the library as
    # an arXiv/DOI paper (added via URL) or an identical local copy. Reuse it
    # instead of creating a second entry.
    existing_id = find_existing_paper_for(pdf_bytes, filename=source)
    if existing_id is not None:
        existing = PaperMetadata.load(existing_id)
        if existing is not None:
            return existing

    paper_id = make_local_id(pdf_bytes)
    save_pdf(paper_id, pdf_bytes)

    meta = PaperMetadata(
        paper_id=paper_id,
        title=title or "Uploaded PDF",
        authors=authors or [],
        year=year,
        abstract="",
        source_url=source,
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
    return add_local_pdf_bytes(
        p.read_bytes(),
        source=str(p.resolve()),
        title=title or p.stem,
        authors=authors,
        year=year,
    )


# ---------------------------------------------------------------------------
# PubMed / PMC (Europe PMC + PubMed connectors)
# ---------------------------------------------------------------------------


def parse_pubmed_id(url_or_id: str) -> tuple[str, str] | None:
    """Return ("pmid"|"pmcid", value) for a PubMed/PMC input, else None."""
    s = url_or_id.strip()
    if s.lower().startswith("pmid:"):
        return ("pmid", s.split(":", 1)[1].strip())
    if s.lower().startswith("pmcid:"):
        return ("pmcid", s.split(":", 1)[1].strip().upper())
    m = PUBMED_URL_RE.search(s)
    if m:
        return ("pmid", m.group(1))
    if re.fullmatch(r"PMC\d{4,9}", s, re.IGNORECASE):
        return ("pmcid", s.upper())
    return None


def add_pubmed(url_or_id: str, *, resolve=None, fetch_text=None) -> PaperMetadata:
    """Ingest a paper by PMID/PMCID. resolve/fetch_text are injectable seams
    (default to the Europe PMC + PubMed connectors)."""
    parsed = parse_pubmed_id(url_or_id)
    if parsed is None:
        raise FetchError(f"could not parse a PubMed id from {url_or_id!r}")
    kind, value = parsed

    # Idempotency for pmid inputs: the canonical id is known without a network call.
    if kind == "pmid":
        existing = PaperMetadata.load(make_pmid_id(value))
        if existing is not None:
            return existing
    # (pmcid-only inputs still resolve first, since the canonical id prefers pmid.)

    if resolve is None or fetch_text is None:
        from research_companion.connectors.europepmc import EuropePMCConnector
        from research_companion.connectors.pubmed import PubMedConnector
        from research_companion.refcheck.validate import Reference
        epmc = EuropePMCConnector()
        pm = PubMedConnector()

        def _default_resolve(ident: str) -> dict | None:
            ref = Reference(title="", pmid=value if kind == "pmid" else None,
                            pmcid=value if kind == "pmcid" else None)
            return pm.resolve(ref) or epmc.resolve(ref)
        resolve = resolve or _default_resolve
        fetch_text = fetch_text or (lambda pmcid: epmc.fetch_fulltext(pmcid))

    rec = resolve(value)
    if not rec:
        raise FetchError(f"no record found for {url_or_id!r}")

    paper_id = make_pmid_id(rec["pmid"]) if rec.get("pmid") else make_pmcid_id(rec.get("pmcid") or value)
    existing = PaperMetadata.load(paper_id)
    if existing is not None:
        return existing

    full_text = None
    if rec.get("pmcid"):
        full_text = fetch_text(rec["pmcid"])
    if full_text:
        save_text(paper_id, full_text)

    meta = PaperMetadata(
        paper_id=paper_id,
        title=rec["title"],
        authors=rec.get("authors", []),
        year=rec.get("year"),
        abstract=rec.get("abstract", ""),
        source_url=f"https://pubmed.ncbi.nlm.nih.gov/{rec['pmid']}/" if rec.get("pmid") else "",
        added_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        pmid=rec.get("pmid"),
        pmcid=rec.get("pmcid"),
        full_text_available=bool(full_text),
    )
    meta.save()
    return meta


def add_paper(url_or_path: str, **local_kwargs) -> PaperMetadata:
    """Single entry point: routes to arXiv, DOI, S2, PubMed/PMC, or local-PDF based on input shape.

    local_kwargs (title, authors, year) are forwarded only when the input is a local PDF.
    """
    if parse_arxiv_id(url_or_path) is not None:
        return add_arxiv(url_or_path)
    if parse_doi(url_or_path) is not None:
        return add_doi(url_or_path)
    if parse_s2_id(url_or_path) is not None:
        return add_s2(url_or_path)
    if parse_pubmed_id(url_or_path) is not None:
        return add_pubmed(url_or_path)
    return add_local_pdf(url_or_path, **local_kwargs)
