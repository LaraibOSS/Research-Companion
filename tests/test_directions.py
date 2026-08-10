"""Tests for research_companion.directions and its DIRECTIONS_PROMPT triad.

Pipeline under test (mirrors research_companion/gaps.py's synthesize_gaps
shape): _collect_grounding (pure) -> one DIRECTIONS_PROMPT call ->
_assemble_directions (pure, drops invented citation keys) -> rank_directions
(pure, deterministic score, stable sort) -> synthesize_directions
(orchestrator).
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# DIRECTIONS_PROMPT triad (feat/brainstorm-directions, Task 1)
# ---------------------------------------------------------------------------

def test_directions_prompt_sha256_is_stable_and_64_hex_chars():
    from research_companion.prompts import directions_prompt_sha256
    sha = directions_prompt_sha256()
    assert sha == directions_prompt_sha256()
    assert len(sha) == 64
    int(sha, 16)  # raises ValueError if not hex


def test_format_directions_prompt_substitutes_topic_and_grounding_block():
    from research_companion.prompts import format_directions_prompt
    rendered = format_directions_prompt(
        topic="graph neural networks for code",
        grounding_block="- [p:arxiv:2401.00001] Some Paper (2024).",
    )
    assert "graph neural networks for code" in rendered
    assert "[p:arxiv:2401.00001] Some Paper (2024)." in rendered
    assert "<<TOPIC>>" not in rendered
    assert "<<GROUNDING_BLOCK>>" not in rendered
