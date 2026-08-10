"""Tests for research_companion.deep_research and its REPORT_QUESTIONS_PROMPT
triad (Deep-Research Report, slice 2e-1).

Pipeline under test: generate_questions (one REPORT_QUESTIONS_PROMPT LLM
call, never raises; a degenerate/empty question list is treated as a
failure, mirroring scaffold.generate_outline's empty-outline rule) ->
build_report (pure orchestration over an injectable
answer_fn(question) -> QAAnswer-like object -- qa.answer's own citations
and quote-verification flow straight into the report; nothing is
fabricated, no fresh retrieval code is written here).
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# REPORT_QUESTIONS_PROMPT triad (Task 1)
# ---------------------------------------------------------------------------


def test_report_questions_prompt_sha256_is_stable_and_64_hex_chars():
    from research_companion.prompts import report_questions_prompt_sha256
    sha = report_questions_prompt_sha256()
    assert sha == report_questions_prompt_sha256()
    assert len(sha) == 64
    int(sha, 16)  # raises ValueError if not hex


def test_format_report_questions_prompt_substitutes_all_placeholders():
    from research_companion.prompts import format_report_questions_prompt
    rendered = format_report_questions_prompt(
        topic="graph retrieval for code search",
        grounding_block="- Paper: GraphRAG for code retrieval (2023).",
        max_questions=6,
    )
    assert "graph retrieval for code search" in rendered
    assert "GraphRAG for code retrieval (2023)." in rendered
    assert "6" in rendered
    assert "<<TOPIC>>" not in rendered
    assert "<<GROUNDING_BLOCK>>" not in rendered
    assert "<<MAX_QUESTIONS>>" not in rendered


# ---------------------------------------------------------------------------
# _report_grounding_block
# ---------------------------------------------------------------------------

class _FakeGraph:
    """Minimal stand-in for a networkx graph -- only .nodes(data=True) is used
    by directions._underexplored_concepts."""
    def __init__(self, nodes):
        self._nodes = nodes

    def nodes(self, data=False):
        return self._nodes


def test_report_grounding_block_lists_papers_and_underexplored_concepts():
    from research_companion.deep_research import _report_grounding_block

    library_papers = [
        {"title": "GraphRAG for code retrieval", "year": 2023},
        {"title": "Untitled paper", "year": None},
    ]
    graph = _FakeGraph([
        ("c1", {"kind": "concept", "label": "sparse retrieval", "paper_count": 1}),
        ("c2", {"kind": "concept", "label": "dense retrieval", "paper_count": 20}),
    ])

    block = _report_grounding_block(library_papers, graph)
    assert "- Paper: GraphRAG for code retrieval (2023)." in block
    assert "- Paper: Untitled paper (n.d.)." in block
    assert "Underexplored concept: sparse retrieval" in block
    assert "dense retrieval" not in block  # not in the bottom third by paper_count


def test_report_grounding_block_empty_when_no_papers_and_no_graph():
    from research_companion.deep_research import _report_grounding_block
    assert _report_grounding_block([], None) == ""


def test_report_grounding_block_skips_empty_titles_and_non_dicts():
    from research_companion.deep_research import _report_grounding_block
    block = _report_grounding_block([{"title": ""}, "not a dict", {"title": "Real"}], None)
    assert block == "- Paper: Real (n.d.)."
