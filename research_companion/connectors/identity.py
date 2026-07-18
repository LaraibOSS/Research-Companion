"""Canonical identity for records found across multiple scholarly sources.

Precedence DOI > PMID > PMCID > arXiv > title-hash, so one paper found via
several connectors collapses to one id. Pure; no network.
"""
from __future__ import annotations

import hashlib
import re

from research_companion.store import make_arxiv_id, make_doi_id


def _pmcid_norm(pmcid: str) -> str:
    p = pmcid.strip().upper()
    return p if p.startswith("PMC") else f"PMC{p}"


def _title_hash(title: str) -> str:
    norm = re.sub(r"\s+", " ", title.strip().lower())
    return "title:" + hashlib.md5(norm.encode("utf-8")).hexdigest()  # noqa: S324 (non-crypto id)


def _namespaced_ids(rec: dict) -> dict[str, str]:
    """Namespaced ids present on a record, in precedence order (highest first)."""
    ids: dict[str, str] = {}
    if rec.get("doi"):
        ids["doi"] = make_doi_id(rec["doi"].strip())
    if rec.get("pmid"):
        ids["pmid"] = f"pmid:{str(rec['pmid']).strip()}"
    if rec.get("pmcid"):
        ids["pmcid"] = f"pmcid:{_pmcid_norm(rec['pmcid'])}"
    if rec.get("arxiv_id"):
        ids["arxiv"] = make_arxiv_id(rec["arxiv_id"].strip())
    return ids


def canonical_id(rec: dict) -> str:
    namespaced = _namespaced_ids(rec)
    if namespaced:
        return next(iter(namespaced.values()))
    return _title_hash(rec.get("title", ""))


def alt_ids(rec: dict) -> set[str]:
    return set(_namespaced_ids(rec).values())


def preprint_published_warning(rec: dict) -> str | None:
    """A record carrying both a DOI and a preprint id is a preprint↔published
    pair; surface it, never auto-merge."""
    if rec.get("doi") and rec.get("arxiv_id"):
        return ("This reference has both a published DOI and a preprint id — "
                "they may be the same work under two identifiers.")
    return None
