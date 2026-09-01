"""Obtaining a paper's PDF: one chain, one typed outcome."""
from research_companion.acquire.types import (
    AcquireReason,
    Acquisition,
    Attempt,
    HostClass,
)

__all__ = ["acquire", "Acquisition", "AcquireReason", "Attempt", "HostClass"]


def acquire(meta, *, settings=None, transport=None, sleep=None,
            fetchers=None, bucket=None):
    """Get this paper's PDF bytes, or say precisely why not.

    Order: native identifier first (it has never failed and needs no index),
    then doi.org (cheap; occasionally redirects straight to a free copy),
    then every candidate the indexes know about, ranked so a repository is
    asked before a publisher.
    """
    import time

    from research_companion.acquire.hosts import rank_candidates
    from research_companion.acquire.http import download_pdf
    from research_companion.acquire.sources import ARXIV_PDF_URL, collect_candidates

    sleep = sleep or time.sleep
    if settings is None:
        from research_companion.settings import get_settings
        settings = get_settings()
    email = (settings.get("contact_email") or "").strip()

    pid = getattr(meta, "paper_id", "") or ""
    title = (getattr(meta, "title", "") or "").strip()
    doi = pid[len("doi:"):] if pid.startswith("doi:") else None
    attempts = []

    def try_url(url):
        body, attempt = download_pdf(url, transport=transport, sleep=sleep,
                                     bucket=bucket, contact_email=email)
        attempts.append(attempt)
        return body

    # 1. native identifier -- no index round-trip needed
    if pid.startswith("arxiv:"):
        body = try_url(ARXIV_PDF_URL.format(arxiv_id=pid[len("arxiv:"):]))
        if body:
            return body, Acquisition(True, None, tuple(attempts), attempts[-1].url)

    # 2. the DOI itself, which sometimes redirects to a free copy
    if doi:
        body = try_url(f"https://doi.org/{doi}")
        if body:
            return body, Acquisition(True, None, tuple(attempts), attempts[-1].url)

    # 3. every candidate the indexes know, repositories before publishers
    for url in rank_candidates(collect_candidates(meta, settings=settings,
                                                  fetchers=fetchers)):
        body = try_url(url)
        if body:
            return body, Acquisition(True, None, tuple(attempts), attempts[-1].url)

    return None, Acquisition(False, _classify(attempts, doi, pid, title),
                             tuple(attempts), None)


def _classify(attempts, doi, pid, title):
    """Turn what happened into which of the six situations this was.

    Order matters: 'we were refused' outranks 'we found nothing', because a
    403 from a host that has the file is a different problem from absence.
    """
    if not attempts:
        if not doi and not pid.startswith(("arxiv:", "s2:", "pmid:")) and not title:
            return AcquireReason.NOT_ATTEMPTED
        return AcquireReason.PAYWALLED if doi else AcquireReason.NO_LOCATION_FOUND

    outcomes = {a.outcome for a in attempts}
    if "403" in outcomes or "429" in outcomes:
        return AcquireReason.BLOCKED_BY_HOST
    if outcomes <= {"timeout", "5xx", "http-error"}:
        return AcquireReason.SOURCE_UNAVAILABLE
    if "not-pdf" in outcomes:
        return AcquireReason.NOT_A_PDF
    return AcquireReason.PAYWALLED if doi else AcquireReason.NO_LOCATION_FOUND
