"""Tests for the OpenAlex prior-art fallback (no network)."""
from __future__ import annotations

import httpx

from research_companion import discover


def test_parse_openalex_work_full():
    w = {
        "display_name": "GRAG: Graph Retrieval-Augmented Generation",
        "publication_year": 2025,
        "cited_by_count": 47,
        "ids": {"doi": "https://doi.org/10.18653/v1/2025.findings-naacl.232"},
        "authorships": [{"author": {"display_name": "A One"}},
                        {"author": {"display_name": "B Two"}}],
        "abstract_inverted_index": {"Graph": [0], "methods": [1], "win": [2]},
    }
    p = discover._parse_openalex_work(w)
    assert p.title.startswith("GRAG")
    assert p.year == 2025 and p.citation_count == 47
    assert p.doi == "10.18653/v1/2025.findings-naacl.232"
    assert p.authors == ["A One", "B Two"]
    assert p.abstract == "Graph methods win"
    assert p.source == "openalex"


def test_parse_openalex_work_missing_title_is_none():
    assert discover._parse_openalex_work({"display_name": ""}) is None


def test_search_topic_with_fallback_uses_s2_when_it_works():
    calls = []

    def s2(query, **kw):
        calls.append("s2")
        return ["s2-result"]

    out = discover.search_topic_with_fallback("q", s2_search=s2,
                                              openalex_search=lambda q, **kw: ["oa"])
    assert out == ["s2-result"] and calls == ["s2"]


def test_search_topic_with_fallback_falls_to_openalex_on_s2_failure():
    def s2(query, **kw):
        raise httpx.HTTPStatusError("429", request=None, response=None)

    out = discover.search_topic_with_fallback("q", s2_search=s2,
                                              openalex_search=lambda q, **kw: ["oa-result"])
    assert out == ["oa-result"]
