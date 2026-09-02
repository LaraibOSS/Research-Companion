"""The whole path a 403'd DOI takes, from `add` to what the user reads.

All 17 real recorded failures in this codebase say the same thing:

    no PDF on disk for doi:10.1145/3732941

That is the symptom, observed three stages downstream of the cause. The
typed chain, the host-class ranking, the taxonomy and the Needs-you queue
were all built to replace it -- and every one of them was unit-tested in
isolation while the path that actually fails reached none of them:

  * ``add_doi``/``add_s2``/``add_arxiv`` do NOT raise when the PDF cannot be
    got. They save the metadata, print a warning and return -- so the add
    job SUCCEEDS, and lab_api's add-failure except-block (the only place on
    the add path that wrote an ``acquisition`` onto a failure record) never
    fired.
  * The ingest pipeline then failed at extract.py, and research_companion/lab
    recorded ``{"stage": "sections", "error": "no PDF on disk for ..."}``
    with no ``acquisition`` key at all. ``record_failure`` replaces the whole
    record, so nothing survived there either.
  * ``PaperMetadata.last_acquisition`` was written by every add and read
    nowhere.

Net effect: the exact string this branch exists to eliminate was still what
the user saw, the paper never appeared under Needs you, and no "Open at
publisher" button was offered.

This test drives that whole path -- real acquire() over a mocked network,
real add_doi, real ingest_one, real HTTP endpoints -- and asserts what the
user ends up with. Its absence is why the gap survived review.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from research_companion import fetch, store
from research_companion.agents.bus import Bus
from research_companion.lab import ingest_one
from research_companion.lab_api import create_lab_app

DOI = "10.1145/3732941"
PAPER_ID = f"doi:{DOI}"
ACM_PDF = "https://dl.acm.org/doi/pdf/10.1145/3732941"
TITLE = "Thermal- and Power-Aware Scheduling"

# The symptom string. It must not appear on any surface a user reads.
SYMPTOM = "no PDF on disk"


def _acm_refuses(request):
    """ACM answers 403 with an HTML body for an article ACM itself declares
    open access -- verified live against two of the real URLs."""
    url = str(request.url)
    if "doi.org" in url:
        # The DOI resolver hands the robot straight to the publisher.
        return httpx.Response(302, headers={"location": ACM_PDF})
    if "dl.acm.org" in url:
        return httpx.Response(403, headers={"content-type": "text/html"},
                              text="<html>Forbidden</html>")
    return httpx.Response(404)


@pytest.fixture
def blocked_paper(monkeypatch, isolated_papergraph_dir):
    """A DOI paper added exactly the way production adds one, whose PDF the
    host refused with a 403. Nothing here fakes the Acquisition: acquire()
    runs for real over a mock transport and classifies the outcome itself."""
    monkeypatch.setattr(fetch, "_doi_metadata", lambda doi, timeout=30.0: {
        "title": TITLE, "authors": ["A. Author"], "year": 2025,
        "abstract": "An abstract."})

    transport = httpx.MockTransport(_acm_refuses)
    fetchers = {
        "s2": lambda *a, **k: None,
        "unpaywall": lambda *a, **k: None,
        "openalex": lambda *a, **k: {"locations": [{"pdf_url": ACM_PDF}]},
        "arxiv_title": lambda *a, **k: None,
        "pmc_title": lambda *a, **k: None,
    }

    def _acquire(meta, **kwargs):
        from research_companion.acquire import acquire as real_acquire
        return real_acquire(meta, settings={}, transport=transport,
                            sleep=lambda s: None, fetchers=fetchers)

    monkeypatch.setattr(fetch, "acquire", _acquire)

    meta = fetch.add_doi(DOI)
    # The add SUCCEEDED (metadata saved, no exception) -- this is the branch
    # of the path that made the whole chain unreachable.
    assert store.pdf_path(PAPER_ID) is None
    assert meta.last_acquisition["reason"] == "blocked_by_host"

    # ...and then ingest fails three stages later, with the symptom string.
    asyncio.run(ingest_one(meta, DOI, bus=Bus(), provider="anthropic",
                           model=None, align=False, aligner=None,
                           strengther=None, extractor=None, sectioner=None))
    return meta


def _summary(client, paper_id=PAPER_ID):
    papers = client.get("/api/papers").json()
    return next(p for p in papers if p["paper_id"] == paper_id)


def test_the_failure_record_names_the_cause_not_the_symptom(blocked_paper):
    info = next(iter(store.list_failures().values()))
    assert SYMPTOM not in info["error"]
    assert info["acquisition"]["reason"] == "blocked_by_host"
    assert info["acquisition"]["human_can_help"] is True


def test_the_paper_summary_carries_the_acquisition(blocked_paper):
    client = TestClient(create_lab_app(Bus()))
    paper = _summary(client)

    assert paper["status"] == "failed"
    acq = paper["acquisition"]
    assert acq is not None, "the typed outcome must reach GET /api/papers"
    assert acq["reason"] == "blocked_by_host"
    assert acq["human_can_help"] is True
    # 6.5: the copy names the host that refused and says a browser can get it.
    assert "ACM" in acq["headline"]
    assert "browser" in acq["detail"].lower()


def test_the_symptom_string_reaches_no_surface_the_user_reads(blocked_paper):
    client = TestClient(create_lab_app(Bus()))
    paper = _summary(client)
    # failure_reason is rendered inline AND as the card's full-reason
    # tooltip, so the raw sentence must be gone from it too, not merely
    # overridden at one render site.
    assert SYMPTOM not in (paper["failure_reason"] or "")
    assert SYMPTOM not in client.get("/api/papers").text
    assert SYMPTOM not in client.get("/api/acquire/queue").text


def test_the_paper_appears_under_needs_you(blocked_paper):
    client = TestClient(create_lab_app(Bus()))
    queued = client.get("/api/acquire/queue").json()["papers"]
    assert [p["paper_id"] for p in queued] == [PAPER_ID]
    assert queued[0]["title"] == TITLE
    assert queued[0]["acquisition"]["human_can_help"] is True


def test_open_at_publisher_has_a_url_to_open(blocked_paper):
    """7.2: the highest-ranked candidate a browser can use. For this case
    that is the dl.acm.org URL that 403'd the robot and opens fine for a
    person -- NOT the doi.org resolver acquire() tried first."""
    client = TestClient(create_lab_app(Bus()))
    attempts = _summary(client)["acquisition"]["attempts"]
    urls = [a["url"] for a in attempts]
    assert ACM_PDF in urls
    assert all(u.startswith("https://") for u in urls)


def test_a_legacy_record_with_no_acquisition_still_gets_there(blocked_paper):
    """The 17 records already on disk were written before an acquisition was
    ever attached, and record_failure replaces the whole record -- so the
    fallback to the paper's own last_acquisition is what rescues them, not
    the enrichment at record time."""
    key, info = next(iter(store.list_failures().items()))
    stripped = {k: v for k, v in info.items() if k != "acquisition"}
    stripped["error"] = f"{SYMPTOM} for {PAPER_ID}"
    store.record_failure(key, stripped)
    assert "acquisition" not in store.list_failures()[key]

    client = TestClient(create_lab_app(Bus()))
    paper = _summary(client)
    assert paper["acquisition"]["reason"] == "blocked_by_host"
    assert SYMPTOM not in paper["failure_reason"]
    assert [p["paper_id"] for p in
            client.get("/api/acquire/queue").json()["papers"]] == [PAPER_ID]


def test_a_parse_failure_on_a_paper_that_has_a_pdf_is_left_alone(blocked_paper):
    """The fallback must describe THIS failure. Once a PDF is on disk the
    paper's stored acquisition is stale history, and a parse/OCR/graph
    failure must keep its own error -- offering to re-acquire would overwrite
    a file the user already has."""
    store.save_pdf(PAPER_ID, b"%PDF-1.5\nbody")
    key, _info = next(iter(store.list_failures().items()))
    store.record_failure(key, {"stage": "extract", "paper_id": PAPER_ID,
                               "error": "Failed to parse the PDF (boom)"})

    client = TestClient(create_lab_app(Bus()))
    paper = _summary(client)
    assert paper["acquisition"] is None
    assert paper["failure_reason"] == "Failed to parse the PDF (boom)"
    assert client.get("/api/acquire/queue").json()["papers"] == []
