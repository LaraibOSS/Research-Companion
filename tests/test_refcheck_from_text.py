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


# ---------------------------------------------------------------------------
# A bibliography line is not a title
#
# Feeding text-parsed references into a validator tuned for clean, LLM-extracted
# titles produced "suspect" verdicts on perfectly correct citations. At the base
# rate this tool targets, false accusations are the failure that makes people
# stop reading the warnings -- so the matcher has to tolerate the two ways real
# bibliographies deviate, without excusing a genuinely wrong citation.
# ---------------------------------------------------------------------------

from research_companion.refcheck.matching import title_is_cited  # noqa: E402

ATTENTION = "Attention Is All You Need"
BERT = ("BERT: Pre-training of Deep Bidirectional Transformers for Language "
        "Understanding")


def test_surrounding_authors_and_venue_do_not_break_the_match():
    assert title_is_cited("Vaswani et al. Attention is all you need. NeurIPS 2017",
                          ATTENTION)


def test_a_truncated_title_still_matches():
    """Bibliographies routinely shorten long titles; that is not a miscitation."""
    assert title_is_cited(
        "Devlin et al. BERT: pre-training of deep bidirectional transformers. 2018",
        BERT)
    assert title_is_cited("Lee. Dense passage retrieval. ACL",
                          "Dense Passage Retrieval for Open-Domain Question Answering")


def test_an_exact_title_still_matches():
    assert title_is_cited(ATTENTION, ATTENTION)


def test_a_different_paper_is_still_caught():
    assert not title_is_cited("Smith. A completely different paper about frogs. 2020",
                              ATTENTION)


def test_a_short_generic_overlap_is_not_a_match():
    """"Deep learning" appears in thousands of titles; matching on it would
    verify almost anything."""
    assert not title_is_cited("Jones. Deep learning. 2019",
                              "Deep Learning for Molecular Property Prediction")


def test_an_empty_authoritative_title_never_matches():
    assert not title_is_cited("Anything at all", "")


def test_the_validator_compares_against_the_whole_cited_line():
    """The fix only works if validate_reference passes ref.raw, not ref.title."""
    import pathlib

    src = pathlib.Path("research_companion/refcheck/validate.py").read_text(encoding="utf-8")
    assert "title_is_cited(" in src
    assert "ref.raw or ref.title" in src


def test_a_page_number_is_not_glued_onto_the_previous_citation():
    """Extracted text carries page artifacts. Treating a bare "9" as a
    continuation corrupts that reference's title AND hides it from the unparsed
    count, so coverage looks complete when it is not."""
    text = ("References\n"
            "[1] Vaswani et al. Attention is all you need. NeurIPS 2017.\n"
            "9\n"
            "[2] Lee. Dense passage retrieval for open-domain QA. ACL 2020.\n")
    refs, unparsed = references_from_text(text)
    assert len(refs) == 2
    assert unparsed == ["9"]
    assert "9" not in refs[0].raw.split()[-1:]


def test_page_artifact_shapes():
    from research_companion.refcheck.parse import _PAGE_ARTIFACT_RE

    for stray in ("9", " 12 ", "Page 7", "- 7 -", "  1234"):
        assert _PAGE_ARTIFACT_RE.match(stray), f"{stray!r} should be a page artifact"
    for real in ("2020. A paper.", "Smith, A.", "1706.03762"):
        assert not _PAGE_ARTIFACT_RE.match(real), f"{real!r} is not a page artifact"


# ---------------------------------------------------------------------------
# The format the parser ACTUALLY produces
#
# Every test above passed while the parser found no bibliography at all in a
# real paper. The fixtures were hand-written plain text; the default parser
# emits MARKDOWN. Tests written against an assumed input format verify the
# assumption, not the system. These use the real shape, taken verbatim from
# docling output for arXiv:1706.03762.
# ---------------------------------------------------------------------------

MARKDOWN_REAL = """## Acknowledgements

We are grateful for their fruitful comments.

## References

- [1] Jimmy Lei Ba, Jamie Ryan Kiros, and Geoffrey E Hinton. Layer normalization.
  arXiv preprint arXiv:1607.06450, 2016.
- [2] Dzmitry Bahdanau, Kyunghyun Cho, and Yoshua Bengio. Neural machine
  translation by jointly learning to align and translate. CoRR, abs/1409.0473, 2014.
- [3] Denny Britz, Anna Goldie, Minh-Thang Luong, and Quoc V. Le. Massive
  exploration of neural machine translation architectures. CoRR, abs/1703.03906, 2017.

## Attention Visualizations
"""


def test_a_markdown_heading_starts_the_bibliography():
    """"## References" is what the default parser emits. Matching only a bare
    "References" finds nothing on the most common real input."""
    section = bibliography_section(MARKDOWN_REAL)
    assert section, "no bibliography found in real parser output"
    assert "Jimmy Lei Ba" in section


def test_markdown_list_bullets_do_not_hide_entry_markers():
    """Entries arrive as "- [1] ..." not "[1] ...". Missing the bullet collapses
    the whole bibliography into one giant reference."""
    refs, unparsed = references_from_text(MARKDOWN_REAL)
    assert len(refs) == 3, f"expected 3 entries, got {len(refs)}"
    assert unparsed == []


def test_identifiers_survive_the_real_format():
    refs, _ = references_from_text(MARKDOWN_REAL)
    assert refs[0].arxiv_id == "1607.06450"
    assert refs[0].year == 2016
    assert refs[1].year == 2014


def test_a_markdown_section_after_the_bibliography_ends_it():
    section = bibliography_section(MARKDOWN_REAL)
    assert "Attention Visualizations" not in section


def test_bold_and_numbered_heading_variants():
    for heading in ("## References", "### REFERENCES", "**References**",
                    "## 6. References", "# Bibliography"):
        text = f"{heading}\n- [1] Smith, A. A sufficiently long reference title here. 2020.\n"
        refs, _ = references_from_text(text)
        assert len(refs) == 1, f"{heading!r} not recognised"


def test_a_short_real_title_is_not_rejected_by_the_length_floor():
    """"Layer Normalization" normalises to 19 chars and matched its record
    100%, but a 20-char floor rejected it -- an arbitrary threshold turning a
    perfect match into a "suspect" verdict on a real paper."""
    assert title_is_cited(
        "Jimmy Lei Ba, Jamie Ryan Kiros, and Geoffrey E Hinton. Layer normalization",
        "Layer Normalization")


def test_the_floor_still_blocks_a_short_generic_phrase():
    assert not title_is_cited("Jones. Deep learning. 2019", "Deep Learning")
    assert not title_is_cited("Jones. Deep learning. 2019",
                              "Deep Learning for Molecular Property Prediction")


# ---------------------------------------------------------------------------
# probable_title: the lookup query
# ---------------------------------------------------------------------------

from research_companion.refcheck.parse import probable_title  # noqa: E402

REAL_ENTRIES = [
    ("Kaiming He, Xiangyu Zhang, Shaoqing Ren, and Jian Sun. Deep residual "
     "learning for image recognition. In Proceedings of the IEEE Conference, 2016",
     "Deep residual learning for image recognition"),
    ("Sepp Hochreiter and Jurgen Schmidhuber. Long short-term memory. Neural "
     "computation, 9(8):1735-1780, 1997",
     "Long short-term memory"),
    ("Jimmy Lei Ba, Jamie Ryan Kiros, and Geoffrey E Hinton. Layer normalization",
     "Layer normalization"),
    ("Dzmitry Bahdanau, Kyunghyun Cho, and Yoshua Bengio. Neural machine "
     "translation by jointly learning to align and translate. CoRR, 2014",
     "Neural machine translation by jointly learning to align and translate"),
]


def test_probable_title_extracts_the_title_from_real_entries():
    """Searching a catalogue with the whole line found nothing: on a real
    40-reference paper that alone put 18 well-known papers in "not found"."""
    for raw, expected in REAL_ENTRIES:
        assert probable_title(raw) == expected, raw[:60]


def test_a_three_word_title_beats_a_longer_author_list():
    """Scoring by length prefers the authors here; scoring by lowercase ratio
    does not."""
    assert probable_title(
        "Sepp Hochreiter and Jurgen Schmidhuber. Long short-term memory. "
        "Neural computation, 9(8):1735-1780, 1997") == "Long short-term memory"


def test_a_bare_title_survives_unchanged():
    assert probable_title("Attention Is All You Need") == "Attention Is All You Need"
    assert probable_title("") == ""


def test_the_lookup_queries_the_extracted_title():
    """The fix only works if retrieval searches with probable_title."""
    import pathlib

    src = pathlib.Path("research_companion/refcheck/retrieval.py").read_text(encoding="utf-8")
    assert "probable_title(ref.raw or ref.title)" in src
    assert "items = search(ref.title)" not in src
    # and candidate acceptance must use the whole-line comparison too
    assert "title_is_cited(cited" in src
