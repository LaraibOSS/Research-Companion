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


# ---------------------------------------------------------------------------
# _grounding_block
# ---------------------------------------------------------------------------

def test_grounding_block_lists_paper_citations_only():
    from research_companion.scaffold import _grounding_block
    citations = [
        {"kind": "paper", "title": "GraphRAG for code retrieval", "year": 2023},
        {"kind": "concept", "name": "underexplored concept"},
        {"kind": "gap", "theme_id": "g1", "title": "Some gap"},
        {"kind": "paper", "title": "Another Paper", "year": None},
    ]
    block = _grounding_block(citations)
    assert block == "- GraphRAG for code retrieval (2023).\n- Another Paper (n.d.)."


def test_grounding_block_empty_or_missing_title_safe():
    from research_companion.scaffold import _grounding_block
    assert _grounding_block([]) == ""
    assert _grounding_block(None) == ""
    assert _grounding_block([{"kind": "paper", "title": ""}]) == ""
    assert _grounding_block([{"kind": "paper"}, "not a dict"]) == ""


# ---------------------------------------------------------------------------
# _normalize_outline_sections
# ---------------------------------------------------------------------------

def test_normalize_outline_sections_caps_at_12():
    from research_companion.scaffold import _normalize_outline_sections
    raw = [{"title": f"Section {i}", "level": 1, "description": "d"} for i in range(20)]
    out = _normalize_outline_sections(raw)
    assert len(out) == 12


def test_normalize_outline_sections_drops_empty_titles():
    from research_companion.scaffold import _normalize_outline_sections
    raw = [
        {"title": "Kept", "level": 1, "description": "d"},
        {"title": "", "level": 1, "description": "dropped"},
        {"title": "   ", "level": 1, "description": "dropped"},
    ]
    out = _normalize_outline_sections(raw)
    assert [s["title"] for s in out] == ["Kept"]


def test_normalize_outline_sections_clamps_level_to_1_or_2():
    from research_companion.scaffold import _normalize_outline_sections
    raw = [
        {"title": "A", "level": 1, "description": "d"},
        {"title": "B", "level": 3, "description": "d"},
        {"title": "C", "level": "bogus", "description": "d"},
    ]
    out = _normalize_outline_sections(raw)
    assert [s["level"] for s in out] == [1, 1, 1]


def test_normalize_outline_sections_level_2_without_preceding_level_1_becomes_level_1():
    from research_companion.scaffold import _normalize_outline_sections
    raw = [{"title": "Orphan subsection", "level": 2, "description": "d"}]
    out = _normalize_outline_sections(raw)
    assert out == [{"title": "Orphan subsection", "level": 1, "description": "d"}]


def test_normalize_outline_sections_level_2_after_level_1_stays_level_2():
    from research_companion.scaffold import _normalize_outline_sections
    raw = [
        {"title": "Method", "level": 1, "description": "d1"},
        {"title": "Setup", "level": 2, "description": "d2"},
    ]
    out = _normalize_outline_sections(raw)
    assert [s["level"] for s in out] == [1, 2]


def test_normalize_outline_sections_ignores_non_dict_items():
    from research_companion.scaffold import _normalize_outline_sections
    out = _normalize_outline_sections(["not a dict", None, {"title": "Kept", "level": 1}])
    assert [s["title"] for s in out] == ["Kept"]


def test_normalize_outline_sections_empty_input_returns_empty():
    from research_companion.scaffold import _normalize_outline_sections
    assert _normalize_outline_sections([]) == []
    assert _normalize_outline_sections(None) == []
