"""Europe PMC connector — the primary biomedical source.

One REST API federating PubMed (MED), PMC, and preprints, plus OA fullTextXML.
Network is confined to `_search`/`_fetch_fulltext_xml`; parsers are pure.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Callable

import httpx

from research_companion.connectors.base import USER_AGENT
from research_companion.discover import DiscoveredPaper
from research_companion.refcheck import matching
from research_companion.refcheck.validate import Reference

SEARCH_API = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
FULLTEXT_API = "https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
MATCH_FLOOR = 0.7
MAX_FULLTEXT_BYTES = 20 * 1024 * 1024
_SKIP_TAGS = {"table-wrap", "ref-list", "fig", "table"}


def parse_europepmc_result(result: dict) -> dict:
    authors = [a.strip() for a in (result.get("authorString") or "").split(",") if a.strip()]
    year = None
    if (result.get("pubYear") or "").isdigit():
        year = int(result["pubYear"])
    return {
        "title": (result.get("title") or "").strip(),
        "authors": authors,
        "year": year,
        "doi": result.get("doi"),
        "arxiv_id": None,
        "pmid": result.get("pmid"),
        "pmcid": result.get("pmcid"),
    }


def _strip(node: ET.Element) -> str:
    parts: list[str] = []
    if node.tag == "title" and node.text:
        parts.append(node.text.strip() + "\n")
    elif node.tag == "p":
        parts.append("".join(node.itertext()).strip() + "\n")
    for child in node:
        if child.tag in _SKIP_TAGS:
            continue
        parts.append(_strip(child))
    return "".join(parts)


def _remove_skip_tags(root: ET.Element) -> None:
    """Drop skip-tag subtrees in-place, bottom-up, so removal never races iteration.

    `ET.Element.iter()` is a live generator over the tree: mutating a parent's
    children while a shared `.iter()` walk is still descending into one of the
    just-removed nodes can leave stale iterator state. Collecting
    `(parent, child)` pairs first — via `iter()` over a snapshot list per
    parent — and removing only after the full walk completes avoids that.
    """
    to_remove: list[tuple[ET.Element, ET.Element]] = []
    for parent in root.iter():
        for child in list(parent):
            if child.tag in _SKIP_TAGS:
                to_remove.append((parent, child))
    for parent, child in to_remove:
        parent.remove(child)


def jats_to_text(xml: str) -> str:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return ""
    body = root.find(".//body")
    if body is None:
        return ""
    _remove_skip_tags(body)
    text = _strip(body)
    return "\n".join(line for line in (ln.strip() for ln in text.splitlines()) if line)


def _best(ref: Reference, results: list[dict]) -> dict | None:
    best, score = None, -1.0
    for r in results:
        rec = parse_europepmc_result(r)
        s = matching.title_similarity(ref.title, rec["title"])
        if s > score:
            best, score = rec, s
    return best if best is not None and score >= MATCH_FLOOR else None


def _http_search(query: str, *, rows: int = 10, timeout: float = 30.0) -> list[dict]:
    params = {"query": query, "format": "json", "pageSize": rows, "resultType": "core"}
    try:
        with httpx.Client(timeout=timeout, headers={"User-Agent": USER_AGENT}) as c:
            resp = c.get(SEARCH_API, params=params)
            resp.raise_for_status()
        return resp.json().get("resultList", {}).get("result", [])
    except httpx.HTTPError:
        return []


def _http_fetch_xml(pmcid: str, *, timeout: float = 30.0) -> str | None:
    try:
        with httpx.Client(timeout=timeout, headers={"User-Agent": USER_AGENT}) as c:
            resp = c.get(FULLTEXT_API.format(pmcid=pmcid))
            resp.raise_for_status()
        if len(resp.content) > MAX_FULLTEXT_BYTES:
            return None
        return resp.text
    except httpx.HTTPError:
        return None


class EuropePMCConnector:
    name = "europepmc"

    def __init__(self, *, search: Callable[..., list[dict]] = _http_search,
                 fetch_xml: Callable[[str], str | None] = _http_fetch_xml) -> None:
        self._search = search
        self._fetch_xml = fetch_xml

    def resolve(self, ref: Reference) -> dict | None:
        return _best(ref, self._search(ref.title))

    def search(self, query: str, *, limit: int) -> list[DiscoveredPaper]:
        out: list[DiscoveredPaper] = []
        for r in self._search(query, rows=limit):
            rec = parse_europepmc_result(r)
            if not rec["title"]:
                continue
            out.append(DiscoveredPaper(
                title=rec["title"], authors=rec["authors"], year=rec["year"],
                citation_count=int(r.get("citedByCount") or 0),
                arxiv_id=None, doi=rec["doi"], s2_id=None,
                url=f"https://europepmc.org/abstract/MED/{rec['pmid']}" if rec["pmid"] else "",
                abstract=(r.get("abstractText") or "").strip(),
                source="europepmc", pmid=rec["pmid"], pmcid=rec["pmcid"]))
        return out[:limit]

    def fetch_fulltext(self, ident: str) -> str | None:
        xml = self._fetch_xml(ident)
        return jats_to_text(xml) if xml else None
