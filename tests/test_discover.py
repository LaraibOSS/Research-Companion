"""Tests for research_companion.discover: prior-art merge with domain connectors."""
from __future__ import annotations

from research_companion.discover import DiscoveredPaper, search_topic_with_fallback


def _dp(title, **kw):
    base = dict(authors=[], year=2020, citation_count=0, arxiv_id=None, doi=None,
                s2_id=None, url="", abstract="", source="")
    base.update(kw)
    return DiscoveredPaper(title=title, **base)


def test_add_cmd_prefers_pmid():
    assert _dp("T", pmid="30449619").add_cmd == "research-companion add pmid:30449619"


def test_fallback_merges_connector_results_deduped(monkeypatch):
    base = [_dp("Base paper", doi="10.1/a")]
    conn_paper = _dp("Bio paper", pmid="123")
    dup = _dp("Base paper dup", doi="10.1/a")  # same doi => deduped out
    class _Conn:
        name = "europepmc"
        def search(self, q, *, limit):
            return [conn_paper, dup]
    monkeypatch.setattr("research_companion.connectors.enabled_connectors", lambda n: [_Conn()])
    out = search_topic_with_fallback(
        "q", connectors=["europepmc"],
        s2_search=lambda q, **kw: base, openalex_search=lambda q, **kw: base)
    titles = [p.title for p in out]
    assert "Bio paper" in titles
    assert titles.count("Base paper") == 1 and "Base paper dup" not in titles


def test_fallback_no_connectors_is_unchanged(monkeypatch):
    base = [_dp("Base", doi="10.1/a")]
    out = search_topic_with_fallback(
        "q", connectors=[], s2_search=lambda q, **kw: base, openalex_search=lambda q, **kw: base)
    assert [p.title for p in out] == ["Base"]
