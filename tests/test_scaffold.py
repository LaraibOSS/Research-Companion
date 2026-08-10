"""Tests for research_companion.scaffold and its SCAFFOLD_OUTLINE_PROMPT
triad (Brainstorm slice 2d: "Draft this direction").

Pipeline under test: generate_outline (one SCAFFOLD_OUTLINE_PROMPT LLM
call, never raises; a degenerate/empty outline is treated as failure) ->
scaffold_sections_payload (pure text+sections tiling, mirrors sections.py's
id/level/tiling conventions) -> create_draft_from_direction (mutating,
called ONLY after a successful outline: deterministic paper_id, writes
metadata+text+sections directly, bypassing the PDF pipeline).
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# SCAFFOLD_OUTLINE_PROMPT triad (Task 1)
# ---------------------------------------------------------------------------

def test_scaffold_outline_prompt_sha256_is_stable_and_64_hex_chars():
    from research_companion.prompts import scaffold_outline_prompt_sha256
    sha = scaffold_outline_prompt_sha256()
    assert sha == scaffold_outline_prompt_sha256()
    assert len(sha) == 64
    int(sha, 16)  # raises ValueError if not hex


def test_format_scaffold_outline_prompt_substitutes_all_placeholders():
    from research_companion.prompts import format_scaffold_outline_prompt
    rendered = format_scaffold_outline_prompt(
        title="Graph retrieval for code search",
        rationale="Apply graph-based retrieval to code.",
        direction_type="extend_method",
        grounding_block="- GraphRAG for code retrieval (2023).",
    )
    assert "Graph retrieval for code search" in rendered
    assert "Apply graph-based retrieval to code." in rendered
    assert "extend_method" in rendered
    assert "GraphRAG for code retrieval (2023)." in rendered
    assert "<<TITLE>>" not in rendered
    assert "<<RATIONALE>>" not in rendered
    assert "<<DIRECTION_TYPE>>" not in rendered
    assert "<<GROUNDING_BLOCK>>" not in rendered
