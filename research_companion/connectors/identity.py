"""Canonical identity for records found across multiple scholarly sources.

Precedence DOI > PMID > PMCID > arXiv > title-hash, so one paper found via
several connectors collapses to one id. Pure; no network.
"""
from __future__ import annotations

import hashlib
import re


def _pmcid_norm(pmcid: str) -> str:
    p = pmcid.strip().upper()
    return p if p.startswith("PMC") else f"PMC{p}"


def _title_hash(title: str) -> str:
    norm = re.sub(r"\s+", " ", title.strip().lower())
    return "title:" + hashlib.md5(norm.encode("utf-8")).hexdigest()  # noqa: S324 (non-crypto id)


def canonical_id(rec: dict) -> str:
    if rec.get("doi"):
        return f"doi:{rec['doi'].strip()}"
    if rec.get("pmid"):
        return f"pmid:{str(rec['pmid']).strip()}"
    if rec.get("pmcid"):
        return f"pmcid:{_pmcid_norm(rec['pmcid'])}"
    if rec.get("arxiv_id"):
        return f"arxiv:{rec['arxiv_id'].strip()}"
    return _title_hash(rec.get("title", ""))


def alt_ids(rec: dict) -> set[str]:
    ids: set[str] = set()
    if rec.get("doi"):
        ids.add(f"doi:{rec['doi'].strip()}")
    if rec.get("pmid"):
        ids.add(f"pmid:{str(rec['pmid']).strip()}")
    if rec.get("pmcid"):
        ids.add(f"pmcid:{_pmcid_norm(rec['pmcid'])}")
    if rec.get("arxiv_id"):
        ids.add(f"arxiv:{rec['arxiv_id'].strip()}")
    return ids


def preprint_published_warning(rec: dict) -> str | None:
    """A record carrying both a DOI and a preprint id is a preprint↔published
    pair; surface it, never auto-merge."""
    if rec.get("doi") and rec.get("arxiv_id"):
        return ("This reference has both a published DOI and a preprint id — "
                "they may be the same work under two identifiers.")
    return None
