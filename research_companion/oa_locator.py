"""Open-access PDF locator for papers whose PDF download failed.

Given a paper's metadata, ask the OA aggregators the tool already trusts for
a DIRECT pdf URL (fetched by the caller via fetch._try_download_pdf) and for
landing-page links the user can follow themselves. Providers, in order:
s2 (openAccessPdf) -> unpaywall (DOI + contact_email only) -> openalex ->
arxiv (an id surfaced by an earlier provider). Every network call lives in a
seam-injectable module-level _fetch_* function; parsers are pure. Any HTTP
failure means that provider contributes nothing. See
docs/superpowers/specs/2026-07-21-find-pdf-online-design.md (local).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import quote, quote_plus

import httpx

S2_LOOKUP_API = "https://api.semanticscholar.org/graph/v1/paper/{key}"
UNPAYWALL_API = "https://api.unpaywall.org/v2/{doi}"
OPENALEX_DOI_API = "https://api.openalex.org/works/doi:{doi}"
OPENALEX_SEARCH_API = "https://api.openalex.org/works"
ARXIV_PDF_URL = "https://arxiv.org/pdf/{arxiv_id}"
_TIMEOUT = 30.0

DEFAULT_PROVIDERS = ("s2", "unpaywall", "openalex", "arxiv")


@dataclass
class OaLocation:
    pdf_url: str | None = None
    links: list[dict] = field(default_factory=list)
    source: str | None = None


def _derive_ids(meta) -> dict:
    """Identifiers live in the paper_id namespace prefix, not on the dataclass."""
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


def _fetch_s2(ids: dict, title: str) -> dict | None:
    key = ids.get("s2") or (f"DOI:{ids['doi']}" if ids.get("doi") else None) \
        or (f"ARXIV:{ids['arxiv']}" if ids.get("arxiv") else None)
    if key is None:
        return None
    return _get_json(S2_LOOKUP_API.format(key=quote(key, safe=":/")),
                     params={"fields": "title,openAccessPdf,externalIds"})


def _fetch_unpaywall(doi: str, email: str) -> dict | None:
    return _get_json(UNPAYWALL_API.format(doi=quote(doi, safe="/")),
                     params={"email": email})


def _fetch_openalex(ids: dict, title: str) -> dict | None:
    if ids.get("doi"):
        return _get_json(OPENALEX_DOI_API.format(doi=quote(ids["doi"], safe="/")))
    if not title:
        return None
    data = _get_json(OPENALEX_SEARCH_API, params={"search": title, "per-page": "1"})
    results = (data or {}).get("results") or []
    return results[0] if results else None


# ---------------------------------------------------------------------------
# Pure parsers
# ---------------------------------------------------------------------------

def _parse_s2(data) -> dict:
    if not isinstance(data, dict):
        return {"pdf_url": None, "landing": None, "arxiv": None}
    oa = data.get("openAccessPdf") or {}
    ext = data.get("externalIds") or {}
    pid = data.get("paperId")
    return {
        "pdf_url": oa.get("url") or None,
        "landing": f"https://www.semanticscholar.org/paper/{pid}" if pid else None,
        "arxiv": ext.get("ArXiv") or None,
    }


def _parse_unpaywall(data) -> dict:
    if not isinstance(data, dict):
        return {"pdf_url": None, "landing": None}
    best = data.get("best_oa_location") or {}
    return {"pdf_url": best.get("url_for_pdf") or None,
            "landing": best.get("url_for_landing_page") or None}


def _parse_openalex(data) -> dict:
    if not isinstance(data, dict):
        return {"pdf_url": None, "landing": None}
    best = data.get("best_oa_location") or {}
    return {"pdf_url": best.get("pdf_url") or None,
            "landing": best.get("landing_page_url") or None}


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def locate_pdf(meta, *, settings: dict | None = None,
               providers: tuple = DEFAULT_PROVIDERS) -> OaLocation:
    if settings is None:
        from research_companion.settings import get_settings
        settings = get_settings()
    email = (settings.get("contact_email") or "").strip()

    ids = _derive_ids(meta)
    title = (meta.title or "").strip()
    pdf_url: str | None = None
    source: str | None = None
    links: list[dict] = []
    surfaced_arxiv: str | None = None

    def add_link(label: str, url: str | None) -> None:
        if url and url not in {link["url"] for link in links}:
            links.append({"label": label, "url": url})

    for name in providers:
        if pdf_url is not None:
            break
        if name == "s2":
            parsed = _parse_s2(_fetch_s2(ids, title))
            add_link("Semantic Scholar", parsed["landing"])
            surfaced_arxiv = surfaced_arxiv or parsed["arxiv"]
            if parsed["pdf_url"]:
                pdf_url, source = parsed["pdf_url"], "s2"
        elif name == "unpaywall":
            if not ids.get("doi") or not email:
                continue
            parsed = _parse_unpaywall(_fetch_unpaywall(ids["doi"], email))
            add_link("Publisher (open access)", parsed["landing"])
            if parsed["pdf_url"]:
                pdf_url, source = parsed["pdf_url"], "unpaywall"
        elif name == "openalex":
            parsed = _parse_openalex(_fetch_openalex(ids, title))
            add_link("OpenAlex source", parsed["landing"])
            if parsed["pdf_url"]:
                pdf_url, source = parsed["pdf_url"], "openalex"
        elif name == "arxiv":
            arxiv_id = ids.get("arxiv") or surfaced_arxiv
            # only useful when the paper's own add path didn't already try it,
            # i.e. the id was surfaced by another provider just now
            if arxiv_id and not ids.get("arxiv") and pdf_url is None:
                pdf_url, source = ARXIV_PDF_URL.format(arxiv_id=arxiv_id), "arxiv"

    if ids.get("doi"):
        add_link("DOI page", f"https://doi.org/{ids['doi']}")
    if title:
        add_link("Google Scholar",
                 f"https://scholar.google.com/scholar?q={quote_plus(title)}")

    return OaLocation(pdf_url=pdf_url, links=links, source=source)
