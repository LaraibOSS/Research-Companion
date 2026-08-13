"""Authoritative-record retrievers for reference validation.

Each retriever resolves a Reference to a record dict
``{title, authors, year, doi, arxiv_id}`` (or None), suitable as the `lookup`
argument to :func:`research_companion.refcheck.validate.validate_reference`.

Network access is confined to small ``_*_search`` functions so tests can
monkeypatch them; the response parsers are pure.
"""
from __future__ import annotations

from collections.abc import Callable
from contextvars import ContextVar

import httpx

from research_companion.refcheck import matching
from research_companion.refcheck.validate import Reference

USER_AGENT = "research-companion/0.1 (https://github.com/LaraibOSS/Research-Companion)"
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


# ---------------------------------------------------------------------------
# Transport-failure recording
#
# Every retriever below swallows network errors and returns None/[] so a lookup
# never explodes. That is the right behaviour, but it erases a distinction that
# matters: a resolver that ANSWERED "no record" is evidence, while one that was
# never reached is the absence of evidence. Callers that need to tell them apart
# activate this recorder; everything else is unaffected.
# ---------------------------------------------------------------------------

_transport_failures: ContextVar[list[str] | None] = ContextVar(
    "refcheck_transport_failures", default=None,
)


def _record_transport_failure(resolver: str, exc: BaseException) -> None:
    """Note that `resolver` could not be reached, when a caller is listening."""
    sink = _transport_failures.get()
    if sink is not None:
        sink.append(f"{resolver}: {type(exc).__name__}: {exc}")


def _crossref_search(query: str, *, rows: int = 5, timeout: float = 30.0) -> list[dict]:
    """Query the CrossRef bibliographic search endpoint. Returns [] on failure."""
    params = {"query.bibliographic": query, "rows": rows}
    headers = {"User-Agent": USER_AGENT}
    try:
        with httpx.Client(timeout=timeout, headers=headers) as client:
            resp = client.get(CROSSREF_SEARCH_API, params=params)
            resp.raise_for_status()
        return resp.json().get("message", {}).get("items", [])
    except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.HTTPError) as exc:
        _record_transport_failure("crossref", exc)
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
    except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.HTTPError) as exc:
        _record_transport_failure("crossref", exc)
        return []


def openalex_lookup(
    ref: Reference,
    *,
    search: Callable[..., list[dict]] = _openalex_search,
) -> dict | None:
    """Resolve a Reference to an authoritative OpenAlex record, or None."""
    items = search(ref.title)
    return _best_match(ref, items, parse_openalex_item)


ARXIV_API = "https://export.arxiv.org/api/query"


def _arxiv_fetch(arxiv_id: str, *, timeout: float = 30.0) -> dict | None:
    """Fetch title/authors/year for an arXiv id. Returns None on any failure."""
    import feedparser

    try:
        with httpx.Client(timeout=timeout, headers={"User-Agent": USER_AGENT}) as client:
            resp = client.get(ARXIV_API, params={"id_list": arxiv_id, "max_results": 1})
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        _record_transport_failure("openalex", exc)
        return None
    feed = feedparser.parse(resp.text)
    if not feed.entries:
        return None
    e = feed.entries[0]
    title = (e.get("title", "") or "").strip().replace("\n", " ")
    if not title:
        return None
    year = None
    published = e.get("published", "")
    if len(published) >= 4 and published[:4].isdigit():
        year = int(published[:4])
    return {"title": title,
            "authors": [a.get("name", "") for a in getattr(e, "authors", [])],
            "year": year}


def arxiv_lookup(
    ref: Reference,
    *,
    fetch: Callable[[str], dict | None] | None = None,
) -> dict | None:
    """Resolve a Reference by its arXiv id (identifier-based, no title search)."""
    if not ref.arxiv_id:
        return None
    record = (fetch or _arxiv_fetch)(ref.arxiv_id)
    if not record:
        return None
    return {"title": record.get("title", ""),
            "authors": record.get("authors", []),
            "year": record.get("year"),
            "doi": record.get("doi"),
            "arxiv_id": ref.arxiv_id}


def chained_lookup(*retrievers: Callable[[Reference], dict | None]) -> Callable[[Reference], dict | None]:
    """Combine retrievers into one lookup that returns the first non-None hit."""
    def _lookup(ref: Reference) -> dict | None:
        for retriever in retrievers:
            record = retriever(ref)
            if record is not None:
                return record
        return None
    return _lookup


def _settings_connectors() -> list[str]:
    """Enabled connector names from global settings; [] on any error (safe default)."""
    try:
        from research_companion.settings import get_settings
        val = get_settings().get("connectors", [])
        return list(val) if isinstance(val, list) else []
    except Exception:
        return []


def default_lookup(*, connectors=None) -> Callable[[Reference], dict | None]:
    """The standard lookup: arXiv → CrossRef → OpenAlex, then any enabled
    domain connectors. `connectors=None` reads the enabled list from settings;
    pass an explicit list (incl. []) to override (tests / CLI flag)."""
    names = _settings_connectors() if connectors is None else list(connectors)
    retrievers: list[Callable[[Reference], dict | None]] = [
        arxiv_lookup, crossref_lookup, openalex_lookup,
    ]
    if names:
        from research_companion.connectors import enabled_connectors
        retrievers.extend(conn.resolve for conn in enabled_connectors(names))
    return chained_lookup(*retrievers)


# ---------------------------------------------------------------------------
# Reachability-aware lookup
# ---------------------------------------------------------------------------

class LookupOutcome:
    """A lookup result that also says whether anything actually answered.

    ``any_reachable`` is False only when every resolver failed to complete —
    the case that must never be reported to a user as "no matching record
    found", because nothing was found *out*.
    """

    __slots__ = ("record", "any_reachable", "errors")

    def __init__(self, record: dict | None, any_reachable: bool,
                 errors: list[str] | None = None) -> None:
        self.record = record
        self.any_reachable = any_reachable
        self.errors = errors or []


def lookup_with_outcome(ref: Reference, *, lookup=None, connectors=None) -> LookupOutcome:
    """Run a lookup while recording whether any resolver was reachable.

    Existing callers of :func:`default_lookup` are untouched; this is the entry
    point for code that must distinguish "not found" from "could not check".
    """
    fn = lookup or default_lookup(connectors=connectors)
    sink: list[str] = []
    token = _transport_failures.set(sink)
    try:
        record = fn(ref)
    except Exception as exc:  # noqa: BLE001 — a lookup must never explode a caller
        _record_transport_failure("lookup", exc)
        record = None
    finally:
        _transport_failures.reset(token)

    if record is not None:
        return LookupOutcome(record, True, sink)
    # No record. Only call it authoritative if at least one resolver answered.
    return LookupOutcome(None, not sink, sink)
