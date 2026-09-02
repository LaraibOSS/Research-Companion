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
    """Mock both the arxiv API and the PDF acquisition (one acquire() call now,
    not a direct _download_pdf)."""
    from research_companion.acquire import Acquisition

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
    monkeypatch.setattr(
        fetch, "acquire",
        lambda meta, **kw: (fake_pdf_bytes,
                            Acquisition(True, None, source="https://arxiv.org/pdf/2410.05779.pdf")),
    )

    meta = fetch.add_arxiv("https://arxiv.org/abs/2410.05779")
    assert meta.paper_id == "arxiv:2410.05779"
    assert meta.title == "Mocked GraphRAG paper"
    assert meta.authors == ["Alice", "Bob"]
    assert meta.year == 2024
    assert meta.source_url == "https://arxiv.org/abs/2410.05779"


def test_add_paper_routes_arxiv_vs_local(monkeypatch: pytest.MonkeyPatch,
                                          tmp_path: Path, fake_pdf_bytes: bytes):
    from research_companion.acquire import Acquisition

    monkeypatch.setattr(
        fetch, "_arxiv_metadata",
        lambda arxiv_id, timeout=30.0: {"title": "X", "authors": [], "year": None,
                                         "abstract": "", "arxiv_categories": []},
    )
    monkeypatch.setattr(
        fetch, "acquire",
        lambda meta, **kw: (fake_pdf_bytes, Acquisition(True, None)),
    )

    # Distinct bytes from the arXiv download: this is a genuinely different paper,
    # so cross-namespace dedup (find_existing_paper_for) must not merge them —
    # the point of this test is routing (arXiv input -> arxiv id, path -> local id).
    pdf = tmp_path / "local.pdf"
    pdf.write_bytes(fake_pdf_bytes + b"a genuinely different local paper")

    arxiv_meta = fetch.add_paper("2410.05779")
    local_meta = fetch.add_paper(str(pdf))

    assert arxiv_meta.paper_id.startswith("arxiv:")
    assert local_meta.paper_id.startswith("local:")


def test_add_doi_saves_pdf_when_acquire_succeeds(monkeypatch: pytest.MonkeyPatch,
                                                  fake_pdf_bytes: bytes):
    """The old direct-download-then-OA-locator-fallback dance inside add_doi
    is now a single acquire() call; when it comes back with bytes, the PDF
    is saved exactly as it was when the OA fallback used to find one."""
    from research_companion.acquire import Acquisition

    monkeypatch.setattr(
        fetch, "_doi_metadata",
        lambda doi, timeout=30.0: {"title": "T", "authors": [], "year": 2020, "abstract": ""},
    )
    monkeypatch.setattr(
        fetch, "acquire",
        lambda meta, **kw: (fake_pdf_bytes,
                            Acquisition(True, None, source="https://oa.org/found.pdf")),
    )

    meta = fetch.add_doi("10.9999/oa-test")

    assert store.pdf_path(meta.paper_id) is not None      # PDF saved
    assert meta.last_acquisition["obtained"] is True
    assert meta.last_acquisition["source"] == "https://oa.org/found.pdf"


def test_add_doi_saves_metadata_only_when_acquire_finds_nothing(
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture):
    """When acquire() reports no bytes at all (direct attempt and every OA
    candidate exhausted), add_doi still saves metadata — behavior unchanged
    from when the locator itself came back empty."""
    from research_companion.acquire import AcquireReason, Acquisition

    monkeypatch.setattr(
        fetch, "_doi_metadata",
        lambda doi, timeout=30.0: {"title": "T", "authors": [], "year": 2020, "abstract": ""},
    )
    monkeypatch.setattr(
        fetch, "acquire",
        lambda meta, **kw: (None, Acquisition(False, AcquireReason.NO_LOCATION_FOUND)),
    )

    meta = fetch.add_doi("10.9999/paywalled")

    assert store.pdf_path(meta.paper_id) is None  # metadata-only, exactly as today
    assert meta.last_acquisition["reason"] == "no_location_found"
    out = capsys.readouterr().out
    # The warning names the reason acq actually carries. It used to say
    # "(likely paywalled)" unconditionally -- a guess, and the wrong one for
    # the case that dominates the real data (an open-access article a bot
    # filter refused), which is exactly the wrong-cause report this branch
    # exists to remove.
    assert ("warning: could not download PDF for DOI 10.9999/paywalled — "
            "No PDF found in open-access sources. Metadata saved, but text "
            "extraction will not work without a PDF.") in out


def test_add_doi_survives_acquire_raising(monkeypatch: pytest.MonkeyPatch,
                                           capsys: pytest.CaptureFixture):
    """acquire() raising must not abort the whole add — same never-crash
    contract this seam has always kept (cli.py's add loop only catches
    FetchError). acquire() itself is documented to never raise; this proves
    add_doi survives even if it did."""
    monkeypatch.setattr(
        fetch, "_doi_metadata",
        lambda doi, timeout=30.0: {"title": "T", "authors": [], "year": 2020, "abstract": ""},
    )

    def raise_acquire(meta, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(fetch, "acquire", raise_acquire)

    meta = fetch.add_doi("10.9999/acquire-crashes")

    assert store.pdf_path(meta.paper_id) is None   # metadata-only, exactly as today
    assert meta.last_acquisition is not None        # the crash didn't lose the record
    out = capsys.readouterr().out
    # _acquire_safely's defensive fallback is SOURCE_UNAVAILABLE, and the
    # warning reports that rather than guessing at a paywall.
    assert ("warning: could not download PDF for DOI 10.9999/acquire-crashes — "
            "Couldn't reach the source — the host or the network was down. "
            "Metadata saved, but text extraction will not work without a "
            "PDF.") in out


def test_add_s2_saves_pdf_when_acquire_succeeds(monkeypatch: pytest.MonkeyPatch,
                                                 fake_pdf_bytes: bytes):
    """Same contract as the DOI case: add_s2's old arXiv/DOI/locator chain is
    now one acquire() call, and a hit is still saved."""
    from research_companion.acquire import Acquisition

    monkeypatch.setattr(
        fetch, "_s2_metadata",
        lambda s2_id, timeout=30.0: {
            "title": "T", "authors": [], "year": 2020, "abstract": "",
            "external_ids": {"ArXiv": "1234.5678", "DOI": "10.9999/s2-test"},
        },
    )
    monkeypatch.setattr(
        fetch, "acquire",
        lambda meta, **kw: (fake_pdf_bytes,
                            Acquisition(True, None, source="https://oa.org/s2-found.pdf")),
    )

    s2_id = "a" * 40
    meta = fetch.add_s2(s2_id)

    assert store.pdf_path(meta.paper_id) is not None
    assert meta.last_acquisition["obtained"] is True
    assert meta.last_acquisition["source"] == "https://oa.org/s2-found.pdf"


def test_add_s2_saves_metadata_only_when_acquire_finds_nothing(
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture):
    """When acquire() reports no bytes, add_s2 still saves metadata —
    behavior unchanged from when arXiv/DOI attempts and the locator all
    failed."""
    from research_companion.acquire import AcquireReason, Acquisition

    monkeypatch.setattr(
        fetch, "_s2_metadata",
        lambda s2_id, timeout=30.0: {
            "title": "T", "authors": [], "year": 2020, "abstract": "",
            "external_ids": {},
        },
    )
    monkeypatch.setattr(
        fetch, "acquire",
        lambda meta, **kw: (None, Acquisition(False, AcquireReason.NO_LOCATION_FOUND)),
    )

    s2_id = "b" * 40
    meta = fetch.add_s2(s2_id)

    assert store.pdf_path(meta.paper_id) is None
    assert meta.last_acquisition["reason"] == "no_location_found"
    out = capsys.readouterr().out
    assert (f"warning: could not download PDF for S2 paper {s2_id}. "
            f"Metadata saved, but text extraction will not work without a PDF.") in out


def test_add_s2_survives_acquire_raising(monkeypatch: pytest.MonkeyPatch,
                                          capsys: pytest.CaptureFixture):
    """Same never-crash contract for add_s2: an acquire() exception must not
    propagate out of add_s2."""
    monkeypatch.setattr(
        fetch, "_s2_metadata",
        lambda s2_id, timeout=30.0: {
            "title": "T", "authors": [], "year": 2020, "abstract": "",
            "external_ids": {},
        },
    )

    def raise_acquire(meta, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(fetch, "acquire", raise_acquire)

    s2_id = "c" * 40
    meta = fetch.add_s2(s2_id)

    assert store.pdf_path(meta.paper_id) is None
    assert meta.last_acquisition is not None
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
