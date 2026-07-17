"""URL egress guardrails for user-supplied download URLs (best-effort SSRF hardening).

NOT a complete SSRF defense: the host is resolved here and again by the HTTP client
at connect time (a TOCTOU/DNS-rebinding window). Connection-IP pinning and network
egress controls are out of scope for this local single-user tool.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024  # 50 MB cap for a single PDF
MAX_REDIRECTS = 5


class UrlNotAllowed(Exception):
    """Raised when a URL is disallowed by the egress policy."""


def validate_public_url(url: str) -> None:
    """Raise UrlNotAllowed unless *url* is an http(s) URL, credential-free, whose
    host resolves ONLY to globally-reachable IP addresses."""
    try:
        parts = urlparse(url)
    except ValueError as exc:
        raise UrlNotAllowed(f"unparseable URL: {url!r}") from exc
    if parts.scheme.lower() not in ("http", "https"):
        raise UrlNotAllowed(f"scheme not allowed: {url!r}")
    if parts.username or parts.password:
        raise UrlNotAllowed("embedded credentials are not allowed")
    try:
        port = parts.port  # raises ValueError on a non-numeric port
    except ValueError as exc:
        raise UrlNotAllowed(f"invalid port in {url!r}") from exc
    host = parts.hostname
    if not host:
        raise UrlNotAllowed(f"missing host: {url!r}")
    try:
        infos = socket.getaddrinfo(host, port or (443 if parts.scheme == "https" else 80),
                                   proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UrlNotAllowed(f"cannot resolve host {host!r}: {exc}") from exc
    resolved = {info[4][0] for info in infos}
    if not resolved:
        raise UrlNotAllowed(f"host {host!r} resolved to no addresses")
    for ip in resolved:
        clean = ip.split("%", 1)[0]  # strip IPv6 scope id, e.g. 'fe80::1%eth0'
        if not ipaddress.ip_address(clean).is_global:
            raise UrlNotAllowed(f"host {host!r} resolves to non-global address {ip}")
