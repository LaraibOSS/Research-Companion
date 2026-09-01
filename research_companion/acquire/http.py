"""The only place acquisition touches the network.

Carries across the guardrails from fetch._download_pdf unchanged -- they were
never what failed: validate_public_url on every redirect hop, a 50 MB cap
enforced on both the declared length and the streamed bytes, a redirect cap,
and a %PDF- magic-byte check.

What is new is knowing when NOT to try again. A 403 or a 404 or an HTML body
is a definitive answer; retrying it is indistinguishable from an attack and is
how a host-level block becomes an IP-level one.
"""
from __future__ import annotations

import random
import threading
import time

import httpx

from research_companion.acquire.hosts import classify_host
from research_companion.acquire.types import Attempt

_TIMEOUT = 60.0
_MAX_ATTEMPTS = 3
_BASE_BACKOFF = 1.0

# Retried: the host is there and is asking us to come back.
RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})


def user_agent(contact_email: str = "") -> str:
    """Politeness. Verified not to move ACM, but it is the documented etiquette
    for arXiv, Crossref, Unpaywall and OpenAlex -- the difference between being
    allowlisted and being throttled."""
    base = "research-companion (https://github.com/LaraibOSS/Research-Companion)"
    email = (contact_email or "").strip()
    return f"{base} (mailto:{email})" if email else base


class TokenBucket:
    """Per-host throttle. Injectable clock and sleep so tests need no wall time."""

    def __init__(self, rate_per_sec: float = 1.0, capacity: int = 3,
                 sleep=time.sleep, now=time.monotonic) -> None:
        self._rate = rate_per_sec
        self._capacity = float(capacity)
        self._sleep = sleep
        self._now = now
        self._tokens: dict[str, float] = {}
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def take(self, host: str) -> None:
        with self._lock:
            now = self._now()
            last = self._last.get(host, now)
            tokens = min(self._capacity,
                         self._tokens.get(host, self._capacity) + (now - last) * self._rate)
            if tokens < 1.0:
                wait = (1.0 - tokens) / self._rate
                self._sleep(wait)
                tokens = 1.0
            self._tokens[host] = tokens - 1.0
            self._last[host] = now


def _backoff(attempt_index: int) -> float:
    """Exponential with jitter, so concurrent adds do not resonate."""
    return _BASE_BACKOFF * (2 ** attempt_index) * (1.0 + random.random() * 0.1)


def _retry_after(resp: httpx.Response) -> float | None:
    raw = resp.headers.get("Retry-After")
    if raw and raw.strip().isdigit():
        return float(raw.strip())
    return None


def download_pdf(url: str, *, transport=None, sleep=time.sleep,
                 bucket: TokenBucket | None = None,
                 contact_email: str = "") -> tuple[bytes | None, Attempt]:
    """Fetch one URL. Returns (bytes|None, Attempt) and never raises.

    The Attempt is the point: the caller learns WHICH failure happened, which
    is exactly what `bytes | None` threw away.
    """
    from research_companion.net import (
        MAX_DOWNLOAD_BYTES,
        MAX_REDIRECTS,
        UrlNotAllowed,
        validate_public_url,
    )

    host_class = classify_host(url)

    def done(status, outcome):
        return Attempt(url=url, host_class=host_class, status=status, outcome=outcome)

    if bucket is not None:
        bucket.take(httpx.URL(url).host or url)

    last_status: int | None = None
    for i in range(_MAX_ATTEMPTS):
        current = url
        retry_after: float | None = None
        try:
            with httpx.Client(timeout=_TIMEOUT, transport=transport,
                              headers={"User-Agent": user_agent(contact_email)},
                              follow_redirects=False) as client:
                for _ in range(MAX_REDIRECTS + 1):
                    validate_public_url(current)   # re-validate EVERY hop
                    with client.stream("GET", current) as resp:
                        if resp.is_redirect:
                            loc = resp.headers.get("location")
                            if not loc:
                                return None, done(resp.status_code, "bad-redirect")
                            current = str(resp.url.join(loc))
                            continue

                        last_status = resp.status_code
                        if resp.status_code in RETRYABLE_STATUSES:
                            retry_after = _retry_after(resp)
                            break                                    # to the retry loop
                        if resp.status_code >= 400:
                            return None, done(resp.status_code,
                                              str(resp.status_code))  # definitive
                        declared = resp.headers.get("content-length")
                        if declared and declared.isdigit() and int(declared) > MAX_DOWNLOAD_BYTES:
                            return None, done(resp.status_code, "too-large")
                        chunks: list[bytes] = []
                        total = 0
                        for chunk in resp.iter_bytes():
                            total += len(chunk)
                            if total > MAX_DOWNLOAD_BYTES:
                                return None, done(resp.status_code, "too-large")
                            chunks.append(chunk)
                        body = b"".join(chunks)
                        if not body:
                            return None, done(resp.status_code, "empty")
                        if not body.startswith(b"%PDF-"):
                            return None, done(resp.status_code, "not-pdf")  # definitive
                        return body, done(resp.status_code, "pdf")
                else:
                    return None, done(last_status, "too-many-redirects")
        except UrlNotAllowed:
            return None, done(None, "blocked-url")
        except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError,
                httpx.RemoteProtocolError):
            if i == _MAX_ATTEMPTS - 1:
                return None, done(None, "timeout")
            sleep(_backoff(i))
            continue
        except httpx.HTTPError:
            return None, done(last_status, "http-error")

        # Fell out of the redirect loop on a retryable status.
        if i == _MAX_ATTEMPTS - 1:
            return None, done(last_status,
                              "429" if last_status == 429 else "5xx")
        sleep(retry_after if retry_after is not None else _backoff(i))
    # No fallthrough: the last iteration above (i == _MAX_ATTEMPTS - 1) always
    # returns explicitly, on every branch it can take.
