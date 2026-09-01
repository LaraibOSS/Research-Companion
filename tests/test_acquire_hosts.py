"""Which host to ask first.

The locator read only OpenAlex's `best_oa_location` -- one URL, chosen for
bibliographic quality, not for whether a robot may fetch it. For the ACM
papers that URL is dl.acm.org, which answers 403, and there was no second
candidate to fall back to.
"""
from __future__ import annotations

import pytest

from research_companion.acquire import HostClass
from research_companion.acquire.hosts import classify_host, rank_candidates


@pytest.mark.parametrize("url,expected", [
    ("https://arxiv.org/pdf/2501.02600", HostClass.NATIVE),
    ("https://www.ncbi.nlm.nih.gov/pmc/articles/PMC123/pdf", HostClass.NATIVE),
    ("https://europepmc.org/articles/PMC123?pdf=render", HostClass.NATIVE),
    ("https://ink.library.smu.edu.sg/cgi/viewcontent.cgi?article=1", HostClass.REPOSITORY),
    ("https://zenodo.org/record/123/files/paper.pdf", HostClass.REPOSITORY),
    ("https://core.ac.uk/download/pdf/123.pdf", HostClass.REPOSITORY),
    ("https://hal.science/hal-0123/document", HostClass.REPOSITORY),
    ("https://www.biorxiv.org/content/10.1101/123v1.full.pdf", HostClass.PREPRINT),
    ("https://openreview.net/pdf?id=abc", HostClass.PREPRINT),
    ("https://dl.acm.org/doi/pdf/10.1145/3732941", HostClass.PUBLISHER),
    ("https://ieeexplore.ieee.org/stamp/stamp.jsp?arnumber=1", HostClass.PUBLISHER),
    ("https://link.springer.com/content/pdf/10.1007/x.pdf", HostClass.PUBLISHER),
])
def test_known_hosts_are_classified(url, expected):
    assert classify_host(url) == expected


def test_an_unknown_host_is_assumed_to_be_a_publisher():
    """The conservative default: try it last rather than ahead of a repository
    we know will answer."""
    assert classify_host("https://journal.example.org/paper.pdf") == HostClass.PUBLISHER


@pytest.mark.parametrize("bad", ["", "not a url", "ftp://x/y.pdf", None])
def test_classification_never_raises(bad):
    assert classify_host(bad) == HostClass.PUBLISHER


def test_ranking_puts_a_repository_before_a_publisher():
    """The whole point: the ACM copy 403s, the repository copy does not."""
    out = rank_candidates([
        "https://dl.acm.org/doi/pdf/10.1145/3767742",
        "https://ink.library.smu.edu.sg/cgi/viewcontent.cgi?article=1",
    ])
    assert "smu.edu.sg" in out[0]
    assert "dl.acm.org" in out[1]


def test_ranking_puts_native_first_of_all():
    out = rank_candidates([
        "https://dl.acm.org/doi/pdf/10.1145/1",
        "https://zenodo.org/record/1/files/p.pdf",
        "https://arxiv.org/pdf/2501.02600",
    ])
    assert out == [
        "https://arxiv.org/pdf/2501.02600",
        "https://zenodo.org/record/1/files/p.pdf",
        "https://dl.acm.org/doi/pdf/10.1145/1",
    ]


def test_ranking_is_stable_within_a_class():
    """Two publisher URLs keep the order the indexes gave them -- we have no
    basis for preferring one, and reordering would make runs unrepeatable."""
    urls = ["https://dl.acm.org/a.pdf", "https://ieeexplore.ieee.org/b.pdf"]
    assert rank_candidates(urls) == urls


def test_ranking_dedupes_while_preserving_first_position():
    urls = ["https://arxiv.org/pdf/1", "https://dl.acm.org/a", "https://arxiv.org/pdf/1"]
    assert rank_candidates(urls) == ["https://arxiv.org/pdf/1", "https://dl.acm.org/a"]


def test_ranking_drops_empty_and_non_http_entries():
    assert rank_candidates(["", None, "ftp://x/y", "https://arxiv.org/pdf/1"]) == [
        "https://arxiv.org/pdf/1"]


def test_ranking_an_empty_list_is_empty():
    assert rank_candidates([]) == []
