"""Tests for research_companion.fetch.

Mocks all HTTP — no real network calls.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from research_companion import fetch, store


def test_parse_arxiv_id_from_abs_url():
    assert fetch.parse_arxiv_id("https://arxiv.org/abs/2410.05779") == "2410.05779"
    assert fetch.parse_arxiv_id("https://arxiv.org/abs/2410.05779v3") == "2410.05779"


def test_parse_arxiv_id_from_pdf_url():
    assert fetch.parse_arxiv_id("https://arxiv.org/pdf/2410.05779") == "2410.05779"
    assert fetch.parse_arxiv_id("https://arxiv.org/pdf/2410.05779.pdf") == "2410.05779"


def test_parse_arxiv_id_from_html_url():
    assert fetch.parse_arxiv_id("https://arxiv.org/html/2410.05779v3") == "2410.05779"


def test_parse_arxiv_id_from_bare_id():
    assert fetch.parse_arxiv_id("2410.05779") == "2410.05779"
    assert fetch.parse_arxiv_id("2410.05779v2") == "2410.05779"


def test_parse_arxiv_id_rejects_garbage():
    assert fetch.parse_arxiv_id("not a paper") is None
    assert fetch.parse_arxiv_id("./local.pdf") is None
    assert fetch.parse_arxiv_id("") is None


def test_add_local_pdf_happy_path(tmp_path: Path, fake_pdf_bytes: bytes):
    pdf = tmp_path / "my-paper.pdf"
    pdf.write_bytes(fake_pdf_bytes)

    meta = fetch.add_local_pdf(pdf, title="My Paper", authors=["Azizur"], year=2026)
    assert meta.paper_id.startswith("local:")
    assert meta.title == "My Paper"
    assert meta.authors == ["Azizur"]
    assert meta.year == 2026
    assert (store.paper_dir(meta.paper_id) / "paper.pdf").exists()


def test_add_local_pdf_idempotent(tmp_path: Path, fake_pdf_bytes: bytes):
    pdf = tmp_path / "my-paper.pdf"
    pdf.write_bytes(fake_pdf_bytes)
    meta1 = fetch.add_local_pdf(pdf, title="A")
    meta2 = fetch.add_local_pdf(pdf, title="B")  # title arg ignored on cache hit
    assert meta1.paper_id == meta2.paper_id
    assert meta2.title == "A"  # original title preserved


def test_add_local_pdf_rejects_non_pdf(tmp_path: Path):
    bad = tmp_path / "fake.pdf"
    bad.write_bytes(b"not a pdf")
    with pytest.raises(fetch.FetchError):
        fetch.add_local_pdf(bad)


def test_add_local_pdf_rejects_missing(tmp_path: Path):
    with pytest.raises(fetch.FetchError):
        fetch.add_local_pdf(tmp_path / "does-not-exist.pdf")


def test_add_arxiv_with_mocked_http(monkeypatch: pytest.MonkeyPatch, fake_pdf_bytes: bytes):
    """Mock both the arxiv API and the PDF download."""
    monkeypatch.setattr(
        fetch, "_arxiv_metadata",
        lambda arxiv_id, timeout=30.0: {
            "title": "Mocked GraphRAG paper",
            "authors": ["Alice", "Bob"],
            "year": 2024,
            "abstract": "We propose a thing.",
            "arxiv_categories": ["cs.CL"],
        },
    )
    monkeypatch.setattr(fetch, "_download_pdf", lambda url, timeout=60.0: fake_pdf_bytes)

    meta = fetch.add_arxiv("https://arxiv.org/abs/2410.05779")
    assert meta.paper_id == "arxiv:2410.05779"
    assert meta.title == "Mocked GraphRAG paper"
    assert meta.authors == ["Alice", "Bob"]
    assert meta.year == 2024
    assert meta.source_url == "https://arxiv.org/abs/2410.05779"


def test_add_paper_routes_arxiv_vs_local(monkeypatch: pytest.MonkeyPatch,
                                          tmp_path: Path, fake_pdf_bytes: bytes):
    monkeypatch.setattr(
        fetch, "_arxiv_metadata",
        lambda arxiv_id, timeout=30.0: {"title": "X", "authors": [], "year": None,
                                         "abstract": "", "arxiv_categories": []},
    )
    monkeypatch.setattr(fetch, "_download_pdf", lambda url, timeout=60.0: fake_pdf_bytes)

    # Distinct bytes from the arXiv download: this is a genuinely different paper,
    # so cross-namespace dedup (find_existing_paper_for) must not merge them —
    # the point of this test is routing (arXiv input -> arxiv id, path -> local id).
    pdf = tmp_path / "local.pdf"
    pdf.write_bytes(fake_pdf_bytes + b"a genuinely different local paper")

    arxiv_meta = fetch.add_paper("2410.05779")
    local_meta = fetch.add_paper(str(pdf))

    assert arxiv_meta.paper_id.startswith("arxiv:")
    assert local_meta.paper_id.startswith("local:")


def test_arxiv_metadata_wraps_http_errors_in_fetcherror(monkeypatch: pytest.MonkeyPatch):
    """A throttled arXiv API (429) must surface as FetchError, not a raw traceback."""
    import httpx

    class _FakeResp:
        text = ""
        def raise_for_status(self):
            raise httpx.HTTPStatusError("429", request=None, response=None)

    class _FakeClient:
        def __init__(self, *a, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, *a, **kw): return _FakeResp()

    monkeypatch.setattr(fetch.httpx, "Client", _FakeClient)
    with pytest.raises(fetch.FetchError):
        fetch._arxiv_metadata("2410.04209")
