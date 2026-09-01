"""The add paths, once acquisition is one call with one answer.

Three holes closed here, all of which made this class of failure invisible:
a failed add was never recorded anywhere, add_arxiv hard-raised so nothing
survived it at all, and re-adding a metadata-only paper short-circuited on
metadata and never retried the PDF.

Note (Task 7A scope): recording the failure onto store.record_failure and
lab_api's job-status plumbing is Task 7B's job, not this module's -- so the
assertions here stop at what fetch.py itself is responsible for: metadata is
always saved, last_acquisition carries the outcome, and nothing crashes.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from research_companion.acquire import AcquireReason, Acquisition


def _blocked():
    return None, Acquisition(False, AcquireReason.BLOCKED_BY_HOST)


def _ok():
    return b"%PDF-1.5\nx", Acquisition(True, None, source="https://arxiv.org/pdf/1")


def test_add_arxiv_no_longer_loses_everything_when_the_pdf_fails():
    """It used to raise, so there was no metadata, no failure record and no
    Find-PDF button -- the paper simply did not exist afterwards."""
    from research_companion import fetch
    with patch.object(fetch, "acquire", side_effect=lambda *a, **k: _blocked()), \
         patch.object(fetch, "_arxiv_metadata", return_value={
             "title": "T", "authors": ["A"], "year": 2024, "abstract": "",
             "arxiv_categories": []}):
        meta = fetch.add_arxiv("2501.02600")
    assert meta is not None
    assert meta.paper_id == "arxiv:2501.02600"
    assert meta.last_acquisition["reason"] == "blocked_by_host"


def test_add_arxiv_still_raises_when_the_metadata_itself_is_missing():
    """A bad id is a different failure and must stay loud."""
    from research_companion import fetch
    with patch.object(fetch, "_arxiv_metadata", return_value=None), pytest.raises(fetch.FetchError):
        fetch.add_arxiv("9999.99999")


def test_readding_a_metadata_only_paper_retries_the_pdf():
    """DOI and S2 short-circuited on metadata alone, so a paper that lost its
    PDF race could never recover by being added again."""
    from research_companion import fetch
    calls = []

    def once(*a, **k):
        calls.append(1)
        return _ok() if len(calls) > 1 else _blocked()

    with patch.object(fetch, "acquire", side_effect=once), \
         patch.object(fetch, "_doi_metadata", return_value={
             "title": "T", "authors": ["A"], "year": 2024, "abstract": "",
             "venue": "", "publisher": ""}):
        fetch.add_doi("10.1145/3732941")
        fetch.add_doi("10.1145/3732941")
    assert len(calls) == 2, "the second add must try again"


def test_readding_a_paper_that_has_its_pdf_does_not_refetch():
    from research_companion import fetch
    calls = []
    with patch.object(fetch, "acquire",
                      side_effect=lambda *a, **k: (calls.append(1), _ok())[1]), \
         patch.object(fetch, "_doi_metadata", return_value={
             "title": "T", "authors": ["A"], "year": 2024, "abstract": "",
             "venue": "", "publisher": ""}):
        fetch.add_doi("10.1145/3732941")
        fetch.add_doi("10.1145/3732941")
    assert len(calls) == 1


def test_the_acquisition_is_saved_on_the_metadata():
    from research_companion import fetch
    from research_companion.store import PaperMetadata
    with patch.object(fetch, "acquire", side_effect=lambda *a, **k: _blocked()), \
         patch.object(fetch, "_doi_metadata", return_value={
             "title": "T", "authors": ["A"], "year": 2024, "abstract": "",
             "venue": "", "publisher": ""}):
        fetch.add_doi("10.1145/3732941")
    reloaded = PaperMetadata.load("doi:10.1145/3732941")
    assert reloaded.last_acquisition["human_can_help"] is True


def test_try_download_pdf_is_gone():
    """It flattened 404, 403, timeout, HTML and the size cap into one None.
    Leaving it available invites the same bug back."""
    from research_companion import fetch
    assert not hasattr(fetch, "_try_download_pdf")


def test_oa_locator_is_gone():
    """Absorbed into acquire.sources so one place decides where a PDF comes
    from."""
    with pytest.raises(ImportError):
        import research_companion.oa_locator  # noqa: F401
