"""Tests for papergraph.refcheck.retrieval — CrossRef/OpenAlex lookups.

HTTP is never hit: the thin search functions are monkeypatched, and the
response parsers are pure and tested directly.
"""
from __future__ import annotations

from papergraph.refcheck import retrieval
from papergraph.refcheck.validate import Reference

# --- CrossRef item parser (pure) --------------------------------------------

def test_parse_crossref_item_full():
    item = {
        "title": ["Attention Is All You Need"],
        "author": [
            {"given": "Ashish", "family": "Vaswani"},
            {"given": "Noam", "family": "Shazeer"},
        ],
        "issued": {"date-parts": [[2017, 6, 12]]},
        "DOI": "10.5555/3295222.3295349",
    }
    record = retrieval.parse_crossref_item(item)
    assert record["title"] == "Attention Is All You Need"
    assert record["authors"] == ["Ashish Vaswani", "Noam Shazeer"]
    assert record["year"] == 2017
    assert record["doi"] == "10.5555/3295222.3295349"
    assert record["arxiv_id"] is None


def test_parse_crossref_item_handles_missing_fields():
    record = retrieval.parse_crossref_item({})
    assert record["title"] == ""
    assert record["authors"] == []
    assert record["year"] is None
    assert record["doi"] is None


# --- OpenAlex item parser (pure) --------------------------------------------

def test_parse_openalex_item_full():
    item = {
        "title": "Attention Is All You Need",
        "publication_year": 2017,
        "doi": "https://doi.org/10.5555/3295222.3295349",
        "authorships": [
            {"author": {"display_name": "Ashish Vaswani"}},
            {"author": {"display_name": "Noam Shazeer"}},
        ],
    }
    record = retrieval.parse_openalex_item(item)
    assert record["title"] == "Attention Is All You Need"
    assert record["authors"] == ["Ashish Vaswani", "Noam Shazeer"]
    assert record["year"] == 2017
    # DOI is normalized to the bare form, stripping the doi.org URL prefix.
    assert record["doi"] == "10.5555/3295222.3295349"


def test_parse_openalex_item_handles_missing_fields():
    record = retrieval.parse_openalex_item({})
    assert record["title"] == ""
    assert record["authors"] == []
    assert record["year"] is None
    assert record["doi"] is None


# --- crossref_lookup (search + parse + best-match) --------------------------

def _search_returning(items):
    def _search(query, **kwargs):
        return items
    return _search


def test_crossref_lookup_returns_best_title_match():
    ref = Reference(title="Attention Is All You Need", authors=["Vaswani"])
    items = [
        {"title": ["A Survey of Reinforcement Learning"], "author": [], "DOI": "10.0/wrong"},
        {
            "title": ["Attention Is All You Need"],
            "author": [{"given": "Ashish", "family": "Vaswani"}],
            "DOI": "10.5555/right",
        },
    ]
    record = retrieval.crossref_lookup(ref, search=_search_returning(items))
    assert record["doi"] == "10.5555/right"


def test_crossref_lookup_none_when_no_results():
    ref = Reference(title="Attention Is All You Need")
    assert retrieval.crossref_lookup(ref, search=_search_returning([])) is None


def test_crossref_lookup_none_when_no_plausible_match():
    ref = Reference(title="Attention Is All You Need")
    items = [{"title": ["Completely Unrelated Paper About Frog Migration"], "author": []}]
    assert retrieval.crossref_lookup(ref, search=_search_returning(items)) is None


# --- openalex_lookup --------------------------------------------------------

def test_openalex_lookup_returns_best_title_match():
    ref = Reference(title="Attention Is All You Need")
    items = [
        {"title": "Frog Migration Patterns", "authorships": []},
        {
            "title": "Attention Is All You Need",
            "publication_year": 2017,
            "doi": "https://doi.org/10.5555/right",
            "authorships": [{"author": {"display_name": "Ashish Vaswani"}}],
        },
    ]
    record = retrieval.openalex_lookup(ref, search=_search_returning(items))
    assert record["doi"] == "10.5555/right"
    assert record["year"] == 2017


def test_openalex_lookup_none_when_no_results():
    ref = Reference(title="Attention Is All You Need")
    assert retrieval.openalex_lookup(ref, search=_search_returning([])) is None


# --- chained_lookup (fallback across sources) -------------------------------

def test_chained_lookup_falls_back_to_second_source():
    ref = Reference(title="Attention Is All You Need")
    record = {"title": "Attention Is All You Need", "authors": [], "year": 2017,
              "doi": "10.5555/x", "arxiv_id": None}
    lookup = retrieval.chained_lookup(lambda r: None, lambda r: record)
    assert lookup(ref) is record


def test_chained_lookup_short_circuits_on_first_hit():
    ref = Reference(title="Attention Is All You Need")
    record = {"title": "Attention Is All You Need", "authors": []}

    def _boom(r):
        raise AssertionError("second retriever should not be called")

    lookup = retrieval.chained_lookup(lambda r: record, _boom)
    assert lookup(ref) is record


def test_chained_lookup_returns_none_when_all_miss():
    ref = Reference(title="Attention Is All You Need")
    lookup = retrieval.chained_lookup(lambda r: None, lambda r: None)
    assert lookup(ref) is None
