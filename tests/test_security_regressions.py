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


def test_download_pdf_maps_blocked_url_to_fetcherror():
    """A blocked URL (literal loopback, no DNS) surfaces as FetchError."""
    from research_companion.fetch import FetchError, _download_pdf
    with pytest.raises(FetchError):
        _download_pdf("http://127.0.0.1/x.pdf")


# --- streaming size cap + redirects, deterministic via httpx.MockTransport ----

def _download_with(monkeypatch, handler):
    """Force fetch's internal httpx.Client to use a MockTransport; allow any host."""
    monkeypatch.setattr(net, "validate_public_url", lambda url: None)
    import research_companion.fetch as fetch_mod
    real_client = httpx.Client

    def fake_client(*a, **k):
        k.pop("follow_redirects", None)
        return real_client(*a, transport=httpx.MockTransport(handler),
                           follow_redirects=False, **k)
    monkeypatch.setattr(fetch_mod.httpx, "Client", fake_client)
    from research_companion.fetch import _download_pdf
    return _download_pdf


def test_stream_rejects_oversized_content_length(monkeypatch):
    from research_companion.fetch import FetchError
    monkeypatch.setattr(net, "MAX_DOWNLOAD_BYTES", 100)
    body = b"%PDF-" + b"a" * 96  # 101 bytes -> httpx sets content-length=101
    dl = _download_with(monkeypatch, lambda req: httpx.Response(200, content=body))
    with pytest.raises(FetchError):
        dl("https://ok.example.org/p.pdf")


def test_stream_rejects_oversized_body_without_content_length(monkeypatch):
    from research_companion.fetch import FetchError
    monkeypatch.setattr(net, "MAX_DOWNLOAD_BYTES", 10)

    def gen():
        yield b"%PDF-"
        yield b"a" * 20  # total 25 > 10, no content-length (streaming iterator)
    dl = _download_with(monkeypatch, lambda req: httpx.Response(200, content=gen()))
    with pytest.raises(FetchError):
        dl("https://ok.example.org/p.pdf")


@pytest.mark.parametrize("content", [b"", b"<html>not a pdf</html>"])
def test_stream_rejects_non_pdf_and_empty(monkeypatch, content):
    from research_companion.fetch import FetchError
    dl = _download_with(monkeypatch, lambda req: httpx.Response(200, content=content))
    with pytest.raises(FetchError):
        dl("https://ok.example.org/p.pdf")


def test_stream_follows_bounded_redirects_then_downloads(monkeypatch):
    hops = {"n": 0}

    def handler(req):
        if hops["n"] < 2:
            hops["n"] += 1
            return httpx.Response(302, headers={"location": "https://ok.example.org/next"})
        return httpx.Response(200, content=b"%PDF-1.7 minimal")
    dl = _download_with(monkeypatch, handler)
    assert dl("https://ok.example.org/start").startswith(b"%PDF-")


def test_stream_rejects_too_many_redirects(monkeypatch):
    from research_companion.fetch import FetchError
    dl = _download_with(monkeypatch,
                        lambda req: httpx.Response(302, headers={"location": "https://ok.example.org/loop"}))
    with pytest.raises(FetchError):
        dl("https://ok.example.org/start")


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
