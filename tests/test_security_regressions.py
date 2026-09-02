"""Security regressions: URL egress guard (deterministic DNS), traversal, loopback bind."""
import socket

import httpx
import pytest

from research_companion import net, store


def _resolves_to(*ips):
    """Return a fake getaddrinfo resolving any host to the given IPs."""
    def fake(host, port, *a, **k):
        return [(socket.AF_INET6 if ":" in ip else socket.AF_INET,
                 socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, port or 0))
                for ip in ips]
    return fake


@pytest.mark.parametrize("url", [
    "file:///etc/passwd", "ftp://example.com/x.pdf", "gopher://x/1",
    "http://user:pass@example.com/x.pdf",           # embedded creds
    "https://example.org:notaport/x.pdf",           # invalid port
    "https:///nohost",                              # missing host
])
def test_reject_by_static_policy(url):
    with pytest.raises(net.UrlNotAllowed):
        net.validate_public_url(url)


@pytest.mark.parametrize("ip", [
    "127.0.0.1", "::1", "169.254.169.254", "10.0.0.5", "192.168.1.1",
    "172.16.0.2", "0.0.0.0", "100.64.0.1", "198.18.0.1",
    "192.0.2.1", "198.51.100.1", "203.0.113.1", "2001:db8::1",
])
def test_reject_non_global_resolved_ip(ip, monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _resolves_to(ip))
    with pytest.raises(net.UrlNotAllowed):
        net.validate_public_url("https://papers.example.org/p.pdf")


@pytest.mark.parametrize("ip", ["93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946"])
def test_allow_global_resolved_ip(ip, monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _resolves_to(ip))
    net.validate_public_url("https://papers.example.org/p.pdf")  # must not raise


def test_reject_mixed_public_and_private(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _resolves_to("93.184.216.34", "127.0.0.1"))
    with pytest.raises(net.UrlNotAllowed):
        net.validate_public_url("https://papers.example.org/p.pdf")


def test_reject_zero_addresses_and_gaierror(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [])
    with pytest.raises(net.UrlNotAllowed):
        net.validate_public_url("https://none.example.org/p.pdf")

    def boom(*a, **k):
        raise socket.gaierror("nope")
    monkeypatch.setattr(socket, "getaddrinfo", boom)
    with pytest.raises(net.UrlNotAllowed):
        net.validate_public_url("https://bad.example.org/p.pdf")


def test_a_blocked_url_is_refused_before_any_request():
    """A blocked URL (literal loopback, no DNS) never reaches the network,
    and the refusal is reported as its own outcome rather than flattened
    into the same value as a 404."""
    from research_companion.acquire.http import download_pdf
    body, attempt = download_pdf("http://127.0.0.1/x.pdf")
    assert body is None
    assert attempt.outcome == "blocked-url"
    assert attempt.status is None


# --- streaming size cap + redirects, deterministic via httpx.MockTransport ----
#
# These guard acquire/http.py's download_pdf -- the ONE function that fetches
# a PDF in production. They used to guard fetch._download_pdf, which had no
# production caller left once acquire/ absorbed it: a named SSRF regression
# test exercising dead code proves nothing about the path an attacker would
# actually reach. The guardrails themselves (validate_public_url on every
# redirect hop, the 50 MB cap on both the declared length and the streamed
# bytes, the redirect cap, the %PDF- magic-byte check) moved across intact;
# what changed is that a refusal now returns (None, Attempt) naming which
# refusal it was, instead of raising one flattened FetchError.

def _download_with(monkeypatch, handler):
    """Drive the live downloader over a MockTransport; allow any host (the
    URL policy itself is covered by the tests above)."""
    monkeypatch.setattr(net, "validate_public_url", lambda url: None)
    from research_companion.acquire.http import download_pdf

    def run(url):
        return download_pdf(url, transport=httpx.MockTransport(handler),
                            sleep=lambda s: None)
    return run


def test_stream_rejects_oversized_content_length(monkeypatch):
    monkeypatch.setattr(net, "MAX_DOWNLOAD_BYTES", 100)
    body = b"%PDF-" + b"a" * 96  # 101 bytes -> httpx sets content-length=101
    dl = _download_with(monkeypatch, lambda req: httpx.Response(200, content=body))
    got, attempt = dl("https://ok.example.org/p.pdf")
    assert got is None
    assert attempt.outcome == "too-large"


def test_stream_rejects_oversized_body_without_content_length(monkeypatch):
    monkeypatch.setattr(net, "MAX_DOWNLOAD_BYTES", 10)

    def gen():
        yield b"%PDF-"
        yield b"a" * 20  # total 25 > 10, no content-length (streaming iterator)
    dl = _download_with(monkeypatch, lambda req: httpx.Response(200, content=gen()))
    got, attempt = dl("https://ok.example.org/p.pdf")
    assert got is None
    assert attempt.outcome == "too-large"


@pytest.mark.parametrize("content,outcome", [(b"", "empty"),
                                             (b"<html>not a pdf</html>", "not-pdf")])
def test_stream_rejects_non_pdf_and_empty(monkeypatch, content, outcome):
    dl = _download_with(monkeypatch, lambda req: httpx.Response(200, content=content))
    got, attempt = dl("https://ok.example.org/p.pdf")
    assert got is None
    assert attempt.outcome == outcome


def test_stream_follows_bounded_redirects_then_downloads(monkeypatch):
    hops = {"n": 0}

    def handler(req):
        if hops["n"] < 2:
            hops["n"] += 1
            return httpx.Response(302, headers={"location": "https://ok.example.org/next"})
        return httpx.Response(200, content=b"%PDF-1.7 minimal")
    dl = _download_with(monkeypatch, handler)
    got, attempt = dl("https://ok.example.org/start")
    assert got.startswith(b"%PDF-")
    assert attempt.outcome == "pdf"


def test_stream_rejects_too_many_redirects(monkeypatch):
    dl = _download_with(monkeypatch,
                        lambda req: httpx.Response(302, headers={"location": "https://ok.example.org/loop"}))
    got, attempt = dl("https://ok.example.org/start")
    assert got is None
    assert attempt.outcome == "too-many-redirects"


def test_every_redirect_hop_is_revalidated(monkeypatch):
    """The hop matters more than the first URL: a public host redirecting to
    169.254.169.254 is the whole SSRF shape this guard exists for."""
    from research_companion.acquire.http import download_pdf

    seen = []

    def fake_validate(url):
        seen.append(url)
        if "169.254" in url:
            raise net.UrlNotAllowed(url)
    monkeypatch.setattr(net, "validate_public_url", fake_validate)

    def handler(req):
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest"})

    got, attempt = download_pdf("https://ok.example.org/start",
                                transport=httpx.MockTransport(handler),
                                sleep=lambda s: None)
    assert got is None
    assert attempt.outcome == "blocked-url"
    assert any("169.254" in u for u in seen), "the redirect target was validated"


def test_paper_id_cannot_traverse_paths():
    """A hostile paper_id must never escape the (conftest-isolated) papers dir."""
    root = store.papers_dir().resolve()
    for hostile in ("../../evil", "..\\..\\evil", "a/../../b", "x:..%2F..%2Fy"):
        resolved = store.paper_dir(hostile).resolve()
        assert root == resolved.parent, f"{hostile!r} escaped to {resolved}"
        assert ".." not in resolved.name


def test_lab_server_binds_loopback_only(monkeypatch):
    """serve_lab must call uvicorn.run(host='127.0.0.1') — behavioral, not source scan."""
    import uvicorn

    from research_companion import lab_api
    captured = {}
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: captured.update(k))
    monkeypatch.setattr("webbrowser.open", lambda *a, **k: None)
    lab_api.serve_lab(open_browser=False)
    assert captured.get("host") == "127.0.0.1"
    assert captured.get("host") != "0.0.0.0"
