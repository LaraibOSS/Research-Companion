"""Ask every index for every copy.

Absorbs oa_locator.py. The behavioural change is that this COLLECTS rather
than SELECTS: the old code stopped at the first pdf_url any provider offered,
which for a paywalled paper was invariably the publisher's own URL -- the one
host guaranteed to refuse a robot.

Every network call lives in a module-level _fetch_* seam so tests inject dicts
instead of HTTP. Any provider that fails contributes nothing and never stops
the others.
"""
from __future__ import annotations

import re
from urllib.parse import quote, quote_plus

import httpx

S2_LOOKUP_API = "https://api.semanticscholar.org/graph/v1/paper/{key}"
UNPAYWALL_API = "https://api.unpaywall.org/v2/{doi}"
OPENALEX_DOI_API = "https://api.openalex.org/works/doi:{doi}"
OPENALEX_SEARCH_API = "https://api.openalex.org/works"
PMC_SEARCH_API = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
ARXIV_PDF_URL = "https://arxiv.org/pdf/{arxiv_id}"
ARXIV_QUERY = ("http://export.arxiv.org/api/query"
               "?search_query=ti:%22{title}%22&max_results=3")
_TIMEOUT = 30.0


def _derive_ids(meta) -> dict:
    """Identifiers live in the paper_id namespace prefix, not on the dataclass.

    Ported verbatim from oa_locator.py.
    """
    pid = meta.paper_id or ""
    ids = {"doi": None, "arxiv": None, "s2": None}
    if pid.startswith("doi:"):
        ids["doi"] = pid[len("doi:"):]
    elif pid.startswith("arxiv:"):
        ids["arxiv"] = pid[len("arxiv:"):]
    elif pid.startswith("s2:"):
        ids["s2"] = pid[len("s2:"):]
    return ids


# ---------------------------------------------------------------------------
# Seam-injectable fetchers (network lives here and only here)
# ---------------------------------------------------------------------------

def _get_json(url: str, params: dict | None = None) -> dict | None:
    """Ported verbatim from oa_locator.py."""
    from research_companion.fetch import USER_AGENT
    try:
        with httpx.Client(timeout=_TIMEOUT, headers={"User-Agent": USER_AGENT},
                          follow_redirects=True) as client:
            resp = client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, dict) else None
    except Exception:
        return None


def _get_text(url: str) -> str | None:
    """Same shape as _get_json but for the arXiv/EuropePMC endpoints that
    return XML or where we want the raw body rather than parsed JSON."""
    from research_companion.fetch import USER_AGENT
    try:
        with httpx.Client(timeout=_TIMEOUT, headers={"User-Agent": USER_AGENT},
                          follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.text
    except Exception:
        return None


def _fetch_s2(ids: dict, title: str) -> dict | None:
    """Ported verbatim from oa_locator.py."""
    key = ids.get("s2") or (f"DOI:{ids['doi']}" if ids.get("doi") else None) \
        or (f"ARXIV:{ids['arxiv']}" if ids.get("arxiv") else None)
    if key is None:
        return None
    return _get_json(S2_LOOKUP_API.format(key=quote(key, safe=":/")),
                     params={"fields": "title,openAccessPdf,externalIds"})


def _fetch_unpaywall(doi: str, email: str) -> dict | None:
    """Ported verbatim from oa_locator.py."""
    return _get_json(UNPAYWALL_API.format(doi=quote(doi, safe="/")),
                     params={"email": email})


def _fetch_openalex(ids: dict, title: str) -> dict | None:
    """Ported verbatim from oa_locator.py."""
    if ids.get("doi"):
        return _get_json(OPENALEX_DOI_API.format(doi=quote(ids["doi"], safe="/")))
    if not title:
        return None
    data = _get_json(OPENALEX_SEARCH_API, params={"search": title, "per-page": "1"})
    results = (data or {}).get("results") or []
    return results[0] if results else None


def _fetch_arxiv_by_title(title: str) -> str | None:
    """Search arXiv by title, unlike the old code which only followed an
    arXiv id another provider had already surfaced. This is what recovers a
    preprint of a paywalled paper -- TAPAS and NeuPIMs among them."""
    if not title:
        return None
    url = ARXIV_QUERY.format(title=quote_plus(title))
    return _parse_arxiv_feed(_get_text(url), title)


def _fetch_pmc_by_title(title: str) -> str | None:
    """Search EuropePMC by title and return an open-access PDF URL for the
    matching result, or None. Same title-matching discipline as arXiv: a
    near-miss result must not be accepted, since attaching the wrong PDF is
    worse than finding nothing."""
    if not title:
        return None
    data = _get_json(PMC_SEARCH_API, params={
        "query": f'TITLE:"{title}"',
        "format": "json",
        "resultType": "core",
        "pageSize": "3",
    })
    if not isinstance(data, dict):
        return None
    results = (data.get("resultList") or {}).get("result")
    if not isinstance(results, list):
        return None
    want = _norm_title(title)
    for r in results:
        if not isinstance(r, dict):
            continue
        if _norm_title(r.get("title") or "") != want:
            continue
        urls = (r.get("fullTextUrlList") or {}).get("fullTextUrl")
        if not isinstance(urls, list):
            continue
        for u in urls:
            if isinstance(u, dict) and u.get("documentStyle") == "pdf" and u.get("url"):
                return u["url"]
    return None


# ---------------------------------------------------------------------------
# Pure parsers
# ---------------------------------------------------------------------------

def _norm_title(s: str) -> str:
    """Compare titles ignoring case, punctuation and whitespace runs. A title
    search returns near-misses, and attaching the wrong PDF to a paper is a
    worse outcome than finding nothing."""
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _parse_openalex_locations(payload) -> list[str]:
    """EVERY location, not just best_oa_location."""
    if not isinstance(payload, dict):
        return []
    urls: list[str] = []
    best = payload.get("best_oa_location")
    if isinstance(best, dict) and best.get("pdf_url"):
        urls.append(best["pdf_url"])
    for loc in payload.get("locations") or ():
        if isinstance(loc, dict) and loc.get("pdf_url"):
            urls.append(loc["pdf_url"])
    seen, out = set(), []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _parse_arxiv_feed(xml, title) -> str | None:
    """Return the bare arXiv id whose title matches, or None."""
    if not isinstance(xml, str) or not xml:
        return None
    want = _norm_title(title)
    if not want:
        return None
    entries = re.findall(r"<entry>(.*?)</entry>", xml, re.S)
    for entry in entries:
        m_id = re.search(r"<id>http://arxiv\.org/abs/([^<]+)</id>", entry)
        m_ti = re.search(r"<title>(.*?)</title>", entry, re.S)
        if not m_id or not m_ti:
            continue
        if _norm_title(m_ti.group(1)) == want:
            return re.sub(r"v\d+$", "", m_id.group(1).strip())
    return None


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

_DEFAULT_FETCHERS = {
    "s2": _fetch_s2,
    "unpaywall": _fetch_unpaywall,
    "openalex": _fetch_openalex,
    "arxiv_title": _fetch_arxiv_by_title,
    "pmc_title": _fetch_pmc_by_title,
}


def collect_candidates(meta, *, settings=None, fetchers=None) -> list[str]:
    """Every candidate PDF URL any index knows about, unranked.

    Ranking is hosts.rank_candidates' job; fetching is http.download_pdf's.
    This function only knows how to ask.
    """
    if settings is None:
        from research_companion.settings import get_settings
        settings = get_settings()
    f = fetchers or _DEFAULT_FETCHERS
    ids = _derive_ids(meta)
    title = (getattr(meta, "title", "") or "").strip()
    email = (settings.get("contact_email") or "").strip()
    urls: list[str] = []

    def safe(fn, *args):
        try:
            return fn(*args)
        except Exception:      # a provider outage must not fail the acquisition
            return None

    s2 = safe(f["s2"], ids, title)
    if isinstance(s2, dict):
        pdf = (s2.get("openAccessPdf") or {}).get("url")
        if pdf:
            urls.append(pdf)

    if ids.get("doi") and email:
        up = safe(f["unpaywall"], ids["doi"], email)
        if isinstance(up, dict):
            pdf = (up.get("best_oa_location") or {}).get("url_for_pdf")
            if pdf:
                urls.append(pdf)

    urls.extend(_parse_openalex_locations(safe(f["openalex"], ids, title)))

    if title and not ids.get("arxiv"):
        found = safe(f["arxiv_title"], title)
        if found:
            urls.append(ARXIV_PDF_URL.format(arxiv_id=found))

    if title:
        pmc = safe(f["pmc_title"], title)
        if pmc:
            urls.append(pmc)

    seen, out = set(), []
    for u in urls:
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out
