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
