"""Asking the indexes for EVERY copy, not just the best one.

Two failures motivated this. OpenAlex's best_oa_location is one URL chosen for
bibliographic quality, so a paper with a repository copy and a publisher copy
offered us only the publisher. And the arxiv provider only fired when another
service volunteered an arXiv id -- it never searched by title, so preprints of
paywalled papers were invisible.
"""
from __future__ import annotations

from types import SimpleNamespace

from research_companion.acquire.sources import (
    _parse_arxiv_feed,
    _parse_openalex_locations,
    _parse_pmc_result,
    collect_candidates,
)


def _meta(paper_id="doi:10.1145/3767742", title="A Paper"):
    return SimpleNamespace(paper_id=paper_id, title=title, authors=[], year=2024)


# --- OpenAlex: all locations -------------------------------------------------

def test_every_location_is_collected_not_just_the_best():
    payload = {
        "best_oa_location": {"pdf_url": "https://dl.acm.org/doi/pdf/10.1145/3767742"},
        "locations": [
            {"pdf_url": "https://dl.acm.org/doi/pdf/10.1145/3767742"},
            {"pdf_url": "https://ink.library.smu.edu.sg/cgi/viewcontent.cgi?a=1"},
        ],
    }
    urls = _parse_openalex_locations(payload)
    assert "https://ink.library.smu.edu.sg/cgi/viewcontent.cgi?a=1" in urls
    assert "https://dl.acm.org/doi/pdf/10.1145/3767742" in urls


def test_locations_without_a_pdf_url_are_skipped():
    payload = {"locations": [{"pdf_url": None, "landing_page_url": "https://x/"},
                             {"pdf_url": "https://zenodo.org/p.pdf"}]}
    assert _parse_openalex_locations(payload) == ["https://zenodo.org/p.pdf"]


def test_a_malformed_payload_yields_nothing():
    for bad in (None, {}, {"locations": None}, {"locations": [None, 3]}, "nope"):
        assert _parse_openalex_locations(bad) == []


# --- arXiv by title ----------------------------------------------------------

_FEED = """<feed xmlns="http://www.w3.org/2005/Atom">
  <entry><id>http://arxiv.org/abs/2501.02600v1</id>
  <title>TAPAS: Thermal- and Power-Aware Scheduling for LLM Inference</title></entry>
</feed>"""


def test_a_preprint_is_found_by_title():
    """This is what recovers TAPAS and NeuPIMs, both of which sit in the
    failure log today reading 'no PDF on disk'."""
    got = _parse_arxiv_feed(
        _FEED, "TAPAS: Thermal- and Power-Aware Scheduling for LLM Inference")
    assert got == "2501.02600"


def test_the_version_suffix_is_stripped():
    assert not (_parse_arxiv_feed(_FEED, "TAPAS: Thermal- and Power-Aware "
                                         "Scheduling for LLM Inference") or "").endswith("v1")


def test_a_title_that_does_not_match_is_rejected():
    """A title search returns near-misses; accepting one would attach the wrong
    PDF to a paper, which is worse than not finding it."""
    assert _parse_arxiv_feed(_FEED, "Something Entirely Different") is None


def test_matching_ignores_case_and_punctuation():
    got = _parse_arxiv_feed(
        _FEED, "tapas thermal and power aware scheduling for llm inference")
    assert got == "2501.02600"


def test_an_empty_feed_yields_nothing():
    assert _parse_arxiv_feed("<feed></feed>", "Anything") is None


def test_parsing_junk_never_raises():
    for bad in ("", "<<<", None):
        assert _parse_arxiv_feed(bad, "x") is None


# --- EuropePMC by title -------------------------------------------------------
# Payload shape verified live against the real API (2026-09-01, query
# TITLE:"A rapid and low-cost protocol" AND OPEN_ACCESS:Y, resultType=core):
# resultList.result[].fullTextUrlList.fullTextUrl[] entries each carry a
# documentStyle ("doi" | "html" | "pdf" | ...) and a url; "pdf" is the direct
# PDF link. Trimmed here to the fields the parser reads.

_PMC_PAYLOAD = {
    "resultList": {
        "result": [
            {
                "id": "34977991",
                "pmcid": "PMC8720503",
                "title": "A Rapid and Low-Cost Protocol",
                "isOpenAccess": "Y",
                "fullTextUrlList": {
                    "fullTextUrl": [
                        {"availability": "Subscription required",
                         "documentStyle": "doi",
                         "url": "https://doi.org/10.1007/x"},
                        {"availability": "Open access",
                         "documentStyle": "html",
                         "url": "https://europepmc.org/articles/PMC8720503"},
                        {"availability": "Open access",
                         "documentStyle": "pdf",
                         "url": "https://europepmc.org/articles/PMC8720503?pdf=render"},
                    ]
                },
            }
        ]
    }
}


def test_a_pmc_result_is_found_by_title():
    got = _parse_pmc_result(_PMC_PAYLOAD, "A Rapid and Low-Cost Protocol")
    assert got == "https://europepmc.org/articles/PMC8720503?pdf=render"


def test_pmc_matching_ignores_case_and_punctuation():
    got = _parse_pmc_result(_PMC_PAYLOAD, "a rapid and low cost protocol")
    assert got == "https://europepmc.org/articles/PMC8720503?pdf=render"


def test_a_pmc_title_that_does_not_match_is_rejected():
    """As with arXiv: a near-miss must not be accepted, since attaching the
    wrong PDF to a paper is worse than finding nothing."""
    assert _parse_pmc_result(_PMC_PAYLOAD, "Something Entirely Different") is None


def test_a_pmc_result_without_an_open_access_pdf_link_yields_nothing():
    payload = {
        "resultList": {
            "result": [
                {
                    "title": "A Rapid and Low-Cost Protocol",
                    "fullTextUrlList": {
                        "fullTextUrl": [
                            {"documentStyle": "doi", "url": "https://doi.org/x"},
                            {"documentStyle": "html", "url": "https://europepmc.org/x"},
                        ]
                    },
                }
            ]
        }
    }
    assert _parse_pmc_result(payload, "A Rapid and Low-Cost Protocol") is None


def test_a_malformed_pmc_payload_never_raises():
    for bad in (None, {}, "nope", {"resultList": None},
                {"resultList": {"result": "nope"}},
                {"resultList": {"result": [None, 3]}}):
        assert _parse_pmc_result(bad, "A Rapid and Low-Cost Protocol") is None


# --- orchestration -----------------------------------------------------------

def test_candidates_come_from_every_provider_that_answers():
    fetchers = {
        "s2": lambda ids, title: {"openAccessPdf": {"url": "https://zenodo.org/a.pdf"}},
        "unpaywall": lambda doi, email: {
            "best_oa_location": {"url_for_pdf": "https://core.ac.uk/b.pdf"}},
        "openalex": lambda ids, title: {
            "locations": [{"pdf_url": "https://dl.acm.org/c.pdf"}]},
        "arxiv_title": lambda title: None,
        "pmc_title": lambda title: None,
    }
    urls = collect_candidates(_meta(), settings={"contact_email": "a@b.c"},
                              fetchers=fetchers)
    assert set(urls) == {"https://zenodo.org/a.pdf", "https://core.ac.uk/b.pdf",
                         "https://dl.acm.org/c.pdf"}


def test_unpaywall_is_skipped_without_a_contact_email():
    """Unpaywall requires an email by policy; calling it without one is a
    request we know will be refused."""
    called = []
    fetchers = {
        "s2": lambda ids, title: None,
        "unpaywall": lambda doi, email: called.append(doi),
        "openalex": lambda ids, title: None,
        "arxiv_title": lambda title: None,
        "pmc_title": lambda title: None,
    }
    collect_candidates(_meta(), settings={"contact_email": ""}, fetchers=fetchers)
    assert called == []


def test_a_provider_that_raises_contributes_nothing_and_does_not_stop_the_rest():
    def boom(*a, **k):
        raise RuntimeError("openalex is down")

    fetchers = {
        "s2": lambda ids, title: {"openAccessPdf": {"url": "https://zenodo.org/a.pdf"}},
        "unpaywall": lambda doi, email: None,
        "openalex": boom,
        "arxiv_title": lambda title: None,
        "pmc_title": lambda title: None,
    }
    urls = collect_candidates(_meta(), settings={"contact_email": "a@b.c"},
                              fetchers=fetchers)
    assert urls == ["https://zenodo.org/a.pdf"]


def test_an_arxiv_id_found_by_title_becomes_a_pdf_url():
    fetchers = {
        "s2": lambda ids, title: None,
        "unpaywall": lambda doi, email: None,
        "openalex": lambda ids, title: None,
        "arxiv_title": lambda title: "2501.02600",
        "pmc_title": lambda title: None,
    }
    urls = collect_candidates(_meta(), settings={}, fetchers=fetchers)
    assert urls == ["https://arxiv.org/pdf/2501.02600"]


def test_a_paper_with_no_identifiers_and_no_title_yields_nothing():
    fetchers = {k: (lambda *a, **k: None) for k in
                ("s2", "unpaywall", "openalex", "arxiv_title", "pmc_title")}
    assert collect_candidates(_meta(paper_id="local:abc", title=""),
                              settings={}, fetchers=fetchers) == []
