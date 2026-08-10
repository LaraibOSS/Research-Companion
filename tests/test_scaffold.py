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

import json

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


# ---------------------------------------------------------------------------
# generate_outline
# ---------------------------------------------------------------------------

def test_generate_outline_happy_path_with_stub_llm():
    from research_companion.scaffold import generate_outline

    def fake_llm(prompt: str) -> str:
        assert "Graph retrieval for code search" in prompt
        assert "Apply graph-based retrieval to code." in prompt
        assert "extend_method" in prompt
        assert "GraphRAG for code retrieval (2023)." in prompt
        return json.dumps({"sections": [
            {"title": "Introduction", "level": 1, "description": "Intro desc."},
            {"title": "Method", "level": 1, "description": "Method desc."},
        ]})

    direction = {
        "title": "Graph retrieval for code search",
        "rationale": "Apply graph-based retrieval to code.",
        "direction_type": "extend_method",
        "citations": [{"kind": "paper", "title": "GraphRAG for code retrieval", "year": 2023}],
    }
    out = generate_outline(direction, llm=fake_llm)
    assert out["llm_error"] is None
    assert len(out["sections"]) == 2
    assert out["sections"][0] == {"title": "Introduction", "level": 1, "description": "Intro desc."}


def test_generate_outline_malformed_json_sets_llm_error_no_raise():
    from research_companion.scaffold import generate_outline

    def bad_llm(prompt: str) -> str:
        return "not json at all"

    out = generate_outline({"title": "Topic", "rationale": "r"}, llm=bad_llm)
    assert out["sections"] == []
    assert out["llm_error"]


def test_generate_outline_missing_sections_key_sets_llm_error_no_raise():
    from research_companion.scaffold import generate_outline

    def bad_llm(prompt: str) -> str:
        return json.dumps({"not_sections": []})

    out = generate_outline({"title": "Topic", "rationale": "r"}, llm=bad_llm)
    assert out["sections"] == []
    assert out["llm_error"]


def test_generate_outline_empty_sections_list_is_treated_as_failure():
    from research_companion.scaffold import generate_outline

    def empty_llm(prompt: str) -> str:
        return json.dumps({"sections": []})

    out = generate_outline({"title": "Topic", "rationale": "r"}, llm=empty_llm)
    assert out["sections"] == []
    assert out["llm_error"]  # a degenerate/empty outline is a failure


def test_generate_outline_llm_raises_sets_llm_error_no_raise():
    from research_companion.scaffold import generate_outline

    def raising_llm(prompt: str) -> str:
        raise RuntimeError("provider down")

    out = generate_outline({"title": "Topic", "rationale": "r"}, llm=raising_llm)
    assert out["sections"] == []
    assert out["llm_error"] == "provider down"


def test_generate_outline_llm_none_sets_llm_error_no_raise():
    from research_companion.scaffold import generate_outline
    out = generate_outline({"title": "Topic", "rationale": "r"}, llm=None)
    assert out["sections"] == []
    assert out["llm_error"]


def test_generate_outline_strips_markdown_code_fences():
    from research_companion.scaffold import generate_outline

    def fenced_llm(prompt: str) -> str:
        return "```json\n" + json.dumps({"sections": [
            {"title": "Introduction", "level": 1, "description": "d"},
        ]}) + "\n```"

    out = generate_outline({"title": "Topic", "rationale": "r"}, llm=fenced_llm)
    assert out["llm_error"] is None
    assert len(out["sections"]) == 1


def test_generate_outline_normalizes_caps_and_clamps():
    from research_companion.scaffold import generate_outline

    def many_llm(prompt: str) -> str:
        return json.dumps({"sections": [
            {"title": f"Section {i}", "level": 1, "description": "d"} for i in range(20)
        ]})

    out = generate_outline({"title": "Topic", "rationale": "r"}, llm=many_llm)
    assert out["llm_error"] is None
    assert len(out["sections"]) == 12


# ---------------------------------------------------------------------------
# scaffold_sections_payload
# ---------------------------------------------------------------------------

def _sample_outline() -> dict:
    return {"sections": [
        {"title": "Introduction", "level": 1, "description": "Intro desc."},
        {"title": "Method", "level": 1, "description": "Method desc."},
        {"title": "Setup", "level": 2, "description": "Setup desc."},
    ]}


def test_scaffold_sections_payload_tiles_text_exactly():
    from research_companion.scaffold import scaffold_sections_payload
    text, payload = scaffold_sections_payload(_sample_outline(), title="My Direction")

    assert text == (
        "# Introduction\n\nIntro desc.\n\n"
        "# Method\n\nMethod desc.\n\n"
        "## Setup\n\nSetup desc.\n\n"
    )
    sections = payload["sections"]
    assert sections[0] == {
        "section_id": "s1", "title": "Introduction", "level": 1, "parent": None,
        "char_start": 0, "char_end": 29,
    }
    assert sections[1] == {
        "section_id": "s2", "title": "Method", "level": 1, "parent": None,
        "char_start": 29, "char_end": 53,
    }
    assert sections[2] == {
        "section_id": "s2.1", "title": "Setup", "level": 2, "parent": "s2",
        "char_start": 53, "char_end": 76,
    }
    # tiling: no gaps/overlaps, exact cover of the whole text
    assert sections[0]["char_start"] == 0
    assert sections[-1]["char_end"] == len(text)
    for i in range(len(sections) - 1):
        assert sections[i]["char_end"] == sections[i + 1]["char_start"]


def test_scaffold_sections_payload_shape_and_hash():
    import hashlib

    from research_companion.scaffold import scaffold_sections_payload
    text, payload = scaffold_sections_payload(_sample_outline(), title="My Direction")
    assert payload["version"] == 1
    assert payload["method"] == "scaffold"
    assert payload["text_sha256"] == hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_scaffold_sections_payload_second_level1_after_a_level2_gets_new_parent():
    from research_companion.scaffold import scaffold_sections_payload
    outline = {"sections": [
        {"title": "A", "level": 1, "description": "a"},
        {"title": "A.1", "level": 2, "description": "a1"},
        {"title": "B", "level": 1, "description": "b"},
        {"title": "B.1", "level": 2, "description": "b1"},
    ]}
    _text, payload = scaffold_sections_payload(outline, title="T")
    ids = [(s["section_id"], s["parent"]) for s in payload["sections"]]
    assert ids == [("s1", None), ("s1.1", "s1"), ("s2", None), ("s2.1", "s2")]


def test_scaffold_sections_payload_empty_outline_returns_empty_text_and_sections():
    from research_companion.scaffold import scaffold_sections_payload
    text, payload = scaffold_sections_payload({"sections": []}, title="T")
    assert text == ""
    assert payload["sections"] == []


def test_scaffold_sections_payload_missing_title_defaults_to_untitled():
    from research_companion.scaffold import scaffold_sections_payload
    outline = {"sections": [{"title": "", "level": 1, "description": "d"}]}
    text, payload = scaffold_sections_payload(outline, title="T")
    assert payload["sections"][0]["title"] == "Untitled"
    assert "Untitled" in text


# ---------------------------------------------------------------------------
# create_draft_from_direction
# ---------------------------------------------------------------------------

def test_create_draft_from_direction_writes_metadata_text_and_sections(isolated_papergraph_dir):
    from research_companion import store
    from research_companion.scaffold import create_draft_from_direction

    direction = {
        "title": "Graph retrieval for code search",
        "rationale": "Apply graph-based retrieval to code.",
        "direction_type": "extend_method",
        "citations": [],
    }
    outline = _sample_outline()

    paper_id = create_draft_from_direction(direction, outline)

    assert paper_id.startswith("scaffold:")
    meta = store.PaperMetadata.load(paper_id)
    assert meta is not None
    assert meta.title == "Graph retrieval for code search"
    assert meta.authors == []
    assert meta.year is None
    assert meta.abstract == "Apply graph-based retrieval to code."
    assert meta.parse_source == "scaffold"
    assert meta.full_text_available is True

    text = store.load_text(paper_id)
    assert text == (
        "# Introduction\n\nIntro desc.\n\n"
        "# Method\n\nMethod desc.\n\n"
        "## Setup\n\nSetup desc.\n\n"
    )
    sections = store.load_sections(paper_id)
    assert sections is not None
    assert sections["method"] == "scaffold"
    assert len(sections["sections"]) == 3


def test_create_draft_from_direction_deterministic_paper_id(isolated_papergraph_dir):
    from research_companion.scaffold import create_draft_from_direction

    direction = {"title": "Same direction", "rationale": "Same rationale.", "citations": []}
    outline = _sample_outline()

    pid1 = create_draft_from_direction(direction, outline)
    pid2 = create_draft_from_direction(direction, outline)
    assert pid1 == pid2


def test_create_draft_from_direction_rescaffold_overwrites_same_paper(isolated_papergraph_dir):
    from research_companion import store
    from research_companion.scaffold import create_draft_from_direction

    direction = {"title": "Same direction", "rationale": "Same rationale.", "citations": []}

    pid1 = create_draft_from_direction(direction, _sample_outline())
    other_outline = {"sections": [{"title": "Only Section", "level": 1, "description": "d"}]}
    pid2 = create_draft_from_direction(direction, other_outline)

    assert pid1 == pid2  # same paper_id -- overwrite, not a new paper
    sections = store.load_sections(pid1)
    assert len(sections["sections"]) == 1  # the second scaffold's content won


def test_create_draft_from_direction_different_direction_different_paper_id(isolated_papergraph_dir):
    from research_companion.scaffold import create_draft_from_direction

    pid1 = create_draft_from_direction(
        {"title": "Direction A", "rationale": "Rationale A.", "citations": []}, _sample_outline())
    pid2 = create_draft_from_direction(
        {"title": "Direction B", "rationale": "Rationale B.", "citations": []}, _sample_outline())
    assert pid1 != pid2
