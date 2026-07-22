"""Tests for research_companion.opportunities — uncited-paper opportunities.

Strictness contract: every suggestion must trace back to stored analysis
(store.load_alignment / store.load_strength) for a paper that
citations_coverage.compute_coverage says is NOT cited by the active draft.
No LLM, no network, no fabricated impact.
"""
from __future__ import annotations

import pytest

from research_companion import opportunities, store
from research_companion.citations_coverage import compute_coverage

DRAFT_ID = "local:draftopp001"
PAPER_A = "arxiv:1111.00001"  # cited by the draft (matched via arXiv id)
PAPER_B = "arxiv:2222.00002"  # uncited, strong alignment
PAPER_C = "arxiv:3333.00003"  # uncited, weaker alignment


@pytest.fixture
def seeded_workspace(isolated_papergraph_dir):
    """Seed a workspace with a draft D, a cited paper A, and two uncited
    papers B and C that each carry stored alignment against the draft."""
    text = (
        "Introduction\n"
        "Some body text discussing prior work.\n\n"
        "References\n"
        "[1] A. Author. A Paper About Something Specific And Long Enough Title. "
        "arXiv:1111.00001, 2020.\n"
        "[2] B. Author. An unrelated citation string not present in the library. 2021.\n"
        "[3] C. Author. Yet another citation not matched to any library paper. 2022.\n"
    )
    store.PaperMetadata(paper_id=DRAFT_ID, title="My Draft", authors=["Me"],
                         year=2026, added_at="2026-01-01T00:00:00Z").save()
    store.save_text(DRAFT_ID, text)
    store.set_draft_paper_id(DRAFT_ID)

    store.PaperMetadata(
        paper_id=PAPER_A,
        title="A Paper About Something Specific And Long Enough Title",
        authors=["A Author"], year=2020, added_at="2026-01-01T00:00:00Z").save()
    store.PaperMetadata(paper_id=PAPER_B, title="Paper B Title", authors=["B Author"],
                         year=2021, added_at="2026-01-01T00:00:00Z").save()
    store.PaperMetadata(paper_id=PAPER_C, title="Paper C Title", authors=["C Author"],
                         year=2022, added_at="2026-01-01T00:00:00Z").save()

    store.save_alignment(PAPER_B, {
        "draft_paper_id": DRAFT_ID,
        "sections": [
            {"section_id": "s1", "section_title": "Introduction", "relation": "strengthens",
             "relevance": 0.9, "rationale": "B strongly supports the intro claim.",
             "evidence": ["quote from B"]},
        ],
    })
    store.save_alignment(PAPER_C, {
        "draft_paper_id": DRAFT_ID,
        "sections": [
            {"section_id": "s1", "section_title": "Introduction",
             "relation": "offers_alternative", "relevance": 0.4,
             "rationale": "C offers an alternative method.",
             "evidence": ["quote from C"]},
        ],
    })
    store.save_strength(PAPER_B, {"score": 0.8, "band": "strong", "color": "#3fb950"})
    store.save_strength(PAPER_C, {"score": 0.3, "band": "weak", "color": "#f85149"})

    # Persist coverage so uncited_paper_ids has something to read.
    compute_coverage(DRAFT_ID)

    return {"draft_id": DRAFT_ID, "A": PAPER_A, "B": PAPER_B, "C": PAPER_C}


def test_uncited_excludes_cited_and_draft(seeded_workspace):
    draft_id = store.get_draft_paper_id()
    uncited = opportunities.uncited_paper_ids(draft_id)
    assert draft_id not in uncited
    assert PAPER_A not in uncited        # cited (matched)
    assert {PAPER_B, PAPER_C} <= uncited


def test_build_opportunities_shape_and_sorting(seeded_workspace):
    draft_id = store.get_draft_paper_id()
    out = opportunities.build_opportunities(draft_id)
    assert out["draft_id"] == draft_id
    assert out["sections"], "expected at least one section with suggestions"
    for sec in out["sections"]:
        rels = [s["relevance"] for s in sec["suggestions"]]
        assert rels == sorted(rels, reverse=True)
        for s in sec["suggestions"]:
            assert s["paper_id"] in opportunities.uncited_paper_ids(draft_id)
            assert set(s) >= {"paper_id", "title", "relation", "relevance",
                               "rationale", "evidence", "strength_band"}

    # The cited paper A must never appear as a suggestion anywhere.
    for sec in out["sections"]:
        assert all(s["paper_id"] != PAPER_A for s in sec["suggestions"])

    # B (relevance 0.9) must outrank C (relevance 0.4) within section s1.
    s1 = next(sec for sec in out["sections"] if sec["section_id"] == "s1")
    ids_in_order = [s["paper_id"] for s in s1["suggestions"]]
    assert ids_in_order.index(PAPER_B) < ids_in_order.index(PAPER_C)

    # strength_band carried through from store.load_strength.
    b_sugg = next(s for s in s1["suggestions"] if s["paper_id"] == PAPER_B)
    assert b_sugg["strength_band"] == "strong"


def test_build_opportunities_empty_sections_omitted(seeded_workspace):
    draft_id = store.get_draft_paper_id()
    out = opportunities.build_opportunities(draft_id)
    for sec in out["sections"]:
        assert sec["suggestions"], "sections with zero suggestions must be omitted"


def test_build_opportunities_no_draft(isolated_papergraph_dir):
    store.set_draft_paper_id(None)
    assert opportunities.build_opportunities(None) == {"draft_id": None, "sections": []}
