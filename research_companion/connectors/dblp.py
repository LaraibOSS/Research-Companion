"""DBLP connector — the authoritative computer-science bibliography.

DBLP's free JSON publication API (no key) covers CS venues — workshop papers
and older proceedings included — better than the general sources. Metadata
only: no abstracts, no citation counts, no full text. Network is confined to
`_http_search`; parsers are pure.
"""
from __future__ import annotations

import re
from collections.abc import Callable

import httpx

from research_companion.connectors.base import USER_AGENT, RateLimiter
from research_companion.discover import DiscoveredPaper
from research_companion.refcheck import matching
from research_companion.refcheck.validate import Reference

SEARCH_API = "https://dblp.org/search/publ/api"
MATCH_FLOOR = 0.7
DBLP_MIN_INTERVAL_S = 1.0  # gentle: ~1 request/second (DBLP has no key system)

_ARXIV_RE = re.compile(r"arxiv\.org/abs/([\w./-]*[\w/])", re.IGNORECASE)
_ARXIV_DOI_RE = re.compile(r"10\.48550/arxiv\.([\w./-]*[\w/])", re.IGNORECASE)
_AUTHOR_SUFFIX_RE = re.compile(r"\s+\d{4}$")  # DBLP homonym tag, e.g. "Noam Shazeer 0001"


def _clean_author(author) -> str:
    text = author.get("text", "") if isinstance(author, dict) else str(author or "")
    return _AUTHOR_SUFFIX_RE.sub("", text).strip()


def _authors_list(info: dict) -> list[str]:
    authors = info.get("authors")
    authors = authors if isinstance(authors, dict) else {}
    authors = authors.get("author")
    if authors is None:
        return []
    if isinstance(authors, (dict, str)):
        authors = [authors]
    return [name for name in (_clean_author(a) for a in authors) if name]


def _arxiv_from_ee(ee) -> str | None:
    if ee is None:
        return None
    for url in (ee if isinstance(ee, list) else [ee]):
        m = _ARXIV_RE.search(str(url)) or _ARXIV_DOI_RE.search(str(url))
        if m:
            return m.group(1)
    return None


def _coerce_year(value) -> int | None:
    s = str(value or "").strip()
    return int(s) if s.isdigit() else None


def _hits_from_json(data) -> list[dict]:
    """Extract hits from DBLP JSON response, handling non-dict top-level.

    Returns [] if data is not a dict, or if any intermediate value is non-dict.
    DBLP returns a bare object for a single hit; we normalize to list.
    """
    if not isinstance(data, dict):
        return []
    result = data.get("result")
    if not isinstance(result, dict):
        return []
    hits = result.get("hits")
    if not isinstance(hits, dict):
        return []
    hit = hits.get("hit", [])
    if isinstance(hit, dict):  # single hit: normalize to list
        return [hit]
    return hit if isinstance(hit, list) else []


def parse_dblp_hit(hit: dict) -> dict:
    info = hit.get("info")
    info = info if isinstance(info, dict) else {}
    title = (info.get("title") or "").strip()
    if title.endswith("."):
        title = title[:-1]
    return {
        "title": title,
        "authors": _authors_list(info),
        "year": _coerce_year(info.get("year")),
        "doi": info.get("doi"),
        "arxiv_id": _arxiv_from_ee(info.get("ee")),
        "pmid": None,
        "pmcid": None,
    }


def dblp_url(hit: dict) -> str:
    info = hit.get("info")
    info = info if isinstance(info, dict) else {}
    return info.get("url") or "https://dblp.org/"


def _best(ref: Reference, hits: list[dict]) -> dict | None:
    best, score = None, -1.0
    for h in hits:
        rec = parse_dblp_hit(h)
        s = matching.title_similarity(ref.title, rec["title"])
        if s > score:
            best, score = rec, s
    return best if best is not None and score >= MATCH_FLOOR else None


def _http_search(query: str, *, rows: int = 10, timeout: float = 30.0) -> list[dict]:
    params = {"q": query, "format": "json", "h": rows}
    try:
        with httpx.Client(timeout=timeout, headers={"User-Agent": USER_AGENT}) as c:
            resp = c.get(SEARCH_API, params=params)
            resp.raise_for_status()
        return _hits_from_json(resp.json())
    except (httpx.HTTPError, ValueError):
        return []


class DBLPConnector:
    name = "dblp"

    def __init__(self, *, search: Callable[..., list[dict]] = _http_search,
                 limiter: RateLimiter | None = None) -> None:
        self._search = search
        self._limiter = limiter or RateLimiter(DBLP_MIN_INTERVAL_S)

    def resolve(self, ref: Reference) -> dict | None:
        self._limiter.wait()
        return _best(ref, self._search(ref.title))

    def search(self, query: str, *, limit: int) -> list[DiscoveredPaper]:
        self._limiter.wait()
        out: list[DiscoveredPaper] = []
        for h in self._search(query, rows=limit):
            rec = parse_dblp_hit(h)
            if not rec["title"]:
                continue
            out.append(DiscoveredPaper(
                title=rec["title"], authors=rec["authors"], year=rec["year"],
                citation_count=0, arxiv_id=rec["arxiv_id"], doi=rec["doi"],
                s2_id=None, url=dblp_url(h), abstract="",
                source="dblp", pmid=None, pmcid=None))
        return out[:limit]

    def fetch_fulltext(self, ident: str) -> str | None:
        return None
