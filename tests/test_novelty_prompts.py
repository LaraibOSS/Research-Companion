"""Tests for the novelty-assessment prompts."""
from __future__ import annotations

from papergraph import prompts


def test_format_contribution_prompt_substitutes():
    p = prompts.format_contribution_prompt("My Title", "BODY TEXT")
    assert "My Title" in p and "BODY TEXT" in p
    assert "{title}" not in p and "{paper_text}" not in p


def test_format_comparison_prompt_substitutes():
    p = prompts.format_comparison_prompt("claim text", "1. Prior A\n2. Prior B")
    assert "claim text" in p and "Prior A" in p
    assert "{claim}" not in p and "{prior_art}" not in p


def test_contribution_prompt_demands_json_schema():
    assert '"claims"' in prompts.CONTRIBUTION_PROMPT
    assert "evidence_quote" in prompts.CONTRIBUTION_PROMPT


def test_novelty_prompt_sha_is_stable_hex():
    sha = prompts.novelty_prompt_sha256()
    assert sha == prompts.novelty_prompt_sha256()
    assert len(sha) == 64 and all(c in "0123456789abcdef" for c in sha)
