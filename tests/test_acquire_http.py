"""Fetching bytes, and knowing when not to try again.

There were no retries at all, so one transient 503 from arXiv permanently
failed an add. Adding them has a hazard of its own: retrying a 403 is
indistinguishable from an attack and is how a host-level block becomes an
IP-level one.
"""
from __future__ import annotations

import httpx

from research_companion.acquire import HostClass
from research_companion.acquire.http import TokenBucket, download_pdf

PDF = b"%PDF-1.5\nbody"


def _transport(*responses):
    """Serve the given responses in order, then repeat the last one."""
    calls = []

    def handler(request):
        calls.append(str(request.url))
        r = responses[min(len(calls) - 1, len(responses) - 1)]
        return r() if callable(r) else r

    t = httpx.MockTransport(handler)
    t.calls = calls
    return t


def _sleeps():
    slept = []
    return slept, lambda s: slept.append(s)


def test_a_pdf_is_returned_with_its_attempt():
    t = _transport(httpx.Response(200, content=PDF))
    body, attempt = download_pdf("https://arxiv.org/pdf/1", transport=t)
    assert body == PDF
    assert attempt.status == 200
    assert attempt.outcome == "pdf"
    assert attempt.host_class == HostClass.NATIVE


def test_a_403_is_never_retried():
    """The ban-avoidance rule. One assertion, and it is the difference between
    a tool an institution can install and one that gets its IP blocked."""
    t = _transport(httpx.Response(403, text="<html>denied</html>"))
    slept, sleep = _sleeps()
    body, attempt = download_pdf("https://dl.acm.org/doi/pdf/1", transport=t, sleep=sleep)
    assert body is None
    assert attempt.status == 403
    assert attempt.outcome == "403"
    assert len(t.calls) == 1, "a 403 is a definitive answer"
    assert slept == []


def test_a_404_is_never_retried():
    t = _transport(httpx.Response(404))
    body, attempt = download_pdf("https://example.org/x.pdf", transport=t)
    assert body is None
    assert len(t.calls) == 1


def test_a_503_is_retried_and_can_succeed():
    t = _transport(httpx.Response(503), httpx.Response(503),
                   httpx.Response(200, content=PDF))
    slept, sleep = _sleeps()
    body, attempt = download_pdf("https://arxiv.org/pdf/1", transport=t, sleep=sleep)
    assert body == PDF
    assert len(t.calls) == 3
    assert len(slept) == 2


def test_retries_back_off():
    t = _transport(httpx.Response(503))
    slept, sleep = _sleeps()
    download_pdf("https://arxiv.org/pdf/1", transport=t, sleep=sleep)
    assert len(slept) == 2, "3 attempts means 2 waits"
    assert slept[1] > slept[0], "exponential, not flat"


def test_retries_give_up_after_three_attempts():
    t = _transport(httpx.Response(503))
    body, attempt = download_pdf("https://arxiv.org/pdf/1", transport=t, sleep=lambda s: None)
    assert body is None
    assert len(t.calls) == 3
    assert attempt.outcome == "5xx"


def test_a_429_honours_retry_after():
    t = _transport(httpx.Response(429, headers={"Retry-After": "7"}),
                   httpx.Response(200, content=PDF))
    slept, sleep = _sleeps()
    body, _ = download_pdf("https://arxiv.org/pdf/1", transport=t, sleep=sleep)
    assert body == PDF
    assert slept == [7.0]


def test_a_timeout_is_retried():
    def boom():
        raise httpx.ConnectTimeout("timed out")

    t = _transport(boom, boom, httpx.Response(200, content=PDF))
    body, _ = download_pdf("https://arxiv.org/pdf/1", transport=t, sleep=lambda s: None)
    assert body == PDF


def test_a_timeout_that_never_clears_is_reported_as_such():
    def boom():
        raise httpx.ConnectTimeout("timed out")

    t = _transport(boom)
    body, attempt = download_pdf("https://arxiv.org/pdf/1", transport=t, sleep=lambda s: None)
    assert body is None
    assert attempt.outcome == "timeout"
    assert attempt.status is None


def test_html_where_a_pdf_was_promised_is_not_a_pdf():
    t = _transport(httpx.Response(200, text="<html>login</html>"))
    body, attempt = download_pdf("https://dl.acm.org/doi/pdf/1", transport=t)
    assert body is None
    assert attempt.outcome == "not-pdf"
    assert attempt.status == 200


def test_html_is_not_retried():
    """A 200 that is not a PDF is a definitive answer too."""
    t = _transport(httpx.Response(200, text="<html>login</html>"))
    download_pdf("https://dl.acm.org/doi/pdf/1", transport=t, sleep=lambda s: None)
    assert len(t.calls) == 1


def test_the_size_cap_still_applies():
    from research_companion.net import MAX_DOWNLOAD_BYTES
    big = b"%PDF-" + b"x" * (MAX_DOWNLOAD_BYTES + 10)
    t = _transport(httpx.Response(200, content=big))
    body, attempt = download_pdf("https://arxiv.org/pdf/1", transport=t)
    assert body is None
    assert attempt.outcome == "too-large"


def test_a_private_address_is_refused_without_a_request():
    body, attempt = download_pdf("http://127.0.0.1:8800/x.pdf", transport=_transport(
        httpx.Response(200, content=PDF)))
    assert body is None
    assert attempt.outcome == "blocked-url"
    assert attempt.status is None


def test_redirects_are_followed_to_a_pdf():
    t = _transport(
        httpx.Response(302, headers={"Location": "https://arxiv.org/pdf/final"}),
        httpx.Response(200, content=PDF))
    body, _ = download_pdf("https://arxiv.org/pdf/1", transport=t)
    assert body == PDF
    assert len(t.calls) == 2


def test_a_redirect_loop_gives_up():
    t = _transport(httpx.Response(302, headers={"Location": "https://arxiv.org/pdf/1"}))
    body, attempt = download_pdf("https://arxiv.org/pdf/1", transport=t)
    assert body is None
    assert attempt.outcome == "too-many-redirects"


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

def test_the_bucket_allows_a_burst_up_to_capacity():
    slept, sleep = _sleeps()
    b = TokenBucket(rate_per_sec=1.0, capacity=3, sleep=sleep, now=lambda: 0.0)
    for _ in range(3):
        b.take("arxiv.org")
    assert slept == []


def test_the_bucket_waits_once_the_burst_is_spent():
    """Auto-add fires one queue entry per reference with no spacing, so a
    40-reference bibliography arrived at arXiv as a burst."""
    slept, sleep = _sleeps()
    b = TokenBucket(rate_per_sec=1.0, capacity=2, sleep=sleep, now=lambda: 0.0)
    for _ in range(4):
        b.take("arxiv.org")
    assert len(slept) == 2
    assert all(s > 0 for s in slept)


def test_hosts_are_limited_independently():
    slept, sleep = _sleeps()
    b = TokenBucket(rate_per_sec=1.0, capacity=1, sleep=sleep, now=lambda: 0.0)
    b.take("arxiv.org")
    b.take("api.openalex.org")
    assert slept == [], "a slow publisher must not throttle arXiv"
