"""Tests for research_companion.rcs — Report Evidence Scoring (RCS),
slice 2e-2 -- and its RCS_PROMPT triad.

Pipeline under test: _chunk_text (slice a citation's REAL cited text out of
store.load_text[char_start:char_end], defensive -> "" never raises) ->
_chunks_block (numbered, truncated, skips unscorable/empty-text citations)
-> score_section (one RCS_PROMPT LLM call per section, batched like
gaps.synthesize_gaps; never raises) -> _normalize_scores (drop invented
refs, clamp relevance, normalize stance) -> score_report (pure
orchestration over a saved report's sections; never raises).

HONESTY: a citation whose chunk can't be loaded is left unscored -- never
a guessed score. The LLM may only score listed refs; an invented ref is
dropped. RCS is a MODEL JUDGMENT, never "verified".
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# RCS_PROMPT triad (Task 1)
# ---------------------------------------------------------------------------

def test_rcs_prompt_sha256_is_stable_and_64_hex_chars():
    from research_companion.prompts import rcs_prompt_sha256
    sha = rcs_prompt_sha256()
    assert sha == rcs_prompt_sha256()
    assert len(sha) == 64
    int(sha, 16)  # raises ValueError if not hex


def test_format_rcs_prompt_substitutes_all_placeholders():
    from research_companion.prompts import format_rcs_prompt
    rendered = format_rcs_prompt(
        question="What retrieval methods does the library use?",
        answer="BM25 and dense retrieval are used [S1].",
        chunks_block="[0] Paper One -- some chunk text.",
    )
    assert "What retrieval methods does the library use?" in rendered
    assert "BM25 and dense retrieval are used [S1]." in rendered
    assert "[0] Paper One -- some chunk text." in rendered
    assert "<<QUESTION>>" not in rendered
    assert "<<ANSWER>>" not in rendered
    assert "<<CHUNKS_BLOCK>>" not in rendered
