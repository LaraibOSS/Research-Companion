"""Paper discovery via Semantic Scholar APIs.

Two modes:
    topic search  — find papers on a topic, ranked by citation count + relevance
    expand        — follow citations/references of existing papers to find gaps

All APIs are free, no auth required. Rate limit: ~100 req/5min without a key.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx

from research_companion.store import list_papers

S2_SEARCH = "https://api.semanticscholar.org/graph/v1/paper/search"
S2_PAPER = "https://api.semanticscholar.org/graph/v1/paper"
S2_FIELDS = "title,authors,year,abstract,citationCount,externalIds,url,venue,publicationVenue"
S2_REF_FIELDS = "title,authors,year,citationCount,externalIds,url"
USER_AGENT = "research-companion/0.1 (https://github.com/azizur100389/research-companion)"

_HEADERS = {"User-Agent": USER_AGENT}
_TIMEOUT = 30.0


def _s2_headers() -> dict[str, str]:
    """Request headers for Semantic Scholar, including the API key when the
    user has set one. S2's anonymous pool is shared and throttles bursts; a
    free key raises the limit substantially. Never raises."""
    headers = dict(_HEADERS)
    import os as _os
    key = _os.environ.get("S2_API_KEY", "").strip()
    if key:
        headers["x-api-key"] = key
    return headers


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
    pmid: str | None = None
    pmcid: str | None = None
    venue: str = ""   # publication venue as reported by the source ("" when unknown)

    @property
    def add_cmd(self) -> str:
        """Suggested `research-companion add` command for this paper."""
        if self.pmid:
            return f"research-companion add pmid:{self.pmid}"
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
            "s2_id": self.s2_id,
            "pmid": self.pmid,
            "pmcid": self.pmcid,
            "url": self.url,
            "abstract": self.abstract,
            "venue": self.venue,
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
        venue=_s2_venue(data),
    )



def _s2_venue(data: dict) -> str:
    """Venue name from a Semantic Scholar record. `publicationVenue.name` is the
    curated form; `venue` is the free-text fallback. "" when neither is set."""
    pv = data.get("publicationVenue")
    if isinstance(pv, dict):
        name = str(pv.get("name") or "").strip()
        if name:
            return name
    return str(data.get("venue") or "").strip()

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
    if paper.doi and f"doi:{paper.doi}" in known:
        return True
    if paper.pmid and f"pmid:{paper.pmid}" in known:
        return True
    return bool(paper.pmcid and f"pmcid:{paper.pmcid}" in known)


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
        with httpx.Client(timeout=_TIMEOUT, headers=_s2_headers()) as client:
            resp = _get_with_backoff(client, S2_SEARCH, params=params)
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
        with httpx.Client(timeout=_TIMEOUT, headers=_s2_headers()) as client:
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
        with httpx.Client(timeout=_TIMEOUT, headers=_s2_headers()) as client:
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


# ---------------------------------------------------------------------------
# OpenAlex fallback (S2 rate-limits aggressively for unauthenticated clients)
# ---------------------------------------------------------------------------

OPENALEX_SEARCH = "https://api.openalex.org/works"


def _reconstruct_abstract(inverted: dict | None) -> str:
    """Rebuild plain text from OpenAlex's abstract_inverted_index."""
    if not inverted:
        return ""
    positions: list[tuple[int, str]] = []
    for word, idxs in inverted.items():
        for i in idxs:
            positions.append((i, word))
    return " ".join(w for _, w in sorted(positions))


def _parse_openalex_work(w: dict) -> DiscoveredPaper | None:
    """Map one OpenAlex work to a DiscoveredPaper. Returns None without a title."""
    title = (w.get("display_name") or "").strip()
    if not title:
        return None
    doi = (w.get("ids") or {}).get("doi") or ""
    doi = doi.replace("https://doi.org/", "").replace("http://doi.org/", "") or None
    arxiv_id = None
    if doi and doi.startswith("10.48550/arxiv."):
        arxiv_id = doi.split("arxiv.", 1)[1]
    return DiscoveredPaper(
        title=title,
        authors=[(a.get("author") or {}).get("display_name", "")
                 for a in w.get("authorships", [])],
        year=w.get("publication_year"),
        citation_count=w.get("cited_by_count", 0),
        arxiv_id=arxiv_id,
        doi=doi,
        s2_id=None,
        url=(w.get("ids") or {}).get("openalex", ""),
        abstract=_reconstruct_abstract(w.get("abstract_inverted_index")),
        source="openalex",
        venue=str(((w.get("primary_location") or {}).get("source") or {})
                  .get("display_name") or ""),
    )


def _polite_params() -> dict[str, str]:
    """OpenAlex serves anonymous traffic from a shared, aggressively-throttled
    pool; adding `mailto` moves requests into the far more generous "polite
    pool". Uses the contact_email setting when the user has set one — we never
    invent an address. Never raises."""
    try:
        from research_companion.settings import get_settings
        email = str(get_settings().get("contact_email", "") or "").strip()
    except Exception:  # noqa: BLE001 — discovery must not depend on settings loading
        email = ""
    return {"mailto": email} if email else {}


def _get_with_backoff(client, url, *, params=None, attempts: int = 3):
    """GET that retries on 429/503 instead of failing the whole search.

    Public catalogues rate-limit bursts (adding 20 papers, then searching, is a
    burst). Honors `Retry-After` when the server sends it, else backs off
    1s, 2s. Raises the final error only after the retries are spent.
    """
    import time as _time

    last_exc = None
    for attempt in range(attempts):
        try:
            resp = client.get(url, params=params)
            if resp.status_code in (429, 503) and attempt < attempts - 1:
                retry_after = resp.headers.get("Retry-After", "")
                try:
                    delay = min(float(retry_after), 10.0)
                except (TypeError, ValueError):
                    delay = float(2 ** attempt)
                _time.sleep(max(0.5, delay))
                continue
            resp.raise_for_status()
            return resp
        except httpx.HTTPStatusError as exc:
            last_exc = exc
            if exc.response is not None and exc.response.status_code in (429, 503)                     and attempt < attempts - 1:
                _time.sleep(float(2 ** attempt))
                continue
            raise
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("request failed")


def search_topic_openalex(
    query: str,
    *,
    limit: int = 20,
    year_min: int | None = None,
    year_max: int | None = None,
    timeout: float = 30.0,
) -> list[DiscoveredPaper]:
    """Search OpenAlex works (generous rate limits, no key required)."""
    params: dict[str, Any] = {"search": query, "per-page": min(limit, 50)}
    params.update(_polite_params())
    filters = []
    if year_min:
        filters.append(f"from_publication_date:{year_min}-01-01")
    if year_max:
        filters.append(f"to_publication_date:{year_max}-12-31")
    if filters:
        params["filter"] = ",".join(filters)
    with httpx.Client(timeout=timeout, headers={"User-Agent": USER_AGENT}) as client:
        resp = _get_with_backoff(client, OPENALEX_SEARCH, params=params)
    known = _existing_ids()
    out = []
    for w in resp.json().get("results", []):
        paper = _parse_openalex_work(w)
        if paper is not None and not _is_known(paper, known):
            out.append(paper)
    out.sort(key=lambda p: -p.citation_count)
    return out[:limit]


def _settings_connector_names() -> list[str]:
    """Enabled connector names from global settings; [] on any error (safe default).

    Intentionally mirrors research_companion.refcheck.retrieval._settings_connectors()
    by design — a small duplication to avoid a cross-module import between
    discover and refcheck.
    """
    try:
        from research_companion.settings import get_settings
        val = get_settings().get("connectors", [])
        return list(val) if isinstance(val, list) else []
    except Exception:
        return []


def search_topic_with_fallback(
    query: str,
    *,
    limit: int = 20,
    year_min: int | None = None,
    year_max: int | None = None,
    s2_search=None,
    openalex_search=None,
    connectors=None,
) -> list[DiscoveredPaper]:
    """Prior-art search: Semantic Scholar first, OpenAlex on failure, then any
    enabled domain connectors merged in and deduped. `connectors=None` reads
    settings; pass a list to override (tests / CLI)."""
    from research_companion.connectors.identity import alt_ids

    s2 = s2_search or search_topic
    oa = openalex_search or search_topic_openalex
    # Try Semantic Scholar, fall back to OpenAlex. If BOTH are unavailable
    # (both are public services that throttle bursts), re-raise the LAST error
    # so the caller can explain what happened -- but never let a failure in one
    # source discard results the other already returned.
    base: list[DiscoveredPaper] = []
    errors: list[Exception] = []
    try:
        base = s2(query, limit=limit, year_min=year_min, year_max=year_max)
    except Exception as exc:  # noqa: BLE001
        errors.append(exc)
    if not base:
        try:
            base = oa(query, limit=limit, year_min=year_min, year_max=year_max)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
    if not base and errors:
        raise errors[-1]

    names = _settings_connector_names() if connectors is None else list(connectors)
    if not names:
        return base

    seen_ids: set[str] = set()
    seen_titles: set[str] = set()
    merged: list[DiscoveredPaper] = []
    for p in base:
        rec = {"doi": p.doi, "arxiv_id": p.arxiv_id, "pmid": p.pmid, "pmcid": p.pmcid}
        seen_ids |= alt_ids(rec)
        seen_titles.add(p.title.lower().strip())
        merged.append(p)

    from research_companion.connectors import enabled_connectors
    for conn in enabled_connectors(names):
        try:
            found = conn.search(query, limit=limit)
        except Exception:
            found = []
        for p in found:
            rec = {"doi": p.doi, "arxiv_id": p.arxiv_id, "pmid": p.pmid, "pmcid": p.pmcid}
            ids = alt_ids(rec)
            t = p.title.lower().strip()
            if (ids & seen_ids) or t in seen_titles:
                continue
            seen_ids |= ids
            seen_titles.add(t)
            merged.append(p)
    return merged


# ---------------------------------------------------------------------------
# Query expansion — turn a rough title/topic into a handful of search queries
# ---------------------------------------------------------------------------

def expand_query(title: str, *, llm=None) -> list[str]:
    """Expand a rough title/topic into up to 5 literature-search queries.

    The original `title` is ALWAYS the first entry in the returned list.
    When `llm` is None, or the LLM call / JSON parse fails for ANY reason,
    degrades to `[title]` — this function never raises. Otherwise appends
    up to 4 additional AI-suggested queries (deduped case-insensitively
    against the original and each other) via a single SHA-cached
    DISCOVER_EXPAND_PROMPT call.

    `llm`: an injectable callable(prompt: str) -> str (same seam as the
    rest of the codebase: `_resolve_llm(json_mode=True)` / `app.state.llm`
    in lab_api.py).
    """
    if llm is None:
        return [title]

    from research_companion.extract import _strip_code_fences
    from research_companion.prompts import format_discover_expand_prompt

    try:
        raw = llm(format_discover_expand_prompt(title))
        data = json.loads(_strip_code_fences(raw)) if isinstance(raw, str) else raw
        extra = data.get("queries") if isinstance(data, dict) else None
        if not isinstance(extra, list):
            return [title]
    except Exception:
        return [title]

    queries = [title]
    seen = {title.strip().lower()}
    for q in extra:
        if not isinstance(q, str):
            continue
        q = q.strip()
        if not q or q.lower() in seen:
            continue
        queries.append(q)
        seen.add(q.lower())
        if len(queries) >= 5:
            break
    return queries
