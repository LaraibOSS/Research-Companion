"""Rank candidate PDF URLs by how likely the host is to serve a robot.

Verified against the real failures: dl.acm.org returns 403 with text/html for
articles it itself declares open access, regardless of User-Agent politeness.
Repositories, which exist to be harvested, do not do this. So when an index
offers several copies, ask the repository first -- the previous behaviour took
OpenAlex's single `best_oa_location`, which is chosen for bibliographic
quality and is usually the publisher.
"""
from __future__ import annotations

from urllib.parse import urlparse

from research_companion.acquire.types import HostClass

# Suffix matched against the hostname, so "dl.acm.org" also catches subdomains.
_NATIVE = ("arxiv.org", "ncbi.nlm.nih.gov", "europepmc.org", "pubmed.ncbi.nlm.nih.gov")
_PREPRINT = ("biorxiv.org", "medrxiv.org", "ssrn.com", "openreview.net", "osf.io")
_REPOSITORY = ("zenodo.org", "core.ac.uk", "hal.science", "archives-ouvertes.fr",
               "figshare.com", "repository", "eprints", "dspace", ".edu", ".ac.uk",
               "library.")

_ORDER = (HostClass.NATIVE, HostClass.REPOSITORY, HostClass.PREPRINT, HostClass.PUBLISHER)


def classify_host(url) -> HostClass:
    """Never raises. An unrecognised host is assumed to be a publisher, which
    only costs it a later position in the queue."""
    if not isinstance(url, str) or not url:
        return HostClass.PUBLISHER
    try:
        parts = urlparse(url)
    except ValueError:
        return HostClass.PUBLISHER
    if parts.scheme.lower() not in ("http", "https"):
        return HostClass.PUBLISHER
    host = (parts.hostname or "").lower()
    if not host:
        return HostClass.PUBLISHER
    if any(host == n or host.endswith("." + n) for n in _NATIVE):
        return HostClass.NATIVE
    if any(p in host for p in _PREPRINT):
        return HostClass.PREPRINT
    if any(r in host for r in _REPOSITORY):
        return HostClass.REPOSITORY
    return HostClass.PUBLISHER


def rank_candidates(urls) -> list[str]:
    """Stable sort into host-class order, deduped, non-http dropped.

    Stability matters: two publisher URLs have no principled ordering between
    them, and shuffling would make an identical run produce different attempts.
    """
    seen: set[str] = set()
    kept: list[str] = []
    for u in urls or ():
        if not isinstance(u, str) or not u or u in seen:
            continue
        if urlparse(u).scheme.lower() not in ("http", "https"):
            continue
        seen.add(u)
        kept.append(u)
    return sorted(kept, key=lambda u: _ORDER.index(classify_host(u)))
