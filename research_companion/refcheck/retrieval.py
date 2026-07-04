"""Authoritative-record retrievers for reference validation.

Each retriever resolves a Reference to a record dict
``{title, authors, year, doi, arxiv_id}`` (or None), suitable as the `lookup`
argument to :func:`research_companion.refcheck.validate.validate_reference`.

Network access is confined to small ``_*_search`` functions so tests can
monkeypatch them; the response parsers are pure.
"""
from __future__ import annotations

from collections.abc import Callable

import httpx

from research_companion.refcheck import matching
from research_companion.refcheck.validate import Reference

USER_AGENT = "research-companion/0.1 (https://github.com/azizur100389/research-companion)"
CROSSREF_SEARCH_API = "https://api.crossref.org/works"
OPENALEX_SEARCH_API = "https://api.openalex.org/works"

# Below this title-similarity, even the best candidate is not a plausible match.
MATCH_FLOOR = 0.7


def _year_from_date_parts(*candidates: dict) -> int | None:
    """Pull the year out of the first CrossRef-style date object that has one."""
    for date_obj in candidates:
        parts = (date_obj or {}).get("date-parts") or [[]]
        if parts and parts[0]:
            return parts[0][0]
    return None


def parse_crossref_item(item: dict) -> dict:
    """Map a CrossRef work item to a record dict. Pure; tolerant of missing keys."""
    title_list = item.get("title") or []
    title = title_list[0].strip() if title_list else ""

    authors = []
    for a in item.get("author", []):
        name = " ".join(p for p in (a.get("given", ""), a.get("family", "")) if p).strip()
        if name:
            authors.append(name)

    year = _year_from_date_parts(
        item.get("issued", {}),
        item.get("published", {}),
        item.get("published-print", {}),
        item.get("published-online", {}),
    )

    return {
        "title": title,
        "authors": authors,
        "year": year,
        "doi": item.get("DOI"),
        "arxiv_id": None,
    }


def _bare_doi(doi: str | None) -> str | None:
    """Strip a doi.org URL prefix, leaving the bare ``10.xxxx/...`` form."""
    if not doi:
        return None
    return doi.strip().replace("https://doi.org/", "").replace("http://doi.org/", "")


def parse_openalex_item(item: dict) -> dict:
    """Map an OpenAlex work to a record dict. Pure; tolerant of missing keys."""
    title = (item.get("title") or item.get("display_name") or "").strip()
    authors = [
        name
        for a in item.get("authorships", [])
        if (name := (a.get("author") or {}).get("display_name", "").strip())
    ]
    return {
        "title": title,
        "authors": authors,
        "year": item.get("publication_year"),
        "doi": _bare_doi(item.get("doi")),
        "arxiv_id": None,
    }


def _best_match(
    ref: Reference,
    items: list[dict],
    parser: Callable[[dict], dict],
    *,
    floor: float = MATCH_FLOOR,
) -> dict | None:
    """Parse candidates and return the record whose title best matches `ref`.

    Returns None if there are no candidates or the best title similarity is
    below `floor` (no plausible match).
    """
    best_record: dict | None = None
    best_score = -1.0
    for item in items:
        record = parser(item)
        score = matching.title_similarity(ref.title, record["title"])
        if score > best_score:
            best_score, best_record = score, record
    if best_record is None or best_score < floor:
        return None
    return best_record


def _crossref_search(query: str, *, rows: int = 5, timeout: float = 30.0) -> list[dict]:
    """Query the CrossRef bibliographic search endpoint. Returns [] on failure."""
    params = {"query.bibliographic": query, "rows": rows}
    headers = {"User-Agent": USER_AGENT}
    try:
        with httpx.Client(timeout=timeout, headers=headers) as client:
            resp = client.get(CROSSREF_SEARCH_API, params=params)
            resp.raise_for_status()
        return resp.json().get("message", {}).get("items", [])
    except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.HTTPError):
        return []


def crossref_lookup(
    ref: Reference,
    *,
    search: Callable[..., list[dict]] = _crossref_search,
) -> dict | None:
    """Resolve a Reference to an authoritative CrossRef record, or None."""
    items = search(ref.title)
    return _best_match(ref, items, parse_crossref_item)


def _openalex_search(query: str, *, rows: int = 5, timeout: float = 30.0) -> list[dict]:
    """Query the OpenAlex search endpoint. Returns [] on failure."""
    params = {"search": query, "per-page": rows}
    headers = {"User-Agent": USER_AGENT}
    try:
        with httpx.Client(timeout=timeout, headers=headers) as client:
            resp = client.get(OPENALEX_SEARCH_API, params=params)
            resp.raise_for_status()
        return resp.json().get("results", [])
    except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.HTTPError):
        return []


def openalex_lookup(
    ref: Reference,
    *,
    search: Callable[..., list[dict]] = _openalex_search,
) -> dict | None:
    """Resolve a Reference to an authoritative OpenAlex record, or None."""
    items = search(ref.title)
    return _best_match(ref, items, parse_openalex_item)


def chained_lookup(*retrievers: Callable[[Reference], dict | None]) -> Callable[[Reference], dict | None]:
    """Combine retrievers into one lookup that returns the first non-None hit."""
    def _lookup(ref: Reference) -> dict | None:
        for retriever in retrievers:
            record = retriever(ref)
            if record is not None:
                return record
        return None
    return _lookup


def default_lookup() -> Callable[[Reference], dict | None]:
    """The standard lookup: CrossRef first, then OpenAlex as fallback."""
    return chained_lookup(crossref_lookup, openalex_lookup)
