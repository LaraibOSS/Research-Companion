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

import json

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


# ---------------------------------------------------------------------------
# generate_questions
# ---------------------------------------------------------------------------

def test_generate_questions_happy_path_with_stub_llm():
    from research_companion.deep_research import generate_questions

    def fake_llm(prompt: str) -> str:
        assert "graph retrieval for code" in prompt
        assert "GraphRAG for code retrieval (2023)." in prompt
        assert "6" in prompt
        return json.dumps({"questions": [
            "What retrieval methods does the library use?",
            "What datasets are evaluated?",
        ]})

    out = generate_questions(
        "graph retrieval for code",
        library_papers=[{"title": "GraphRAG for code retrieval", "year": 2023}],
        graph=None, llm=fake_llm, max_questions=6,
    )
    assert out["llm_error"] is None
    assert out["questions"] == [
        "What retrieval methods does the library use?",
        "What datasets are evaluated?",
    ]


def test_generate_questions_dedupes_case_insensitively():
    from research_companion.deep_research import generate_questions

    def fake_llm(prompt: str) -> str:
        return json.dumps({"questions": ["What is X?", "what is x?", "What is Y?"]})

    out = generate_questions("topic", llm=fake_llm)
    assert out["questions"] == ["What is X?", "What is Y?"]


def test_generate_questions_drops_empty_and_non_string_items():
    from research_companion.deep_research import generate_questions

    def fake_llm(prompt: str) -> str:
        return json.dumps({"questions": ["Real question?", "", "   ", 42, None]})

    out = generate_questions("topic", llm=fake_llm)
    assert out["questions"] == ["Real question?"]


def test_generate_questions_caps_at_max_questions():
    from research_companion.deep_research import generate_questions

    def fake_llm(prompt: str) -> str:
        return json.dumps({"questions": [f"Question {i}?" for i in range(20)]})

    out = generate_questions("topic", llm=fake_llm, max_questions=4)
    assert len(out["questions"]) == 4


def test_generate_questions_malformed_json_sets_llm_error_no_raise():
    from research_companion.deep_research import generate_questions

    def bad_llm(prompt: str) -> str:
        return "not json at all"

    out = generate_questions("topic", llm=bad_llm)
    assert out["questions"] == []
    assert out["llm_error"]


def test_generate_questions_missing_questions_key_sets_llm_error_no_raise():
    from research_companion.deep_research import generate_questions

    def bad_llm(prompt: str) -> str:
        return json.dumps({"not_questions": []})

    out = generate_questions("topic", llm=bad_llm)
    assert out["questions"] == []
    assert out["llm_error"]


def test_generate_questions_empty_questions_list_is_treated_as_failure():
    from research_companion.deep_research import generate_questions

    def empty_llm(prompt: str) -> str:
        return json.dumps({"questions": []})

    out = generate_questions("topic", llm=empty_llm)
    assert out["questions"] == []
    assert out["llm_error"]  # a degenerate/empty question list is a failure


def test_generate_questions_llm_raises_sets_llm_error_no_raise():
    from research_companion.deep_research import generate_questions

    def raising_llm(prompt: str) -> str:
        raise RuntimeError("provider down")

    out = generate_questions("topic", llm=raising_llm)
    assert out["questions"] == []
    assert out["llm_error"] == "provider down"


def test_generate_questions_llm_none_sets_llm_error_no_raise():
    from research_companion.deep_research import generate_questions
    out = generate_questions("topic", llm=None)
    assert out["questions"] == []
    assert out["llm_error"]


def test_generate_questions_strips_markdown_code_fences():
    from research_companion.deep_research import generate_questions

    def fenced_llm(prompt: str) -> str:
        return "```json\n" + json.dumps({"questions": ["Q1?"]}) + "\n```"

    out = generate_questions("topic", llm=fenced_llm)
    assert out["llm_error"] is None
    assert out["questions"] == ["Q1?"]


def test_generate_questions_empty_topic_and_empty_grounding_skips_llm_call():
    from research_companion.deep_research import generate_questions

    def exploding_llm(prompt: str) -> str:
        raise AssertionError("must not be called")

    out = generate_questions("", library_papers=[], graph=None, llm=exploding_llm)
    assert out == {"questions": [], "llm_error": None}


def test_generate_questions_topic_alone_still_calls_llm():
    from research_companion.deep_research import generate_questions

    def fake_llm(prompt: str) -> str:
        return json.dumps({"questions": ["Q1?"]})

    out = generate_questions("a real topic", library_papers=[], graph=None, llm=fake_llm)
    assert out["llm_error"] is None
    assert out["questions"] == ["Q1?"]
