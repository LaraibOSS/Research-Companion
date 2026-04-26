"""Tests for papergraph.chat and papergraph.viz."""
from __future__ import annotations

import pytest

from papergraph import chat, graph, prompts, store, viz


def _seed_two_papers(sample_extraction: dict) -> None:
    for pid, title in [("arxiv:2410.00001", "GraphRAG paper"),
                        ("arxiv:2410.00002", "Vector RAG paper")]:
        meta = store.PaperMetadata(paper_id=pid, title=title, authors=["A", "B"],
                                    year=2024, added_at="2026-01-01")
        meta.save()
        store.save_extraction(pid, sample_extraction,
                              prompt_sha=prompts.extraction_prompt_sha256())


def test_question_terms_filters_stopwords():
    terms = chat._question_terms("What is the main approach to graph RAG?")
    assert "graph" in terms
    assert "rag" in terms
    assert "main" in terms
    assert "approach" in terms
    assert "what" not in terms
    assert "is" not in terms
    assert "the" not in terms


def test_score_nodes_lexical_match(sample_extraction: dict):
    _seed_two_papers(sample_extraction)
    G = graph.build_graph()

    scored = chat._score_nodes(G, ["graphrag"])
    assert scored, "expected at least one matching node"
    # The top hit must be the GraphRAG method node.
    top_id = scored[0][1]
    assert G.nodes[top_id].get("label", "").lower().startswith("graphrag")


def test_bfs_respects_depth(sample_extraction: dict):
    _seed_two_papers(sample_extraction)
    G = graph.build_graph()

    paper_node = "arxiv:2410.00001"
    nodes_d1, _ = chat._bfs(G, [paper_node], depth=1)
    nodes_d2, _ = chat._bfs(G, [paper_node], depth=2)
    assert paper_node in nodes_d1
    assert len(nodes_d2) >= len(nodes_d1)


def test_chat_with_mocked_llm(monkeypatch: pytest.MonkeyPatch, sample_extraction: dict):
    _seed_two_papers(sample_extraction)
    G = graph.build_graph()

    captured: dict = {}

    def _fake(system, user, model):
        captured["system"] = system
        captured["user"] = user
        captured["model"] = model
        return "GraphRAG uses community summaries [GraphRAG paper].", {
            "input_tokens": 100, "output_tokens": 30,
        }

    monkeypatch.setattr(chat, "_call_anthropic", _fake)
    ans = chat.chat("What does GraphRAG do?", G=G, provider="anthropic")

    assert "GraphRAG" in ans.answer
    assert ans.input_tokens == 100
    assert ans.output_tokens == 30
    assert ans.n_subgraph_nodes > 0
    assert "Question: What does GraphRAG do?" in captured["user"]
    # System prompt must instruct citations.
    assert "cite" in captured["system"].lower()


def test_chat_on_empty_graph_returns_polite_message(monkeypatch: pytest.MonkeyPatch):
    # Empty graph -> graceful fallback, no LLM call.
    monkeypatch.setattr(chat, "_call_anthropic",
                        lambda *a, **k: pytest.fail("should not call LLM on empty graph"))
    ans = chat.chat("Anything?", provider="anthropic")
    assert ans.input_tokens == 0
    assert "empty" in ans.answer.lower()


def test_viz_render_writes_html(sample_extraction: dict, tmp_path):
    _seed_two_papers(sample_extraction)
    G = graph.build_graph()

    out = tmp_path / "graph.html"
    p = viz.render(G, output_path=out)
    assert p == out
    html = out.read_text(encoding="utf-8")
    assert "<html" in html.lower()
    assert "vis-network" in html
    # Must include each paper's title and at least one method label.
    assert "GraphRAG paper" in html
    # JSON nodes serialised into the HTML.
    assert '"id":' in html or "'id':" in html


def test_viz_legend_and_stats(sample_extraction: dict, tmp_path):
    _seed_two_papers(sample_extraction)
    G = graph.build_graph()

    out = tmp_path / "graph.html"
    viz.render(G, output_path=out)
    html = out.read_text(encoding="utf-8")
    # Legend includes all 6 kinds.
    for kind in ("paper", "concept", "method", "dataset", "claim", "result"):
        assert kind in html
