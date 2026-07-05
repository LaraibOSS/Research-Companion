"""Tests for research_companion.sections — section-tree extraction module.

All tests use synthetic text and fake LLM callables (no network, no real LLM).
The isolated_papergraph_dir fixture (conftest.py autouse) isolates filesystem state.
"""
from __future__ import annotations

import json

import pytest

from research_companion.sections import (
    Section,
    build_and_save_sections,
    build_section_tree,
    group_extraction_by_section,
    is_boilerplate,
    refine_sections_llm,
    section_text,
)
from research_companion import store


# ===========================================================================
# build_section_tree — numbered headings (levels 1+2, parent linkage, tiling)
# ===========================================================================

def test_numbered_headings_level1():
    """Numbered level-1 headings produce sections with correct ids and levels."""
    text = (
        "1 Introduction\n"
        "This is the introduction section with sufficient body text to pass filter.\n\n"
        "2 Methods\n"
        "These are the methods described in full detail in this section of the paper.\n"
    )
    sections = build_section_tree(text)
    assert len(sections) == 2
    assert sections[0].section_id == "s1"
    assert sections[0].title == "Introduction"
    assert sections[0].level == 1
    assert sections[0].parent is None
    assert sections[1].section_id == "s2"
    assert sections[1].title == "Methods"
    assert sections[1].level == 1
    assert sections[1].parent is None


def test_numbered_headings_level2_parent_linkage():
    """Level-2 numbered headings nest under their preceding level-1 parent."""
    text = (
        "1 Introduction\n"
        "This is the introductory text which is long enough to pass the body check.\n\n"
        "2 Methods\n"
        "This section describes the methodology used in our experiments here.\n\n"
        "2.1 Dataset\n"
        "Dataset details here including the name source and statistics used.\n\n"
        "2.2 Model\n"
        "Model details here describing the architecture and training procedure.\n"
    )
    sections = build_section_tree(text)
    ids = [s.section_id for s in sections]
    levels = [s.level for s in sections]
    parents = [s.parent for s in sections]

    assert "s1" in ids
    assert "s2" in ids
    assert "s2.1" in ids
    assert "s2.2" in ids

    s1 = next(s for s in sections if s.section_id == "s1")
    s2 = next(s for s in sections if s.section_id == "s2")
    s21 = next(s for s in sections if s.section_id == "s2.1")
    s22 = next(s for s in sections if s.section_id == "s2.2")

    assert s1.level == 1
    assert s1.parent is None
    assert s2.level == 1
    assert s2.parent is None
    assert s21.level == 2
    assert s21.parent == "s2"
    assert s22.level == 2
    assert s22.parent == "s2"


def test_numbered_headings_tiling():
    """Sections tile the text: ranges are contiguous, last ends at len(text)."""
    text = (
        "1 Introduction\n"
        "Intro text.\n\n"
        "2 Methods\n"
        "Methods text.\n\n"
        "3 Results\n"
        "Results text.\n"
    )
    sections = build_section_tree(text)
    # Only keep level-1 sections for tiling check
    l1_sections = [s for s in sections if s.level == 1]
    l1_sections.sort(key=lambda s: s.char_start)

    # Each section end must equal the next section start
    for i in range(len(l1_sections) - 1):
        assert l1_sections[i].char_end == l1_sections[i + 1].char_start, (
            f"Gap between {l1_sections[i].section_id} and {l1_sections[i+1].section_id}"
        )

    # Last section must end at len(text)
    assert l1_sections[-1].char_end == len(text)


def test_numbered_headings_l2_tiling():
    """Level-2 sections are also contiguous within their parent range."""
    text = (
        "2 Methods\n"
        "Methods overview text.\n\n"
        "2.1 Dataset\n"
        "Dataset details with enough text to pass the 40-char minimum body check.\n\n"
        "2.2 Model\n"
        "Model details with enough text to pass the 40-char minimum body check.\n"
    )
    sections = build_section_tree(text)
    l2 = [s for s in sections if s.level == 2]
    l2.sort(key=lambda s: s.char_start)

    # L2 sections are contiguous
    for i in range(len(l2) - 1):
        assert l2[i].char_end == l2[i + 1].char_start


# ===========================================================================
# build_section_tree — canonical-name headings (mixed case)
# ===========================================================================

def test_canonical_name_headings_mixed_case():
    """Canonical names (any case) are detected as level-1 sections."""
    text = (
        "Abstract\n"
        "This paper presents something important and novel to the research community.\n\n"
        "INTRODUCTION\n"
        "We introduce our work and provide context for the reader of this paper here.\n\n"
        "Methods\n"
        "We used these methods and describe them in full detail in this section.\n"
    )
    sections = build_section_tree(text)
    titles_lower = [s.title.lower() for s in sections]
    assert "abstract" in titles_lower or "Abstract" in [s.title for s in sections]
    assert any(t.lower() == "introduction" for t in titles_lower)
    assert any(t.lower() == "methods" for t in titles_lower)
    for s in sections:
        assert s.level == 1
        assert s.parent is None


def test_canonical_name_not_detected_if_too_long():
    """A canonical name that is >= 60 chars is NOT treated as a heading."""
    long_name = "Introduction " + "x" * 60
    text = f"{long_name}\nSome content after the very long line.\n"
    sections = build_section_tree(text)
    # Should fall back to Full Text since nothing valid was found
    assert sections[0].section_id == "s1"
    assert sections[0].title == "Full Text"


# ===========================================================================
# build_section_tree — ALL-CAPS headings
# ===========================================================================

def test_allcaps_headings():
    """All-uppercase short lines are detected as level-1 section headings."""
    text = (
        "ABSTRACT\n"
        "This is the abstract content with enough text.\n\n"
        "INTRODUCTION\n"
        "This is the introduction with enough text for the body requirement.\n\n"
        "CONCLUSION\n"
        "This is the conclusion.\n"
    )
    sections = build_section_tree(text)
    titles = [s.title for s in sections]
    assert "ABSTRACT" in titles
    assert "INTRODUCTION" in titles
    assert "CONCLUSION" in titles
    for s in sections:
        assert s.level == 1


def test_allcaps_heading_with_period_rejected():
    """ALL-CAPS line ending with period is NOT a heading."""
    text = (
        "THIS IS A SENTENCE.\n"
        "Some body text after this line.\n"
    )
    sections = build_section_tree(text)
    assert len(sections) == 1
    assert sections[0].title == "Full Text"


def test_allcaps_heading_too_short_rejected():
    """ALL-CAPS line with < 3 chars is NOT a heading."""
    text = "AB\nSome content.\n"
    sections = build_section_tree(text)
    assert sections[0].title == "Full Text"


def test_allcaps_heading_too_long_rejected():
    """ALL-CAPS line >= 60 chars is NOT a heading."""
    long_caps = "A" * 60
    text = f"{long_caps}\nSome content.\n"
    sections = build_section_tree(text)
    assert sections[0].title == "Full Text"


# ===========================================================================
# build_section_tree — garbage text fallback
# ===========================================================================

def test_garbage_text_fallback():
    """Unstructured text with no heading candidates returns single 'Full Text' section."""
    text = (
        "this is just some random text without any headings\n"
        "it has multiple lines but nothing that looks like a section header\n"
        "just prose and more prose flowing along nicely\n"
    )
    sections = build_section_tree(text)
    assert len(sections) == 1
    assert sections[0].section_id == "s1"
    assert sections[0].title == "Full Text"
    assert sections[0].level == 1
    assert sections[0].parent is None
    assert sections[0].char_start == 0
    assert sections[0].char_end == len(text)


def test_empty_text_fallback():
    """Empty string returns single 'Full Text' section."""
    text = ""
    sections = build_section_tree(text)
    assert len(sections) == 1
    assert sections[0].title == "Full Text"
    assert sections[0].char_end == 0


# ===========================================================================
# build_section_tree — sentence false-positive rejection
# ===========================================================================

def test_numbered_list_item_inside_prose_not_split():
    """A numbered line in prose that ends with '.' and >60 chars is not a heading."""
    text = (
        "Introduction\n"
        "Here is the setup.\n\n"
        "1. This is a numbered list item that is much longer than sixty characters in total.\n"
        "2. Another long list item that also exceeds sixty characters and ends with a period.\n"
        "More prose text that continues the list discussion.\n"
    )
    sections = build_section_tree(text)
    # The numbered items should NOT be treated as headings (they end with "." and >60 chars)
    titles = [s.title for s in sections]
    # We expect only "Introduction" as a heading from canonical name
    assert "Introduction" in titles
    # The numbered list items should NOT appear as section titles
    for title in titles:
        assert "list item" not in title.lower()


def test_numbered_heading_without_uppercase_start_rejected():
    """A numbered line whose text part starts lowercase is not a heading."""
    text = (
        "Introduction\n"
        "Intro content.\n\n"
        "1 this starts with lowercase\n"
        "More content.\n"
    )
    sections = build_section_tree(text)
    titles = [s.title for s in sections]
    # "this starts with lowercase" should not be a heading
    assert not any("lowercase" in t.lower() for t in titles)


# ===========================================================================
# is_boilerplate — true/false table
# ===========================================================================

@pytest.mark.parametrize("title,expected", [
    ("References", True),
    ("REFERENCES", True),
    ("Bibliography", True),
    ("BIBLIOGRAPHY", True),
    ("Acknowledgments", True),
    ("Acknowledgements", True),
    ("ACKNOWLEDGMENTS", True),
    ("Appendix", True),
    ("Appendix A", True),
    ("Appendix B: Additional Experiments", True),
    ("appendix a", True),
    ("Method", False),
    ("Methods", False),
    ("Introduction", False),
    ("Results", False),
    ("Ethics Statement", False),
    ("Conclusion", False),
    ("Related Work", False),
])
def test_is_boilerplate(title, expected):
    assert is_boilerplate(title) == expected, f"is_boilerplate({title!r}) should be {expected}"


# ===========================================================================
# section_text — correct slicing
# ===========================================================================

def test_section_text_slices_correctly():
    """section_text returns the correct slice of the original text."""
    text = "AAAbbbCCC"
    s = Section("s1", "AAA", 1, None, 0, 3)
    assert section_text(text, s) == "AAA"

    s2 = Section("s2", "bbb", 1, None, 3, 6)
    assert section_text(text, s2) == "bbb"

    s3 = Section("s3", "CCC", 1, None, 6, 9)
    assert section_text(text, s3) == "CCC"


def test_section_text_full_text():
    """section_text with full range returns entire text."""
    text = "Hello, world!"
    s = Section("s1", "Full Text", 1, None, 0, len(text))
    assert section_text(text, s) == text


# ===========================================================================
# group_extraction_by_section
# ===========================================================================

def test_group_extraction_assigned():
    """Entities with known section ids are grouped under their section."""
    sections = [
        Section("s1", "Introduction", 1, None, 0, 100),
        Section("s2", "Methods", 1, None, 100, 200),
    ]
    extraction = {
        "concepts": [
            {"name": "C1", "section": "s1"},
            {"name": "C2", "section": "s2"},
        ],
        "methods": [
            {"name": "M1", "section": "s1"},
        ],
    }
    result = group_extraction_by_section(extraction, sections)
    assert result["s1"]["concepts"] == [{"name": "C1", "section": "s1"}]
    assert result["s2"]["concepts"] == [{"name": "C2", "section": "s2"}]
    assert result["s1"]["methods"] == [{"name": "M1", "section": "s1"}]
    assert result["s2"]["methods"] == []


def test_group_extraction_unassigned_missing_section_key():
    """Entities with no 'section' key go to _unassigned."""
    sections = [Section("s1", "Intro", 1, None, 0, 100)]
    extraction = {
        "concepts": [
            {"name": "C1"},  # no section key
        ],
    }
    result = group_extraction_by_section(extraction, sections)
    assert result["_unassigned"]["concepts"] == [{"name": "C1"}]


def test_group_extraction_unassigned_none_section():
    """Entities with section=None go to _unassigned."""
    sections = [Section("s1", "Intro", 1, None, 0, 100)]
    extraction = {
        "methods": [
            {"name": "M1", "section": None},
        ],
    }
    result = group_extraction_by_section(extraction, sections)
    assert result["_unassigned"]["methods"] == [{"name": "M1", "section": None}]


def test_group_extraction_unassigned_unknown_id():
    """Entities with an unknown section_id go to _unassigned."""
    sections = [Section("s1", "Intro", 1, None, 0, 100)]
    extraction = {
        "datasets": [
            {"name": "D1", "section": "s99"},  # s99 does not exist
        ],
    }
    result = group_extraction_by_section(extraction, sections)
    assert result["_unassigned"]["datasets"] == [{"name": "D1", "section": "s99"}]


def test_group_extraction_related_work_excluded():
    """related_work entries are NOT grouped and do not appear in the result."""
    sections = [Section("s1", "Intro", 1, None, 0, 100)]
    extraction = {
        "concepts": [{"name": "C1", "section": "s1"}],
        "related_work": ["Lewis et al. 2020", "Brown et al. 2020"],
    }
    result = group_extraction_by_section(extraction, sections)
    assert "related_work" not in result
    assert "related_work" not in result.get("_unassigned", {})
    assert "related_work" not in result.get("s1", {})


def test_group_extraction_mixed():
    """Mixed scenario: assigned, unassigned, and related_work excluded together."""
    sections = [
        Section("s1", "Introduction", 1, None, 0, 50),
        Section("s2", "Methods", 1, None, 50, 100),
    ]
    extraction = {
        "concepts": [
            {"name": "C1", "section": "s1"},
            {"name": "C2"},                    # unassigned (no section key)
            {"name": "C3", "section": None},   # unassigned (None)
            {"name": "C4", "section": "s99"},  # unassigned (unknown id)
        ],
        "methods": [
            {"name": "M1", "section": "s2"},
        ],
        "related_work": ["Paper A"],
    }
    result = group_extraction_by_section(extraction, sections)

    assert result["s1"]["concepts"] == [{"name": "C1", "section": "s1"}]
    assert result["s2"]["concepts"] == []
    unassigned = result["_unassigned"]["concepts"]
    unassigned_names = [e["name"] for e in unassigned]
    assert "C2" in unassigned_names
    assert "C3" in unassigned_names
    assert "C4" in unassigned_names
    assert result["s2"]["methods"] == [{"name": "M1", "section": "s2"}]
    assert "related_work" not in result


# ===========================================================================
# refine_sections_llm
# ===========================================================================

def _make_llm_response(headings: list[str]) -> str:
    return json.dumps({"headings": headings})


def test_refine_sections_llm_2_match_1_hallucinated():
    """LLM proposes 3 headings; 2 match (one verbatim, one normalized), 1 hallucinated -> dropped."""
    text = (
        "Introduction\n"
        "Some intro text that is long enough to be useful here.\n\n"
        "Methodology\n"
        "Detailed  methodology section with some extra spaces.\n\n"
        "Random content that does not correspond to any heading at all.\n"
    )
    # Heading 1: exact match; Heading 2: whitespace-normalized match; Heading 3: hallucinated
    headings_proposed = ["Introduction", "Detailed  methodology section", "Hallucinated Section XYZ"]

    def fake_llm(prompt: str) -> str:
        return _make_llm_response(headings_proposed)

    original = [Section("s1", "Full Text", 1, None, 0, len(text))]
    result = refine_sections_llm(text, original, fake_llm)

    # Should have 2 sections (hallucinated one dropped)
    assert len(result) == 2
    titles = [s.title for s in result]
    assert "Introduction" in titles
    # The hallucinated heading should not appear
    assert not any("Hallucinated" in t for t in titles)

    # All sections are level 1
    for s in result:
        assert s.level == 1
        assert s.parent is None


def test_refine_sections_llm_only_hallucinated_returns_original():
    """If all proposed headings are hallucinated (no match), return original sections."""
    text = "Just some plain text without any obvious headings at all.\n"
    original = [Section("s1", "Full Text", 1, None, 0, len(text))]

    def fake_llm(prompt: str) -> str:
        return _make_llm_response(["Nonexistent Section A", "Nonexistent Section B"])

    result = refine_sections_llm(text, original, fake_llm)
    assert result == original


def test_refine_sections_llm_invalid_json_returns_original():
    """If LLM returns invalid JSON, return original sections unchanged."""
    text = "Some text.\n"
    original = [Section("s1", "Full Text", 1, None, 0, len(text))]

    def fake_llm(prompt: str) -> str:
        return "this is not valid json at all }{broken"

    result = refine_sections_llm(text, original, fake_llm)
    assert result == original


def test_refine_sections_llm_fewer_than_2_matches_returns_original():
    """If only 1 heading matches, return original sections (< 2 threshold)."""
    text = (
        "Introduction\n"
        "Intro content here.\n"
        "More content here with enough text.\n"
    )
    original = [Section("s1", "Full Text", 1, None, 0, len(text))]

    def fake_llm(prompt: str) -> str:
        # Only 1 real heading + 2 hallucinated
        return _make_llm_response(["Introduction", "Fake Section Alpha", "Fake Section Beta"])

    result = refine_sections_llm(text, original, fake_llm)
    # "Introduction" matches, but "Fake Section Alpha" and "Fake Section Beta" don't
    # Only 1 match -> return original
    assert result == original


def test_refine_sections_llm_no_json_object_returns_original():
    """If LLM returns text with no '{', return original sections."""
    text = "Some text.\n"
    original = [Section("s1", "Full Text", 1, None, 0, len(text))]

    def fake_llm(prompt: str) -> str:
        return "Sorry, I cannot help with that."

    result = refine_sections_llm(text, original, fake_llm)
    assert result == original


def test_refine_sections_llm_tiling():
    """Refined sections from LLM tile the text (last ends at len(text))."""
    text = (
        "Introduction\n"
        "Intro body text here is long enough.\n\n"
        "Conclusion\n"
        "Conclusion body text here is long enough.\n"
    )
    original = [Section("s1", "Full Text", 1, None, 0, len(text))]

    def fake_llm(prompt: str) -> str:
        return _make_llm_response(["Introduction", "Conclusion"])

    result = refine_sections_llm(text, original, fake_llm)
    assert len(result) >= 2
    result.sort(key=lambda s: s.char_start)
    assert result[-1].char_end == len(text)


# ===========================================================================
# build_and_save_sections — caching, force, stale sha, llm fallback
# ===========================================================================

def _make_paper(paper_id: str, text: str) -> store.PaperMetadata:
    """Helper: create minimal metadata and text for a paper."""
    meta = store.PaperMetadata(
        paper_id=paper_id,
        title="Test Paper",
        authors=["Author A"],
        year=2024,
    )
    meta.save()
    store.save_text(paper_id, text)
    return meta


def test_build_and_save_sections_unknown_paper_raises():
    """build_and_save_sections raises ValueError for unknown paper_id."""
    with pytest.raises(ValueError, match="Unknown paper_id"):
        build_and_save_sections("arxiv:0000.00000")


def test_build_and_save_sections_basic():
    """build_and_save_sections returns Section objects and persists them."""
    paper_id = "arxiv:1234.56789"
    text = (
        "1 Introduction\n"
        "This is the intro text here that is definitely long enough to pass.\n\n"
        "2 Methods\n"
        "This is the methods text here that is also definitely long enough.\n\n"
        "3 Conclusion\n"
        "Conclusion text.\n"
    )
    _make_paper(paper_id, text)

    sections = build_and_save_sections(paper_id)
    assert len(sections) >= 3
    assert all(isinstance(s, Section) for s in sections)

    # Persisted
    cached = store.load_sections(paper_id)
    assert cached is not None
    assert cached["version"] == 1


def test_build_and_save_sections_caching_honored():
    """Second call returns cached result without rebuilding (counting fake)."""
    paper_id = "arxiv:1234.56790"
    text = (
        "1 Introduction\n"
        "Intro text here that is long enough.\n\n"
        "2 Methods\n"
        "Methods text here that is also long enough.\n\n"
        "3 Conclusion\n"
        "Conclusion text.\n"
    )
    _make_paper(paper_id, text)

    call_count = 0

    # Monkey-patch build_section_tree to count calls
    import research_companion.sections as sections_mod
    original_build = sections_mod.build_section_tree

    def counting_build(t):
        nonlocal call_count
        call_count += 1
        return original_build(t)

    sections_mod.build_section_tree = counting_build
    try:
        # First call: should build
        build_and_save_sections(paper_id)
        assert call_count == 1

        # Second call: should use cache, NOT rebuild
        build_and_save_sections(paper_id)
        assert call_count == 1  # still 1 — cache was used
    finally:
        sections_mod.build_section_tree = original_build


def test_build_and_save_sections_force_rebuilds():
    """force=True rebuilds even when cache is valid."""
    paper_id = "arxiv:1234.56791"
    text = (
        "1 Introduction\n"
        "Intro text here.\n\n"
        "2 Methods\n"
        "Methods text here that is long enough.\n\n"
        "3 Conclusion\n"
        "Conclusion text.\n"
    )
    _make_paper(paper_id, text)

    call_count = 0
    import research_companion.sections as sections_mod
    original_build = sections_mod.build_section_tree

    def counting_build(t):
        nonlocal call_count
        call_count += 1
        return original_build(t)

    sections_mod.build_section_tree = counting_build
    try:
        build_and_save_sections(paper_id)
        assert call_count == 1

        # Force rebuild
        build_and_save_sections(paper_id, force=True)
        assert call_count == 2
    finally:
        sections_mod.build_section_tree = original_build


def test_build_and_save_sections_stale_sha_rebuilds():
    """Stale text_sha (text changed) triggers rebuild."""
    paper_id = "arxiv:1234.56792"
    text_v1 = (
        "1 Introduction\n"
        "Version 1 intro text.\n\n"
        "2 Methods\n"
        "Version 1 methods text.\n\n"
        "3 Conclusion\n"
        "Version 1 conclusion.\n"
    )
    _make_paper(paper_id, text_v1)
    sections_v1 = build_and_save_sections(paper_id)

    # Simulate text change: save new text with different sha
    text_v2 = (
        "Abstract\n"
        "Version 2 abstract text here.\n\n"
        "Introduction\n"
        "Version 2 introduction text here.\n\n"
        "Conclusion\n"
        "Version 2 conclusion text.\n"
    )
    store.save_text(paper_id, text_v2)

    # Now build_and_save_sections should detect stale sha and rebuild
    sections_v2 = build_and_save_sections(paper_id)

    # The sections should reflect the new text structure
    titles_v2 = [s.title for s in sections_v2]
    # New text uses canonical names, not numbered headings
    assert any("Abstract" in t or "Introduction" in t or "Conclusion" in t for t in titles_v2)


def test_build_and_save_sections_llm_fallback_triggered_when_lt3_sections():
    """LLM fallback is triggered only when heuristics found < 3 sections."""
    paper_id = "arxiv:1234.56793"
    # Plain unstructured text with NO detectable headings
    text = (
        "This is a plain text paper without any section headings.\n"
        "It has multiple paragraphs but no obvious structure.\n"
        "More content here to ensure the text is long enough for the test.\n"
        "Additional content to make the text have sufficient length.\n"
    )
    _make_paper(paper_id, text)

    llm_call_count = 0

    def fake_llm(prompt: str) -> str:
        nonlocal llm_call_count
        llm_call_count += 1
        # Return 2 headings that are actually in the text
        return json.dumps({
            "headings": [
                "This is a plain text paper without any section headings.",
                "More content here to ensure the text is long enough for the test.",
            ]
        })

    sections = build_and_save_sections(paper_id, llm=fake_llm)
    # LLM should have been called because heuristics found < 3 sections
    assert llm_call_count == 1


def test_build_and_save_sections_llm_not_triggered_when_gte3_sections():
    """LLM fallback is NOT triggered when heuristics found >= 3 sections."""
    paper_id = "arxiv:1234.56794"
    text = (
        "1 Introduction\n"
        "This is the introductory section with sufficient body text to pass the filter.\n\n"
        "2 Methods\n"
        "This is the methods section with sufficient body text to pass the body filter.\n\n"
        "3 Results\n"
        "This is the results section with sufficient body text to pass the body filter.\n\n"
        "4 Conclusion\n"
        "Conclusion text here.\n"
    )
    _make_paper(paper_id, text)

    llm_call_count = 0

    def fake_llm(prompt: str) -> str:
        nonlocal llm_call_count
        llm_call_count += 1
        return json.dumps({"headings": ["Introduction", "Methods", "Results", "Conclusion"]})

    sections = build_and_save_sections(paper_id, llm=fake_llm)
    # LLM should NOT be called since >= 3 sections found
    assert llm_call_count == 0
    assert len(sections) >= 3


def test_build_and_save_sections_method_heuristic():
    """Method field is 'heuristic' when no LLM is used."""
    paper_id = "arxiv:1234.56795"
    text = (
        "1 Introduction\n"
        "Intro text here.\n\n"
        "2 Methods\n"
        "Methods text here.\n\n"
        "3 Conclusion\n"
        "Conclusion text.\n"
    )
    _make_paper(paper_id, text)
    build_and_save_sections(paper_id)

    cached = store.load_sections(paper_id)
    assert cached["method"] == "heuristic"


def test_build_and_save_sections_method_heuristic_plus_llm():
    """Method field is 'heuristic+llm' when LLM refinement is used."""
    paper_id = "arxiv:1234.56796"
    # Unstructured text to trigger LLM fallback
    text = (
        "This is a plain text paper without clear section structure.\n"
        "Introduction to the problem we are solving here.\n"
        "Method description for our solution.\n"
        "Conclusion of the paper.\n"
    )
    _make_paper(paper_id, text)

    def fake_llm(prompt: str) -> str:
        return json.dumps({
            "headings": [
                "Introduction to the problem we are solving here.",
                "Method description for our solution.",
            ]
        })

    build_and_save_sections(paper_id, llm=fake_llm)
    cached = store.load_sections(paper_id)
    assert cached["method"] == "heuristic+llm"
