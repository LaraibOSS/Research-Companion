"""Tests for Task 3: section-aware wiring in extract.py.

TDD: written before implementation. Tests cover:
- extract_paper passes section outline to render when build_and_save_sections returns sections
- fake LLM receives a prompt containing "s1 " and "s2 " outline lines
- extract_paper sanitizes unknown section ids to None, keeps valid ones
- extract_paper still works when build_and_save_sections raises (outline empty, no crash)
"""
from __future__ import annotations

import json

import pytest

from research_companion import extract, fetch, prompts, store
from research_companion.sections import Section


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_extraction_with_sections(valid_id: str, invalid_id: str) -> dict:
    """Build a sample extraction where some entities have section ids."""
    return {
        "concepts": [
            {"name": "Concept A", "definition": "def A", "section": valid_id},
            {"name": "Concept B", "definition": "def B", "section": invalid_id},
            {"name": "Concept C", "definition": "def C", "section": None},
        ],
        "methods": [
            {"name": "Method X", "description": "desc X", "section": valid_id},
        ],
        "datasets": [
            {"name": "Dataset D", "description": "desc D", "section": "totally_unknown"},
        ],
        "claims": [
            {"text": "Claim 1", "section": valid_id},
        ],
        "results": [
            {"metric": "F1", "value": "80.0", "dataset": "Dataset D", "section": invalid_id},
        ],
        "related_work": ["Lewis et al. 2020"],
    }


# ---------------------------------------------------------------------------
# Test: outline lines appear in the prompt sent to the LLM
# ---------------------------------------------------------------------------

def test_extract_paper_prompt_contains_outline_lines(
    monkeypatch: pytest.MonkeyPatch,
    fake_pdf_bytes: bytes,
    tmp_path,
):
    """When build_and_save_sections returns 2 sections, the LLM prompt contains
    'sN <Title>' outline lines."""
    pdf = tmp_path / "p.pdf"
    pdf.write_bytes(fake_pdf_bytes)
    meta = fetch.add_local_pdf(pdf, title="Outline Test Paper")

    # Stub sections
    fake_sections = [
        Section("s1", "Introduction", 1, None, 0, 50),
        Section("s2", "Methods", 1, None, 50, 100),
    ]

    import research_companion.extract as extract_mod
    import research_companion.sections as sections_mod
    monkeypatch.setattr(sections_mod, "build_and_save_sections", lambda paper_id, **kwargs: fake_sections)

    captured_prompts: list[str] = []

    sample = {
        "concepts": [], "methods": [], "datasets": [],
        "claims": [], "results": [], "related_work": [],
    }

    def fake_llm(prompt, model, max_output_tokens=2048):
        captured_prompts.append(prompt)
        return json.dumps(sample), {"input_tokens": 10, "output_tokens": 10}

    monkeypatch.setattr(extract_mod, "_call_anthropic", fake_llm)

    extract_mod.extract_paper(meta, provider="anthropic", force=True)

    assert len(captured_prompts) == 1
    rendered = captured_prompts[0]
    assert "s1 Introduction" in rendered
    assert "s2 Methods" in rendered


# ---------------------------------------------------------------------------
# Test: sanitize unknown section ids to None, keep valid ones
# ---------------------------------------------------------------------------

def test_extract_paper_sanitizes_unknown_section_ids(
    monkeypatch: pytest.MonkeyPatch,
    fake_pdf_bytes: bytes,
    tmp_path,
):
    """Entities with unknown section ids get their 'section' set to None.
    Entities with known ids are left intact."""
    pdf = tmp_path / "p.pdf"
    pdf.write_bytes(fake_pdf_bytes)
    meta = fetch.add_local_pdf(pdf, title="Sanitize Test Paper")

    valid_id = "s1"
    invalid_id = "s999_unknown"

    fake_sections = [
        Section("s1", "Introduction", 1, None, 0, 50),
        Section("s2", "Methods", 1, None, 50, 100),
    ]

    import research_companion.sections as sections_mod
    monkeypatch.setattr(sections_mod, "build_and_save_sections", lambda paper_id, **kwargs: fake_sections)

    llm_response = _make_extraction_with_sections(valid_id, invalid_id)

    monkeypatch.setattr(
        extract, "_call_anthropic",
        lambda prompt, model, max_output_tokens=2048: (
            json.dumps(llm_response),
            {"input_tokens": 10, "output_tokens": 10},
        ),
    )

    result, _ = extract.extract_paper(meta, provider="anthropic", force=True)

    # Valid section id must be preserved
    concept_a = next(c for c in result["concepts"] if c["name"] == "Concept A")
    assert concept_a["section"] == valid_id

    # Invalid section id must be set to None
    concept_b = next(c for c in result["concepts"] if c["name"] == "Concept B")
    assert concept_b["section"] is None

    # Already-None stays None
    concept_c = next(c for c in result["concepts"] if c["name"] == "Concept C")
    assert concept_c["section"] is None

    # Dataset with unknown section
    dataset_d = result["datasets"][0]
    assert dataset_d["section"] is None

    # Result with invalid section
    result_item = result["results"][0]
    assert result_item["section"] is None

    # related_work must not be affected
    assert result["related_work"] == ["Lewis et al. 2020"]


# ---------------------------------------------------------------------------
# Test: build_and_save_sections raises -> outline is empty, no crash
# ---------------------------------------------------------------------------

def test_extract_paper_survives_sections_error(
    monkeypatch: pytest.MonkeyPatch,
    fake_pdf_bytes: bytes,
    tmp_path,
):
    """If build_and_save_sections raises, extract_paper continues with empty outline."""
    pdf = tmp_path / "p.pdf"
    pdf.write_bytes(fake_pdf_bytes)
    meta = fetch.add_local_pdf(pdf, title="Error Test Paper")

    def raise_error(paper_id, **kwargs):
        raise RuntimeError("sections module exploded")

    import research_companion.sections as sections_mod
    monkeypatch.setattr(sections_mod, "build_and_save_sections", raise_error)

    captured_prompts: list[str] = []
    sample = {
        "concepts": [], "methods": [], "datasets": [],
        "claims": [], "results": [], "related_work": [],
    }

    def fake_llm(prompt, model, max_output_tokens=2048):
        captured_prompts.append(prompt)
        return json.dumps(sample), {"input_tokens": 5, "output_tokens": 5}

    monkeypatch.setattr(extract, "_call_anthropic", fake_llm)

    # Must not raise
    result, usage = extract.extract_paper(meta, provider="anthropic", force=True)
    assert result is not None
    assert usage["cached"] is False

    # Prompt must not contain section outline lines
    rendered = captured_prompts[0]
    assert "s1 " not in rendered or "Introduction" not in rendered  # no outline injected
    # More precise: the section instruction must not appear
    assert "set to the id of the section" not in rendered
