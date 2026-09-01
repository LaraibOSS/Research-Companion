"""The chain, end to end, over a mocked network.

The classification is the deliverable, not just the bytes: a paper that is
open access but robot-blocked must not be reported the same way as one behind
a paywall, and neither may be reported as 'not found'.
"""
from __future__ import annotations

from types import SimpleNamespace

import httpx

from research_companion.acquire import AcquireReason, acquire

PDF = b"%PDF-1.5\nbody"


def _meta(paper_id="doi:10.1145/3732941", title="A Paper"):
    return SimpleNamespace(paper_id=paper_id, title=title, authors=[], year=2024)


def _fetchers(**over):
    base = {k: (lambda *a, **k: None) for k in
            ("s2", "unpaywall", "openalex", "arxiv_title", "pmc_title")}
    base.update(over)
    return base


def _serve(mapping, default=None):
    not_found = default if default is not None else httpx.Response(404)

    def handler(request):
        for frag, resp in mapping.items():
            if frag in str(request.url):
                return resp
        return not_found
    return httpx.MockTransport(handler)


def test_a_reachable_pdf_is_obtained():
    t = _serve({"zenodo.org": httpx.Response(200, content=PDF)})
    body, acq = acquire(
        _meta(), settings={}, transport=t, sleep=lambda s: None,
        fetchers=_fetchers(s2=lambda i, ti: {
            "openAccessPdf": {"url": "https://zenodo.org/a.pdf"}}))
    assert body == PDF
    assert acq.obtained is True
    assert acq.reason is None
    assert acq.source == "https://zenodo.org/a.pdf"


def test_the_repository_copy_is_tried_before_the_publisher():
    """The ACM copy 403s; the repository copy does not. Order decides."""
    t = _serve({"dl.acm.org": httpx.Response(403),
                "smu.edu.sg": httpx.Response(200, content=PDF)})
    body, acq = acquire(
        _meta(), settings={}, transport=t, sleep=lambda s: None,
        fetchers=_fetchers(openalex=lambda i, ti: {"locations": [
            {"pdf_url": "https://dl.acm.org/doi/pdf/x"},
            {"pdf_url": "https://ink.library.smu.edu.sg/cgi/viewcontent.cgi?a=1"}]}))
    assert body == PDF
    urls = [a.url for a in acq.attempts]
    repo_index = next(i for i, u in enumerate(urls) if u.endswith("a=1"))
    # dl.acm.org may never be tried at all: the repository candidate is
    # ranked first and succeeds, short-circuiting the loop. "never tried"
    # still counts as "after", so a missing publisher attempt sorts last.
    publisher_index = next((i for i, u in enumerate(urls) if "dl.acm.org" in u),
                          len(urls))
    assert repo_index < publisher_index, "repository before publisher"


def test_an_open_access_403_is_blocked_by_host_not_paywalled():
    """The exact case in the failure log: ACM declares the article open access
    and answers 403 to a robot. Calling that 'paywalled' would send the user
    looking for a subscription they do not need."""
    t = _serve({"dl.acm.org": httpx.Response(403, text="<html/>")})
    body, acq = acquire(
        _meta(), settings={}, transport=t, sleep=lambda s: None,
        fetchers=_fetchers(openalex=lambda i, ti: {
            "locations": [{"pdf_url": "https://dl.acm.org/doi/pdf/x"}]}))
    assert body is None
    assert acq.reason is AcquireReason.BLOCKED_BY_HOST
    assert acq.human_can_help is True


def test_no_candidate_anywhere_is_paywalled_when_the_paper_has_a_doi():
    """A DOI that no index can find a free copy for is a subscription article."""
    body, acq = acquire(_meta(), settings={}, transport=_serve({}),
                        sleep=lambda s: None, fetchers=_fetchers())
    assert body is None
    assert acq.reason is AcquireReason.PAYWALLED
    assert [a.url for a in acq.attempts] == ["https://doi.org/10.1145/3732941"]


def test_no_candidate_and_no_doi_is_no_location_found():
    body, acq = acquire(_meta(paper_id="local:abc"), settings={},
                        transport=_serve({}), sleep=lambda s: None,
                        fetchers=_fetchers())
    assert acq.reason is AcquireReason.NO_LOCATION_FOUND


def test_a_paper_with_no_identifier_and_no_title_was_not_attempted():
    body, acq = acquire(_meta(paper_id="local:abc", title=""), settings={},
                        transport=_serve({}), sleep=lambda s: None,
                        fetchers=_fetchers())
    assert acq.reason is AcquireReason.NOT_ATTEMPTED


def test_a_transient_failure_everywhere_is_source_unavailable():
    """The machine's problem, not the user's -- so it must not reach the queue."""
    t = _serve({"zenodo.org": httpx.Response(503)}, default=httpx.Response(503))
    body, acq = acquire(
        _meta(), settings={}, transport=t, sleep=lambda s: None,
        fetchers=_fetchers(s2=lambda i, ti: {
            "openAccessPdf": {"url": "https://zenodo.org/a.pdf"}}))
    assert acq.reason is AcquireReason.SOURCE_UNAVAILABLE
    assert acq.human_can_help is False


def test_html_at_every_candidate_is_not_a_pdf():
    t = _serve({"zenodo.org": httpx.Response(200, text="<html>login</html>")})
    body, acq = acquire(
        _meta(), settings={}, transport=t, sleep=lambda s: None,
        fetchers=_fetchers(s2=lambda i, ti: {
            "openAccessPdf": {"url": "https://zenodo.org/a.pdf"}}))
    assert acq.reason is AcquireReason.NOT_A_PDF


def test_every_candidate_tried_is_recorded():
    t = _serve({"dl.acm.org": httpx.Response(403), "zenodo.org": httpx.Response(404)})
    body, acq = acquire(
        _meta(), settings={}, transport=t, sleep=lambda s: None,
        fetchers=_fetchers(openalex=lambda i, ti: {"locations": [
            {"pdf_url": "https://dl.acm.org/doi/pdf/x"},
            {"pdf_url": "https://zenodo.org/a.pdf"}]}))
    assert len(acq.attempts) == 3
    assert {a.outcome for a in acq.attempts} == {"403", "404"}


def test_an_arxiv_paper_goes_straight_to_arxiv():
    """The native path, which has never failed. It must not be made to wait
    behind an index round-trip."""
    t = _serve({"arxiv.org": httpx.Response(200, content=PDF)})
    called = []
    body, acq = acquire(
        _meta(paper_id="arxiv:2501.02600"), settings={}, transport=t,
        sleep=lambda s: None,
        fetchers=_fetchers(openalex=lambda i, ti: called.append(1)))
    assert body == PDF
    assert called == [], "no index was consulted"
