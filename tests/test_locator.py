"""Citation locators — the pointer that makes a claim checkable.

The properties under test: an anchor is either real or absent, never invented;
and "anchorless" is a distinguishable state rather than a silent gap.
"""
from __future__ import annotations

from research_companion.locator import (
    Locator,
    LocatorKind,
    anchor_quote,
    anchor_section,
    anchorless,
    resolve,
)

FULLTEXT = (
    "Introduction to the method. "
    "Graph retrieval reduces error on multi-hop questions. "
    "We evaluate on three datasets."
)


def test_exact_quote_anchors_to_its_character_range():
    loc = anchor_quote("p1", "Graph retrieval reduces error", FULLTEXT)
    assert loc.kind is LocatorKind.QUOTE
    assert loc.is_anchored is True
    assert resolve(loc, FULLTEXT) == "Graph retrieval reduces error"


def test_whitespace_and_case_differences_still_anchor_to_the_minimal_span():
    """A quote copied with sloppy whitespace must resolve to exactly the quoted
    words — not to a span that trails extra words the author never quoted."""
    loc = anchor_quote("p1", "graph   retrieval  REDUCES error", FULLTEXT)
    assert loc.kind is LocatorKind.QUOTE
    assert resolve(loc, FULLTEXT) == "Graph retrieval reduces error"


def test_a_quote_not_in_the_text_never_gets_invented_offsets():
    loc = anchor_quote("p1", "a sentence that does not appear", FULLTEXT)
    assert loc.kind is LocatorKind.PAPER      # we still know the paper
    assert loc.is_anchored is False           # but nothing to check against
    assert loc.char_start is None and loc.char_end is None
    assert resolve(loc, FULLTEXT) == ""


def test_missing_inputs_degrade_to_anchorless():
    assert anchor_quote("", "q", FULLTEXT).is_anchored is False
    assert anchor_quote("p1", "", FULLTEXT).is_anchored is False
    assert anchor_quote("p1", "q", "").is_anchored is False


def test_section_anchor_carries_the_tilings_range():
    payload = {"sections": [
        {"section_id": "s1", "char_start": 0, "char_end": 27},
        {"section_id": "s2", "char_start": 27, "char_end": 81},
    ]}
    loc = anchor_section("p1", "s2", payload)
    assert loc.kind is LocatorKind.SECTION
    assert loc.is_anchored is True
    assert "Graph retrieval" in resolve(loc, FULLTEXT)


def test_a_section_the_tiling_does_not_have_is_not_faked():
    payload = {"sections": [{"section_id": "s1", "char_start": 0, "char_end": 10}]}
    loc = anchor_section("p1", "s99", payload)
    assert loc.is_anchored is False
    assert loc.section_id is None


def test_naming_a_paper_is_not_an_anchor():
    """A citation that names a document says where to look, not what to check."""
    assert anchorless("p1").kind is LocatorKind.PAPER
    assert anchorless("p1").is_anchored is False
    assert anchorless("").kind is LocatorKind.NONE


def test_anchor_strength_is_ordered_so_anchors_can_be_compared():
    quote = anchor_quote("p1", "Graph retrieval reduces error", FULLTEXT)
    section = anchor_section("p1", "s1", {"sections": [
        {"section_id": "s1", "char_start": 0, "char_end": 27}]})
    assert quote.strength > section.strength > anchorless("p1").strength
    assert anchorless("p1").strength > anchorless("").strength


def test_resolve_clamps_out_of_range_offsets_instead_of_raising():
    loc = Locator(paper_id="p1", kind=LocatorKind.QUOTE,
                  char_start=-5, char_end=10_000)
    assert resolve(loc, FULLTEXT) == FULLTEXT


def test_to_dict_reports_whether_the_citation_can_be_audited():
    d = anchor_quote("p1", "Graph retrieval reduces error", FULLTEXT).to_dict()
    assert d["is_anchored"] is True
    assert d["kind"] == "quote"
    assert anchorless("p1").to_dict()["is_anchored"] is False


# ---------------------------------------------------------------------------
# End-to-end: alignment evidence must carry a re-checkable anchor
# ---------------------------------------------------------------------------

def test_alignment_evidence_carries_a_locator(isolated_papergraph_dir):
    """A verified quote that cannot be located again is a dead end — the
    passage has to be retrievable for any later claim audit."""
    import json

    from research_companion import store
    from research_companion.alignment import align_papers
    from research_companion.prompts import extraction_prompt_sha256

    cand_text = ("Background. Graph retrieval reduces error on multi-hop "
                 "questions. We evaluate on three datasets.")

    for pid, text in (("arxiv:draft1", "Our draft studies retrieval."),
                      ("arxiv:cand1", cand_text)):
        store.PaperMetadata(paper_id=pid, title=pid, authors=["A"], year=2024,
                            added_at="2026-01-01T00:00:00Z").save()
        store.save_text(pid, text)
        store.save_extraction(pid, {"concepts": [], "methods": [], "datasets": [],
                                    "claims": [], "results": [], "related_work": []},
                              prompt_sha=extraction_prompt_sha256())
    store.save_sections("arxiv:draft1", {"method": "test", "sections": [
        {"section_id": "s1", "title": "Intro", "level": 1, "parent": None,
         "char_start": 0, "char_end": len("Our draft studies retrieval.")}]})

    def fake_llm(prompt: str) -> str:
        return json.dumps({"sections": [{
            "section_id": "s1", "relation": "strengthens", "relevance": 0.8,
            "rationale": "Supports the retrieval claim.",
            "evidence": [{"quote": "Graph retrieval reduces error"}],
        }]})

    payload = align_papers("arxiv:draft1", "arxiv:cand1", llm=fake_llm, persist=False)

    evidence = payload["sections"][0]["evidence"][0]
    assert evidence["verified"] is True
    loc = evidence["locator"]
    assert loc["is_anchored"] is True
    assert loc["kind"] == "quote"
    assert loc["paper_id"] == "arxiv:cand1"
    # the anchor must actually resolve back to the quoted words
    assert cand_text[loc["char_start"]:loc["char_end"]] == "Graph retrieval reduces error"
