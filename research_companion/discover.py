"""Paper discovery via Semantic Scholar APIs.

Two modes:
    topic search  — find papers on a topic, ranked by citation count + relevance
    expand        — follow citations/references of existing papers to find gaps

All APIs are free, no auth required. Rate limit: ~100 req/5min without a key.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from research_companion.store import list_papers

S2_SEARCH = "https://api.semanticscholar.org/graph/v1/paper/search"
S2_PAPER = "https://api.semanticscholar.org/graph/v1/paper"
S2_FIELDS = "title,authors,year,abstract,citationCount,externalIds,url"
S2_REF_FIELDS = "title,authors,year,citationCount,externalIds,url"
USER_AGENT = "research-companion/0.1 (https://github.com/azizur100389/research-companion)"

_HEADERS = {"User-Agent": USER_AGENT}
_TIMEOUT = 30.0


@dataclass
class DiscoveredPaper:
    """A paper found via discovery (not yet in the local store)."""
    title: str
    authors: list[str]
    year: int | None
    citation_count: int
    arxiv_id: str | None
    doi: str | None
    s2_id: str | None
    url: str
    abstract: str = ""
    source: str = ""  # how it was discovered: "search", "reference", "citation"

    @property
    def add_cmd(self) -> str:
        """Suggested `research-companion add` command for this paper."""
        if self.arxiv_id:
            return f"research-companion add {self.arxiv_id}"
        if self.doi:
            return f"research-companion add {self.doi}"
        if self.s2_id:
            return f"research-companion add {self.s2_id}"
        return f"research-companion add {self.url}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "authors": self.authors,
            "year": self.year,
            "citation_count": self.citation_count,
            "arxiv_id": self.arxiv_id,
            "doi": self.doi,
            "url": self.url,
            "abstract": self.abstract,
            "source": self.source,
            "add_cmd": self.add_cmd,
        }


def _parse_s2_paper(data: dict, *, source: str = "") -> DiscoveredPaper | None:
    """Parse a Semantic Scholar API response into a DiscoveredPaper."""
    title = (data.get("title") or "").strip()
    if not title:
        return None
    authors = [a.get("name", "") for a in (data.get("authors") or [])]
    ext_ids = data.get("externalIds") or {}
    return DiscoveredPaper(
        title=title,
        authors=authors,
        year=data.get("year"),
        citation_count=data.get("citationCount") or 0,
        arxiv_id=ext_ids.get("ArXiv"),
        doi=ext_ids.get("DOI"),
        s2_id=data.get("paperId"),
        url=data.get("url") or "",
        abstract=(data.get("abstract") or "").strip(),
        source=source,
    )


# ---------------------------------------------------------------------------
# Existing paper IDs — used to filter out papers already in the store
# ---------------------------------------------------------------------------

def _existing_ids() -> set[str]:
    """Return a set of identifiers for papers already in the local store.

    Includes paper_id, normalized arXiv IDs, and DOIs for dedup.
    """
    ids: set[str] = set()
    for meta in list_papers():
        ids.add(meta.paper_id)
        ids.add(meta.title.lower().strip())
        # Extract arXiv ID from paper_id.
        if meta.paper_id.startswith("arxiv:"):
            ids.add(meta.paper_id.removeprefix("arxiv:"))
        if meta.paper_id.startswith("doi:"):
            ids.add(meta.paper_id.removeprefix("doi:"))
    return ids


def _is_known(paper: DiscoveredPaper, known: set[str]) -> bool:
    """Check if a discovered paper is already in the local store."""
    if paper.title.lower().strip() in known:
        return True
    if paper.arxiv_id and paper.arxiv_id in known:
        return True
    if paper.arxiv_id and f"arxiv:{paper.arxiv_id}" in known:
        return True
    if paper.doi and paper.doi in known:
        return True
    return bool(paper.doi and f"doi:{paper.doi}" in known)


# ---------------------------------------------------------------------------
# Topic search
# ---------------------------------------------------------------------------

def search_topic(
    query: str,
    *,
    limit: int = 20,
    year_min: int | None = None,
    year_max: int | None = None,
) -> list[DiscoveredPaper]:
    """Search Semantic Scholar for papers on a topic.

    Returns papers sorted by citation count (descending), filtered to exclude
    papers already in the local store.
    """
    params: dict[str, Any] = {
        "query": query,
        "limit": min(limit * 2, 100),  # over-fetch to allow dedup
        "fields": S2_FIELDS,
    }
    if year_min or year_max:
        lo = str(year_min) if year_min else ""
        hi = str(year_max) if year_max else ""
        params["year"] = f"{lo}-{hi}"

    try:
        with httpx.Client(timeout=_TIMEOUT, headers=_HEADERS) as client:
            resp = client.get(S2_SEARCH, params=params)
            resp.raise_for_status()
    except (httpx.HTTPStatusError, httpx.TimeoutException) as e:
        raise RuntimeError(f"Semantic Scholar search failed: {e}") from e

    data = resp.json()
    raw_papers = data.get("data") or []

    known = _existing_ids()
    results: list[DiscoveredPaper] = []
    for item in raw_papers:
        paper = _parse_s2_paper(item, source="search")
        if paper is None:
            continue
        if _is_known(paper, known):
            continue
        results.append(paper)

    # Sort by citation count descending.
    results.sort(key=lambda p: p.citation_count, reverse=True)
    return results[:limit]


# ---------------------------------------------------------------------------
# Citation expansion — follow references + citations of existing papers
# ---------------------------------------------------------------------------

def _s2_id_for_paper(meta) -> str | None:
    """Resolve a local paper to an S2-resolvable identifier."""
    if meta.paper_id.startswith("arxiv:"):
        arxiv_id = meta.paper_id.removeprefix("arxiv:")
        return f"ArXiv:{arxiv_id}"
    if meta.paper_id.startswith("doi:"):
        doi = meta.paper_id.removeprefix("doi:")
        return f"DOI:{doi}"
    if meta.paper_id.startswith("s2:"):
        return meta.paper_id.removeprefix("s2:")
    # For local PDFs, try title search as last resort.
    return None


def _fetch_references(s2_key: str) -> list[DiscoveredPaper]:
    """Get papers cited BY a given paper (its references)."""
    url = f"{S2_PAPER}/{s2_key}/references"
    params = {"fields": S2_REF_FIELDS, "limit": "100"}
    try:
        with httpx.Client(timeout=_TIMEOUT, headers=_HEADERS) as client:
            resp = client.get(url, params=params)
            resp.raise_for_status()
    except (httpx.HTTPStatusError, httpx.TimeoutException):
        return []
    data = resp.json()
    results: list[DiscoveredPaper] = []
    for item in (data.get("data") or []):
        cited = item.get("citedPaper")
        if not cited:
            continue
        paper = _parse_s2_paper(cited, source="reference")
        if paper is not None:
            results.append(paper)
    return results


def _fetch_citations(s2_key: str) -> list[DiscoveredPaper]:
    """Get papers that CITE a given paper (its citations)."""
    url = f"{S2_PAPER}/{s2_key}/citations"
    params = {"fields": S2_REF_FIELDS, "limit": "100"}
    try:
        with httpx.Client(timeout=_TIMEOUT, headers=_HEADERS) as client:
            resp = client.get(url, params=params)
            resp.raise_for_status()
    except (httpx.HTTPStatusError, httpx.TimeoutException):
        return []
    data = resp.json()
    results: list[DiscoveredPaper] = []
    for item in (data.get("data") or []):
        citing = item.get("citingPaper")
        if not citing:
            continue
        paper = _parse_s2_paper(citing, source="citation")
        if paper is not None:
            results.append(paper)
    return results


def expand_from_existing(
    *,
    limit: int = 20,
    min_citations: int = 5,
) -> list[DiscoveredPaper]:
    """Discover papers by following citations and references of existing papers.

    For each paper in the local store:
        1. Fetch its references (papers it cites)
        2. Fetch its citations (papers that cite it)
    Dedup against the local store + across results.
    Return the top papers ranked by citation count.
    """
    papers = list_papers()
    if not papers:
        return []

    known = _existing_ids()
    seen_titles: set[str] = set()
    all_discovered: list[DiscoveredPaper] = []

    for meta in papers:
        s2_key = _s2_id_for_paper(meta)
        if s2_key is None:
            continue

        # References (papers this one cites).
        refs = _fetch_references(s2_key)
        for p in refs:
            t = p.title.lower().strip()
            if _is_known(p, known) or t in seen_titles:
                continue
            if p.citation_count < min_citations:
                continue
            seen_titles.add(t)
            all_discovered.append(p)

        # Citations (papers that cite this one).
        cites = _fetch_citations(s2_key)
        for p in cites:
            t = p.title.lower().strip()
            if _is_known(p, known) or t in seen_titles:
                continue
            if p.citation_count < min_citations:
                continue
            seen_titles.add(t)
            all_discovered.append(p)

    # Rank by citation count.
    all_discovered.sort(key=lambda p: p.citation_count, reverse=True)
    return all_discovered[:limit]
