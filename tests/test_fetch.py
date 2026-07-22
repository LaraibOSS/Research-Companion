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


def test_add_doi_uses_oa_locator_when_direct_fails(monkeypatch: pytest.MonkeyPatch,
                                                     fake_pdf_bytes: bytes):
    """Direct DOI download fails, but the OA locator finds a PDF elsewhere."""
    from research_companion.oa_locator import OaLocation

    monkeypatch.setattr(
        fetch, "_doi_metadata",
        lambda doi, timeout=30.0: {"title": "T", "authors": [], "year": 2020, "abstract": ""},
    )
    calls = []

    def fake_try(url, **kw):
        calls.append(url)
        return fake_pdf_bytes if url == "https://oa.org/found.pdf" else None

    monkeypatch.setattr(fetch, "_try_download_pdf", fake_try)
    monkeypatch.setattr(
        fetch, "locate_pdf",
        lambda meta_or_stub, **kw: OaLocation(pdf_url="https://oa.org/found.pdf",
                                               links=[], source="s2"),
    )

    meta = fetch.add_doi("10.9999/oa-test")

    assert store.pdf_path(meta.paper_id) is not None  # PDF saved via locator URL
    assert calls[0].startswith("https://doi.org/")     # direct attempt still tried first
    assert calls[-1] == "https://oa.org/found.pdf"


def test_add_doi_degrades_identically_when_locator_empty(monkeypatch: pytest.MonkeyPatch,
                                                           capsys: pytest.CaptureFixture):
    """When both the direct attempt and the locator fail, behavior is unchanged."""
    from research_companion.oa_locator import OaLocation

    monkeypatch.setattr(
        fetch, "_doi_metadata",
        lambda doi, timeout=30.0: {"title": "T", "authors": [], "year": 2020, "abstract": ""},
    )
    monkeypatch.setattr(fetch, "_try_download_pdf", lambda url, **kw: None)
    monkeypatch.setattr(fetch, "locate_pdf", lambda meta, **kw: OaLocation())

    meta = fetch.add_doi("10.9999/paywalled")

    assert store.pdf_path(meta.paper_id) is None  # metadata-only, exactly as today
    out = capsys.readouterr().out
    assert ("warning: could not download PDF for DOI 10.9999/paywalled "
            "(likely paywalled). Metadata saved, but text extraction "
            "will not work without a PDF.") in out


def test_add_doi_locator_exception_falls_back_to_metadata_only(monkeypatch: pytest.MonkeyPatch,
                                                                 capsys: pytest.CaptureFixture):
    """locate_pdf raising must not abort the whole add — same never-crash contract
    as every other seam in this module (cli.py's add loop only catches FetchError)."""
    monkeypatch.setattr(
        fetch, "_doi_metadata",
        lambda doi, timeout=30.0: {"title": "T", "authors": [], "year": 2020, "abstract": ""},
    )
    monkeypatch.setattr(fetch, "_try_download_pdf", lambda url, **kw: None)

    def raise_locate(meta, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(fetch, "locate_pdf", raise_locate)

    meta = fetch.add_doi("10.9999/locator-crashes")

    assert store.pdf_path(meta.paper_id) is None  # metadata-only, exactly as today
    out = capsys.readouterr().out
    assert ("warning: could not download PDF for DOI 10.9999/locator-crashes "
            "(likely paywalled). Metadata saved, but text extraction "
            "will not work without a PDF.") in out


def test_add_s2_uses_oa_locator_when_direct_fails(monkeypatch: pytest.MonkeyPatch,
                                                    fake_pdf_bytes: bytes):
    """Direct arXiv/DOI attempts fail, but the OA locator finds a PDF elsewhere."""
    from research_companion.oa_locator import OaLocation

    monkeypatch.setattr(
        fetch, "_s2_metadata",
        lambda s2_id, timeout=30.0: {
            "title": "T", "authors": [], "year": 2020, "abstract": "",
            "external_ids": {"ArXiv": "1234.5678", "DOI": "10.9999/s2-test"},
        },
    )
    calls = []

    def fake_try(url, **kw):
        calls.append(url)
        return fake_pdf_bytes if url == "https://oa.org/s2-found.pdf" else None

    monkeypatch.setattr(fetch, "_try_download_pdf", fake_try)
    monkeypatch.setattr(
        fetch, "locate_pdf",
        lambda meta_or_stub, **kw: OaLocation(pdf_url="https://oa.org/s2-found.pdf",
                                               links=[], source="unpaywall"),
    )

    s2_id = "a" * 40
    meta = fetch.add_s2(s2_id)

    assert store.pdf_path(meta.paper_id) is not None
    # arXiv attempt first, then DOI attempt, then the locator URL last.
    assert calls[0] == fetch.ARXIV_PDF_URL.format(arxiv_id="1234.5678")
    assert calls[1] == "https://doi.org/10.9999/s2-test"
    assert calls[-1] == "https://oa.org/s2-found.pdf"


def test_add_s2_degrades_identically_when_locator_empty(monkeypatch: pytest.MonkeyPatch,
                                                          capsys: pytest.CaptureFixture):
    """When arXiv/DOI attempts and the locator all fail, behavior is unchanged."""
    from research_companion.oa_locator import OaLocation

    monkeypatch.setattr(
        fetch, "_s2_metadata",
        lambda s2_id, timeout=30.0: {
            "title": "T", "authors": [], "year": 2020, "abstract": "",
            "external_ids": {},
        },
    )
    monkeypatch.setattr(fetch, "_try_download_pdf", lambda url, **kw: None)
    monkeypatch.setattr(fetch, "locate_pdf", lambda meta, **kw: OaLocation())

    s2_id = "b" * 40
    meta = fetch.add_s2(s2_id)

    assert store.pdf_path(meta.paper_id) is None
    out = capsys.readouterr().out
    assert (f"warning: could not download PDF for S2 paper {s2_id}. "
            f"Metadata saved, but text extraction will not work without a PDF.") in out


def test_add_s2_locator_exception_falls_back_to_metadata_only(monkeypatch: pytest.MonkeyPatch,
                                                                capsys: pytest.CaptureFixture):
    """Same never-crash contract for add_s2: a locate_pdf exception must not
    propagate out of add_s2."""
    monkeypatch.setattr(
        fetch, "_s2_metadata",
        lambda s2_id, timeout=30.0: {
            "title": "T", "authors": [], "year": 2020, "abstract": "",
            "external_ids": {},
        },
    )
    monkeypatch.setattr(fetch, "_try_download_pdf", lambda url, **kw: None)

    def raise_locate(meta, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(fetch, "locate_pdf", raise_locate)

    s2_id = "c" * 40
    meta = fetch.add_s2(s2_id)

    assert store.pdf_path(meta.paper_id) is None
    out = capsys.readouterr().out
    assert (f"warning: could not download PDF for S2 paper {s2_id}. "
            f"Metadata saved, but text extraction will not work without a PDF.") in out


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
