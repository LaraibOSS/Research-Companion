"""Reason -> the sentence a user reads.

Kept in one pure module so the honesty guard can walk every reason. The rule
it enforces: only NO_LOCATION_FOUND may use the vocabulary of absence. A
refusal, a paywall and a timeout are not missing files, and describing them as
missing is what sent the last investigation after a web crawler.
"""
from __future__ import annotations

from urllib.parse import urlparse

from research_companion.acquire.types import AcquireReason, Acquisition

_PUBLISHERS = {
    "acm.org": "ACM",
    "ieee.org": "IEEE",
    "springer.com": "Springer",
    "springerlink.com": "Springer",
    "sciencedirect.com": "Elsevier",
    "elsevier.com": "Elsevier",
    "wiley.com": "Wiley",
    "tandfonline.com": "Taylor & Francis",
    "sagepub.com": "SAGE",
}


def publisher_name(url) -> str | None:
    """A human name for the host, falling back to the hostname itself."""
    if not isinstance(url, str) or not url:
        return None
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return None
    if not host:
        return None
    for suffix, name in _PUBLISHERS.items():
        if host == suffix or host.endswith("." + suffix):
            return name
    return host


def _refuser(acq: Acquisition) -> str | None:
    """Which host refused us, preferring one this module can NAME.

    The DOI resolver is tried first and redirects straight to the
    publisher, and an Attempt records the URL we asked for rather than the
    one that answered -- so the first refusal on a blocked ACM article is
    filed under doi.org, and reporting "doi.org blocks automated downloads"
    names the doorbell instead of the door. Prefer a refusal from a host in
    _PUBLISHERS; fall back to the first refusal only when none of them is
    recognised.
    """
    first: str | None = None
    for a in acq.attempts:
        if a.outcome not in ("403", "429"):
            continue
        name = publisher_name(a.url)
        if first is None:
            first = name
        if name in _PUBLISHERS.values():
            return name
    return first


def reason_headline(acq: Acquisition) -> str:
    if acq.obtained or acq.reason is None:
        return ""
    r = acq.reason
    if r is AcquireReason.BLOCKED_BY_HOST:
        who = _refuser(acq) or "The publisher"
        return f"Open access — but {who} blocks automated downloads."
    if r is AcquireReason.PAYWALLED:
        who = publisher_name(acq.attempts[0].url) if acq.attempts else None
        return f"{who or 'The publisher'} requires a subscription."
    if r is AcquireReason.NO_LOCATION_FOUND:
        return "No PDF found in open-access sources."
    if r is AcquireReason.SOURCE_UNAVAILABLE:
        return "Couldn't reach the source — we'll try again."
    if r is AcquireReason.NOT_A_PDF:
        return "The download was a web page, not a PDF."
    # Two situations share NOT_ATTEMPTED: a paper with genuinely no
    # identifier, and a metadata lookup that failed before acquisition ever
    # began (an identifier WAS supplied and used). State only the fact both
    # share -- the download was never attempted -- never the reason, which
    # this function cannot know.
    return "The PDF download was never attempted."


def reason_detail(acq: Acquisition) -> str:
    if acq.obtained or acq.reason is None:
        return ""
    n = len(acq.attempts)
    tried = f"Tried {n} source{'' if n == 1 else 's'}." if n else ""
    r = acq.reason
    if r is AcquireReason.BLOCKED_BY_HOST:
        return f"Your browser can fetch this. {tried}".strip()
    if r is AcquireReason.PAYWALLED:
        return (f"{tried} If you are on a university network, your browser may "
                "have access.").strip()
    if r is AcquireReason.NO_LOCATION_FOUND:
        return f"{tried} If you have the PDF, you can add it yourself.".strip()
    if r is AcquireReason.SOURCE_UNAVAILABLE:
        return f"{tried} This usually clears on its own.".strip()
    if r is AcquireReason.NOT_A_PDF:
        return (f"{tried} That usually means a login page stood in the way."
                ).strip()
    return "Add the PDF directly and it will work like any other paper."


def failure_sentence(acq: Acquisition) -> str:
    """The one user-facing sentence for a failed acquisition: the cause,
    then what follows from it.

    Exists so the two places that put an acquisition failure into a
    ``failed.json`` record's ``error`` field (research_companion/lab's
    ingest failure sites, and research_companion/lab_api.py's paper
    summary, which rewrites the stale symptom text of records written
    before acquisitions were attached) produce the identical sentence
    rather than each assembling headline and detail their own way.
    """
    if acq.obtained or acq.reason is None:
        return ""
    return f"{reason_headline(acq)} {reason_detail(acq)}".strip()
