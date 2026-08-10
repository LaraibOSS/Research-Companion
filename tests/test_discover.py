"""Tests for research_companion.discover: prior-art merge with domain connectors."""
from __future__ import annotations

import json

from research_companion.discover import DiscoveredPaper, search_topic_with_fallback


def _dp(title, **kw):
    base = dict(authors=[], year=2020, citation_count=0, arxiv_id=None, doi=None,
                s2_id=None, url="", abstract="", source="")
    base.update(kw)
    return DiscoveredPaper(title=title, **base)


def test_add_cmd_prefers_pmid():
    assert _dp("T", pmid="30449619").add_cmd == "research-companion add pmid:30449619"


def test_to_dict_includes_s2_id_for_s2_only_results():
    # The Brainstorm Add flow uses the bare s2_id as its add target; if to_dict
    # drops it, an S2-only hit falls through to its unparseable landing URL.
    d = _dp("T", s2_id="0123456789abcdef0123456789abcdef01234567",
            url="https://www.semanticscholar.org/paper/0123456789abcdef0123456789abcdef01234567").to_dict()
    assert d["s2_id"] == "0123456789abcdef0123456789abcdef01234567"


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


# ---------------------------------------------------------------------------
# expand_query (feat/brainstorm-discover, Task 1)
# ---------------------------------------------------------------------------

def test_discover_expand_prompt_sha256_is_stable_and_64_hex_chars():
    from research_companion.prompts import discover_expand_prompt_sha256
    sha = discover_expand_prompt_sha256()
    assert sha == discover_expand_prompt_sha256()
    assert len(sha) == 64
    int(sha, 16)  # raises ValueError if not hex


def test_format_discover_expand_prompt_substitutes_title():
    from research_companion.prompts import format_discover_expand_prompt
    rendered = format_discover_expand_prompt("graph neural networks for code")
    assert "graph neural networks for code" in rendered
    assert "<<TITLE>>" not in rendered


def test_expand_query_no_llm_returns_title_only():
    from research_companion.discover import expand_query
    assert expand_query("graph neural networks for code") == ["graph neural networks for code"]


def test_expand_query_llm_appends_up_to_five_total():
    from research_companion.discover import expand_query

    def fake_llm(prompt: str) -> str:
        assert "graph neural networks" in prompt
        return json.dumps({"queries": [
            "GNN code representation",
            "program graph learning",
            "AST neural embeddings",
            "code2vec",
            "one query too many",
        ]})

    out = expand_query("graph neural networks", llm=fake_llm)
    assert out[0] == "graph neural networks"
    assert len(out) == 5
    assert "GNN code representation" in out
    assert "one query too many" not in out  # capped at 5 total


def test_expand_query_dedupes_case_insensitively_against_title():
    from research_companion.discover import expand_query

    def fake_llm(prompt: str) -> str:
        return json.dumps({"queries": ["Graph Neural Networks", "new query"]})

    out = expand_query("graph neural networks", llm=fake_llm)
    assert out == ["graph neural networks", "new query"]


def test_expand_query_llm_exception_falls_back_to_title():
    from research_companion.discover import expand_query

    def bad_llm(prompt: str) -> str:
        raise RuntimeError("provider unreachable")

    assert expand_query("some topic", llm=bad_llm) == ["some topic"]


def test_expand_query_bad_json_falls_back_to_title():
    from research_companion.discover import expand_query

    def bad_llm(prompt: str) -> str:
        return "not json at all"

    assert expand_query("some topic", llm=bad_llm) == ["some topic"]


def test_expand_query_non_list_queries_field_falls_back_to_title():
    from research_companion.discover import expand_query

    def bad_llm(prompt: str) -> str:
        return json.dumps({"queries": "not-a-list"})

    assert expand_query("some topic", llm=bad_llm) == ["some topic"]


def test_expand_query_strips_markdown_fences():
    from research_companion.discover import expand_query

    def fenced_llm(prompt: str) -> str:
        return "```json\n" + json.dumps({"queries": ["extra query"]}) + "\n```"

    out = expand_query("some topic", llm=fenced_llm)
    assert out == ["some topic", "extra query"]
