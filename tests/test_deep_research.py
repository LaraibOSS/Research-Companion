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


# ---------------------------------------------------------------------------
# build_report
# ---------------------------------------------------------------------------

def test_build_report_assembles_sections_with_citations():
    from research_companion.deep_research import build_report
    from research_companion.qa import QAAnswer, QASource

    def fake_answer_fn(question):
        return QAAnswer(
            answer=f"Answer to: {question} [S1]",
            sources=[QASource(paper_id="p1", paper_title="Paper One", section_id="s1",
                               section_title="Intro", score=2.5, char_start=0, char_end=100, chunk_index=0)],
            cited=[QASource(paper_id="p1", paper_title="Paper One", section_id="s1",
                             section_title="Intro", score=2.5, char_start=0, char_end=100, chunk_index=0)],
            unverified_quotes=["an unverified span here that is long enough"],
            input_chars=500,
        )

    report = build_report(
        "graph retrieval", ["What methods are used?"],
        answer_fn=fake_answer_fn, generated_shas={"topic_sha256": "abc"},
    )
    assert report["topic"] == "graph retrieval"
    assert report["question_count"] == 1
    assert report["generated_from"] == {"topic_sha256": "abc"}
    section = report["sections"][0]
    assert section["question"] == "What methods are used?"
    assert section["answer"] == "Answer to: What methods are used? [S1]"
    assert section["citations"] == [{
        "paper_id": "p1", "paper_title": "Paper One", "section_id": "s1",
        "char_start": 0, "char_end": 100, "chunk_index": 0, "score": 2.5,
    }]
    assert section["unverified_quotes"] == ["an unverified span here that is long enough"]
    assert "error" not in section


def test_build_report_one_failing_question_does_not_abort_others():
    from research_companion.deep_research import build_report
    from research_companion.qa import QAAnswer, QASource

    def flaky_answer_fn(question):
        if question == "Bad question?":
            raise RuntimeError("retrieval exploded")
        return QAAnswer(
            answer="Fine [S1]",
            sources=[QASource(paper_id="p1", paper_title="Paper One", section_id="s1",
                               section_title="Intro", score=1.0)],
            cited=[QASource(paper_id="p1", paper_title="Paper One", section_id="s1",
                             section_title="Intro", score=1.0)],
            unverified_quotes=[], input_chars=10,
        )

    report = build_report(
        "topic", ["Bad question?", "Good question?"],
        answer_fn=flaky_answer_fn, generated_shas={},
    )
    assert report["question_count"] == 2
    bad, good = report["sections"]
    assert bad["question"] == "Bad question?"
    assert bad["answer"] == ""
    assert bad["citations"] == []
    assert bad["error"] == "retrieval exploded"
    assert good["question"] == "Good question?"
    assert good["answer"] == "Fine [S1]"
    assert "error" not in good


def test_build_report_answer_fn_returning_none_is_an_error_not_a_raise():
    from research_companion.deep_research import build_report

    def none_answer_fn(question):
        return None

    report = build_report("topic", ["Q?"], answer_fn=none_answer_fn, generated_shas={})
    assert report["sections"][0]["error"]
    assert report["sections"][0]["answer"] == ""


def test_build_report_empty_questions_list_returns_empty_sections():
    from research_companion.deep_research import build_report

    def unused_answer_fn(question):
        raise AssertionError("must not be called")

    report = build_report("topic", [], answer_fn=unused_answer_fn, generated_shas={})
    assert report["sections"] == []
    assert report["question_count"] == 0


def test_build_report_skips_non_string_and_empty_questions():
    from research_companion.deep_research import build_report
    from research_companion.qa import QAAnswer

    def fake_answer_fn(question):
        return QAAnswer(answer="ok", sources=[], cited=[], unverified_quotes=[], input_chars=1)

    report = build_report(
        "topic", ["Real question?", "", None, 42],
        answer_fn=fake_answer_fn, generated_shas={},
    )
    assert report["question_count"] == 1
    assert report["sections"][0]["question"] == "Real question?"


def test_build_report_never_raises_when_answer_fn_raises_for_every_question():
    from research_companion.deep_research import build_report

    def always_raises(question):
        raise RuntimeError("down")

    report = build_report("topic", ["Q1?", "Q2?"], answer_fn=always_raises, generated_shas={})
    assert report["question_count"] == 2
    assert all(s["error"] == "down" for s in report["sections"])


# ---------------------------------------------------------------------------
# _normalize_plan_questions (Editable Research Plan, 2e-4)
# ---------------------------------------------------------------------------

def test_normalize_plan_questions_trims_and_drops_empty_and_non_string():
    from research_companion.deep_research import _normalize_plan_questions

    out = _normalize_plan_questions(
        ["  What methods are used?  ", "", "   ", None, 42, "What datasets are used?"],
        max_questions=12,
    )
    assert out == ["What methods are used?", "What datasets are used?"]


def test_normalize_plan_questions_dedupes_case_insensitively():
    from research_companion.deep_research import _normalize_plan_questions

    out = _normalize_plan_questions(["What is X?", "what is x?", "What is Y?"], max_questions=12)
    assert out == ["What is X?", "What is Y?"]


def test_normalize_plan_questions_caps_at_max_questions_default_twelve():
    from research_companion.deep_research import _normalize_plan_questions

    out = _normalize_plan_questions([f"Question {i}?" for i in range(20)], max_questions=12)
    assert len(out) == 12
    assert out[0] == "Question 0?"


def test_normalize_plan_questions_default_max_is_twelve():
    from research_companion.deep_research import _normalize_plan_questions

    out = _normalize_plan_questions([f"Q{i}?" for i in range(20)])
    assert len(out) == 12


def test_normalize_plan_questions_empty_list_returns_empty_list():
    from research_companion.deep_research import _normalize_plan_questions
    assert _normalize_plan_questions([]) == []
    assert _normalize_plan_questions(None) == []


def test_normalize_plan_questions_never_raises_on_garbage_input():
    from research_companion.deep_research import _normalize_plan_questions
    assert _normalize_plan_questions("not a list") == []
    assert _normalize_plan_questions([1, 2, {"a": 1}, ["nested"]]) == []
