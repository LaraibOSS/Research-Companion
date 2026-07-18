"""PubMed connector via NCBI E-utilities (secondary/fallback resolver).

esearch (title -> pmids) + esummary (pmids -> metadata). Identifier-first:
if a reference already carries a PMID, resolve it directly. Network confined
to `_esearch`/`_esummary`; parsers pure. NCBI etiquette: always send
`tool=`, send `email=` only when NCBI_EMAIL is set; 3 req/s (10 with key).
"""
from __future__ import annotations

import os
import re
from collections.abc import Callable

import httpx

from research_companion.connectors.base import USER_AGENT, RateLimiter
from research_companion.discover import DiscoveredPaper
from research_companion.refcheck import matching
from research_companion.refcheck.validate import Reference

ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
ESUMMARY = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
MATCH_FLOOR = 0.7
_YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")


def _articleid(doc: dict, idtype: str) -> str | None:
    for a in doc.get("articleids", []):
        if a.get("idtype") == idtype and a.get("value"):
            return a["value"]
    return None


def parse_esummary_doc(doc: dict) -> dict:
    year = None
    m = _YEAR_RE.search(doc.get("pubdate", ""))
    if m:
        year = int(m.group(1))
    return {
        "title": (doc.get("title") or "").strip().rstrip("."),
        "authors": [a.get("name", "") for a in doc.get("authors", []) if a.get("name")],
        "year": year,
        "doi": _articleid(doc, "doi"),
        "arxiv_id": None,
        "pmid": str(doc.get("uid")) if doc.get("uid") else None,
        "pmcid": _articleid(doc, "pmcid"),
    }


def _api_params() -> dict:
    params = {"tool": "research-companion"}
    email = os.environ.get("NCBI_EMAIL", "").strip()
    if email:
        params["email"] = email
    key = os.environ.get("NCBI_API_KEY", "").strip()
    if key:
        params["api_key"] = key
    return params


def _min_interval() -> float:
    return 0.11 if os.environ.get("NCBI_API_KEY", "").strip() else 0.34


def _http_esearch(query: str, *, rows: int = 10, timeout: float = 30.0) -> list[str]:
    params = {**_api_params(), "db": "pubmed", "term": query, "retmax": rows, "retmode": "json"}
    try:
        with httpx.Client(timeout=timeout, headers={"User-Agent": USER_AGENT}) as c:
            resp = c.get(ESEARCH, params=params)
            resp.raise_for_status()
        return resp.json().get("esearchresult", {}).get("idlist", [])
    except httpx.HTTPError:
        return []


def _http_esummary(pmids: list[str], *, timeout: float = 30.0) -> dict[str, dict]:
    if not pmids:
        return {}
    params = {**_api_params(), "db": "pubmed", "id": ",".join(pmids), "retmode": "json"}
    try:
        with httpx.Client(timeout=timeout, headers={"User-Agent": USER_AGENT}) as c:
            resp = c.get(ESUMMARY, params=params)
            resp.raise_for_status()
        result = resp.json().get("result", {})
        return {uid: result[uid] for uid in result.get("uids", []) if uid in result}
    except httpx.HTTPError:
        return {}


class PubMedConnector:
    name = "pubmed"

    def __init__(self, *, esearch: Callable[..., list[str]] = _http_esearch,
                 esummary: Callable[[list[str]], dict[str, dict]] = _http_esummary,
                 limiter: RateLimiter | None = None) -> None:
        self._esearch = esearch
        self._esummary = esummary
        self._limiter = limiter or RateLimiter(_min_interval())

    def resolve(self, ref: Reference) -> dict | None:
        if ref.pmid:
            recs = self._summaries_pmids([str(ref.pmid)])
            return recs[0] if recs else None
        self._limiter.wait()
        pmids = self._esearch(ref.title)
        for rec in self._summaries_pmids(pmids):
            if matching.title_similarity(ref.title, rec["title"]) >= MATCH_FLOOR:
                return rec
        return None

    def _summaries_pmids(self, pmids: list[str]) -> list[dict]:
        if not pmids:
            return []
        self._limiter.wait()
        docs = self._esummary(pmids)
        return [parse_esummary_doc(docs[p]) for p in pmids if p in docs]

    def search(self, query: str, *, limit: int) -> list[DiscoveredPaper]:
        self._limiter.wait()
        pmids = self._esearch(query, rows=limit)
        out: list[DiscoveredPaper] = []
        for rec in self._summaries_pmids(pmids):
            if not rec["title"]:
                continue
            out.append(DiscoveredPaper(
                title=rec["title"], authors=rec["authors"], year=rec["year"],
                citation_count=0, arxiv_id=None, doi=rec["doi"], s2_id=None,
                url=f"https://pubmed.ncbi.nlm.nih.gov/{rec['pmid']}/" if rec["pmid"] else "",
                abstract="", source="pubmed", pmid=rec["pmid"], pmcid=rec["pmcid"]))
        return out[:limit]

    def fetch_fulltext(self, ident: str) -> str | None:
        return None  # full text comes from Europe PMC; PubMed is metadata-only
