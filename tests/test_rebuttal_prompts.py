"""Tests for rebuttal classify/draft prompts."""
from __future__ import annotations

from research_companion import prompts


def test_classify_prompt_formats_and_lists_kinds():
    p = prompts.format_classify_prompt("Missing baseline")
    assert "Missing baseline" in p and "{concern}" not in p
    for kind in ("factual_error", "misunderstanding", "valid_weakness", "clarification"):
        assert kind in p


def test_rebuttal_prompt_formats_all_placeholders():
    p = prompts.format_rebuttal_prompt("c", "valid_weakness", "para 1: text", "firm")
    assert "{concern}" not in p and "{passages}" not in p and "{tone}" not in p and "{kind}" not in p
    assert "firm" in p and "para 1: text" in p


def test_rebuttal_sha_stable():
    assert prompts.rebuttal_prompt_sha256() == prompts.rebuttal_prompt_sha256()
