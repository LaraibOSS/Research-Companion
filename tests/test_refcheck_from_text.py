"""Parsing a bibliography straight from a paper's text, with no model call.

`references_from_extraction` needs an LLM `build` first, so verifying that a
paper's citations exist -- a deterministic, network-only check -- was gated
behind a paid step. This path is free.

The property that matters most is **honest coverage**: a checker that silently
drops half a bibliography reports a clean result over references it never
looked at. Anything not parsed is returned, never discarded.
"""
from __future__ import annotations

from research_companion.refcheck.parse import (
    bibliography_section,
    references_from_text,
    split_reference_entries,
)

NUMBERED = """Introduction
We build on prior references in the literature.

References
[1] A. Smith and B. Jones. Graph retrieval for QA.
    In Proc. NeurIPS, 2023. arXiv:2301.01234
[2] C. Lee. Dense passage retrieval. ACL 2020. doi:10.1234/acl.2020.55
[3] D. Patel. A study of recurrence. 2022.

Appendix A
Extra proofs that mention 2021.
"""


def test_a_numbered_bibliography_parses_with_identifiers():
    refs, unparsed = references_from_text(NUMBERED)
    assert len(refs) == 3
    assert unparsed == []
    assert refs[0].year == 2023 and refs[0].arxiv_id == "2301.01234"
    assert refs[1].doi == "10.1234/acl.2020.55"
    assert refs[2].year == 2022


def test_a_wrapped_entry_stays_one_reference():
    """Entry [1] spans two lines. Splitting on newlines would invent a
    reference out of the continuation and report a phantom missing citation."""
    refs, _ = references_from_text(NUMBERED)
    assert "NeurIPS" in refs[0].raw
    assert len(refs) == 3


def test_an_appendix_is_not_parsed_as_citations():
    section = bibliography_section(NUMBERED)
    assert "Extra proofs" not in section
    assert "D. Patel" in section


def test_prose_mentioning_references_does_not_start_a_bibliography():
    assert bibliography_section("We build on prior references in the literature.") == ""
    assert references_from_text("Just prose, no heading.") == ([], [])


def test_the_last_heading_wins():
    """Papers cite the word in prose and some carry per-section lists; the real
    bibliography is the final one."""
    text = "References\n[1] Early stray line.\n\nReferences\n[1] The real one, 2024.\n"
    assert "The real one" in bibliography_section(text)
    assert "Early stray" not in bibliography_section(text)


def test_blank_line_separated_entries_are_supported():
    text = ("Bibliography\n\n"
            "Smith, A. (2023). Graph retrieval for question answering. NeurIPS.\n\n"
            "Lee, C. (2020). Dense passage retrieval. ACL.\n")
    refs, unparsed = references_from_text(text)
    assert len(refs) == 2
    assert unparsed == []


def test_fragments_are_reported_not_silently_dropped():
    """A page number left in the text is not a reference — but it must show up
    in `unparsed` so coverage can be reported honestly."""
    text = "References\n\nSmith, A. (2023). A real reference title here. NeurIPS.\n\n12\n"
    refs, unparsed = references_from_text(text)
    assert len(refs) == 1
    assert unparsed == ["12"]


def test_alternative_headings_are_recognised():
    for heading in ("References", "REFERENCES", "Bibliography", "Works Cited",
                    "6. References", "References:"):
        text = f"{heading}\n[1] Smith, A. A sufficiently long reference title. 2020.\n"
        refs, _ = references_from_text(text)
        assert len(refs) == 1, f"{heading!r} not recognised as a bibliography heading"


def test_empty_and_malformed_input_never_raises():
    for bad in ("", None, "   ", "References\n"):
        refs, unparsed = references_from_text(bad)
        assert refs == [] and unparsed == []
    assert split_reference_entries(None) == ([], [])
