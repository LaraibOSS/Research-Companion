"""Tests for Task 3: section-aware extraction prompt + new prompt templates.

TDD: these tests were written before implementation. Run to confirm they fail,
then implement, then confirm green.
"""
from __future__ import annotations

from research_companion import prompts

# ===========================================================================
# render_extraction_prompt — section_outline parameter
# ===========================================================================

def test_render_with_outline_contains_section_lines():
    """When section_outline is provided, the rendered prompt includes the outline lines."""
    outline = "s1 Introduction\ns2 Methods\ns2.1 Datasets"
    rendered = prompts.render_extraction_prompt(
        title="Test Paper",
        authors="Alice",
        paper_text="body",
        section_outline=outline,
    )
    assert "s1 Introduction" in rendered
    assert "s2 Methods" in rendered
    assert "s2.1 Datasets" in rendered


def test_render_with_outline_contains_section_field_instruction():
    """When outline is provided, rendered prompt instructs LLM to emit a 'section' field."""
    outline = "s1 Introduction\ns2 Methods"
    rendered = prompts.render_extraction_prompt(
        title="Test Paper",
        authors="Alice",
        paper_text="body",
        section_outline=outline,
    )
    # The prompt must contain the specific instruction phrase to add "section" field to entities
    assert 'include a "section" field' in rendered


def test_render_without_outline_no_section_field_instruction():
    """When outline is empty (default), rendered prompt has NO section-field instruction."""
    rendered = prompts.render_extraction_prompt(
        title="Test Paper",
        authors="Alice",
        paper_text="body",
    )
    # Must not contain section_outline placeholder or section-field instruction
    assert "section_outline" not in rendered
    # Must not instruct LLM to add a "section" field to entities
    # (the word "section" may appear as "If a section is absent" in rules — that's OK,
    #  but the phrase instructing to add a "section" field to each entity must not appear)
    assert 'include a "section" field' not in rendered
    assert "set to the id of the section" not in rendered


def test_render_without_outline_matches_original_behavior():
    """render_extraction_prompt() without outline is backward-compatible (no new text injected)."""
    rendered_new = prompts.render_extraction_prompt(
        title="T",
        authors="A",
        paper_text="P",
    )
    # The new render must still contain the required keys from the original prompt schema
    assert "concepts" in rendered_new
    assert "methods" in rendered_new
    assert "datasets" in rendered_new
    assert "claims" in rendered_new
    assert "results" in rendered_new
    assert "related_work" in rendered_new
    # Title / author / text substituted
    assert "T" in rendered_new
    assert "A" in rendered_new
    assert "P" in rendered_new


# ===========================================================================
# extraction_prompt_sha256 — stable 64-char hex
# ===========================================================================

def test_extraction_prompt_sha256_is_64_hex():
    sha = prompts.extraction_prompt_sha256()
    assert len(sha) == 64
    assert all(c in "0123456789abcdef" for c in sha)


def test_extraction_prompt_sha256_stable():
    """sha256 is deterministic across multiple calls."""
    assert prompts.extraction_prompt_sha256() == prompts.extraction_prompt_sha256()


# ===========================================================================
# ALIGNMENT_PROMPT + format_alignment_prompt + alignment_prompt_sha256
# ===========================================================================

def test_format_alignment_prompt_embeds_inputs():
    """format_alignment_prompt embeds draft_sections_block and candidate_block."""
    draft = "s1 Introduction\nOur paper does X..."
    candidate = "Title: Paper B\nAbstract: Paper B does Y..."
    result = prompts.format_alignment_prompt(
        draft_sections_block=draft,
        candidate_block=candidate,
    )
    assert draft in result
    assert candidate in result


def test_alignment_prompt_mentions_relation_values():
    """ALIGNMENT_PROMPT contains all four relation values."""
    p = prompts.ALIGNMENT_PROMPT
    assert "strengthens" in p
    assert "challenges" in p
    assert "different_perspective" in p
    assert "irrelevant" in p


def test_alignment_prompt_mentions_verbatim_quote_rule():
    """ALIGNMENT_PROMPT instructs that quotes must be verbatim from the candidate paper."""
    p = prompts.ALIGNMENT_PROMPT
    assert "verbatim" in p.lower()


def test_alignment_prompt_sha256_is_64_hex():
    sha = prompts.alignment_prompt_sha256()
    assert len(sha) == 64
    assert all(c in "0123456789abcdef" for c in sha)


def test_alignment_prompt_sha256_stable():
    assert prompts.alignment_prompt_sha256() == prompts.alignment_prompt_sha256()


# ===========================================================================
# QA_PROMPT + format_qa_prompt + qa_prompt_sha256
# ===========================================================================

def test_format_qa_prompt_embeds_inputs():
    """format_qa_prompt embeds question and sources_block."""
    question = "What method does Paper A use?"
    sources = "[S1] Paper A abstract text here.\n[S2] Paper B claims this."
    result = prompts.format_qa_prompt(question=question, sources_block=sources)
    assert question in result
    assert sources in result


def test_qa_prompt_mentions_inline_citation():
    """QA_PROMPT instructs LLM to cite [S#] inline after every claim."""
    p = prompts.QA_PROMPT
    assert "[S#]" in p or "[S1]" in p or "S#" in p


def test_qa_prompt_sha256_is_64_hex():
    sha = prompts.qa_prompt_sha256()
    assert len(sha) == 64
    assert all(c in "0123456789abcdef" for c in sha)


def test_qa_prompt_sha256_stable():
    assert prompts.qa_prompt_sha256() == prompts.qa_prompt_sha256()


# ===========================================================================
# COMPARE_PROMPT + format_compare_prompt + compare_prompt_sha256
# ===========================================================================

def test_format_compare_prompt_embeds_inputs():
    """format_compare_prompt embeds paper_a_block, paper_b_block, shared_block."""
    a = "Paper A: Title A, abstract A, claims A"
    b = "Paper B: Title B, abstract B, claims B"
    shared = "Both papers use dataset X"
    result = prompts.format_compare_prompt(
        paper_a_block=a,
        paper_b_block=b,
        shared_block=shared,
    )
    assert a in result
    assert b in result
    assert shared in result


def test_compare_prompt_mentions_grounding():
    """COMPARE_PROMPT instructs grounding only in provided blocks."""
    p = prompts.COMPARE_PROMPT
    # Must mention grounding / restricting to provided context
    assert "grounded" in p.lower() or "only" in p.lower() or "provided" in p.lower()


def test_compare_prompt_sha256_is_64_hex():
    sha = prompts.compare_prompt_sha256()
    assert len(sha) == 64
    assert all(c in "0123456789abcdef" for c in sha)


def test_compare_prompt_sha256_stable():
    assert prompts.compare_prompt_sha256() == prompts.compare_prompt_sha256()
