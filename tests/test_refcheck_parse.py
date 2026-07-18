"""Tests for research_companion.refcheck.parse — turning bibliography text into References."""
from __future__ import annotations

from research_companion.refcheck import parse
from research_companion.refcheck.validate import Reference

# --- field extractors (pure) ------------------------------------------------

def test_extract_doi_from_citation():
    raw = "Vaswani et al. Attention is all you need. doi:10.5555/3295222.3295349"
    assert parse.extract_doi(raw) == "10.5555/3295222.3295349"


def test_extract_doi_none_when_absent():
    assert parse.extract_doi("No identifier here.") is None


def test_extract_arxiv_id_from_citation():
    raw = "Attention is all you need. arXiv:1706.03762v5"
    assert parse.extract_arxiv_id(raw) == "1706.03762"


def test_extract_arxiv_id_none_when_absent():
    assert parse.extract_arxiv_id("No preprint id here.") is None


def test_extract_year_from_citation():
    assert parse.extract_year("Vaswani et al. (2017). Attention is all you need.") == 2017


def test_extract_year_none_when_absent():
    assert parse.extract_year("No date in this string.") is None


def test_extract_year_ignores_implausible_numbers():
    # A 4-digit number outside [1900, 2100) is not a publication year.
    assert parse.extract_year("Model trained on 5000 examples.") is None


# --- parse_reference_string -------------------------------------------------

def test_parse_reference_string_returns_reference_with_identifiers():
    raw = "Attention Is All You Need. arXiv:1706.03762v5. 2017."
    ref = parse.parse_reference_string(raw)
    assert isinstance(ref, Reference)
    assert ref.arxiv_id == "1706.03762"
    assert ref.year == 2017
    assert ref.raw == raw


def test_parse_reference_string_strips_identifiers_from_title():
    raw = "Attention Is All You Need. arXiv:1706.03762"
    ref = parse.parse_reference_string(raw)
    # The arXiv token must not leak into the title used for matching.
    assert "arxiv" not in ref.title.lower()
    assert "1706.03762" not in ref.title
    assert "Attention Is All You Need" in ref.title


def test_parse_reference_string_empty_is_empty_reference():
    ref = parse.parse_reference_string("   ")
    assert ref.title == ""
    assert ref.arxiv_id is None
    assert ref.doi is None


# --- references_from_extraction (research-companion wiring) -------------------------

def test_references_from_extraction_parses_related_work():
    extraction = {
        "concepts": ["irrelevant"],
        "related_work": [
            "Attention Is All You Need. arXiv:1706.03762",
            "BERT: Pre-training of Deep Bidirectional Transformers. 2018",
        ],
    }
    refs = parse.references_from_extraction(extraction)
    assert len(refs) == 2
    assert refs[0].arxiv_id == "1706.03762"
    assert refs[1].year == 2018
    assert "BERT" in refs[1].title


def test_references_from_extraction_missing_key_is_empty():
    assert parse.references_from_extraction({"concepts": []}) == []


def test_references_from_extraction_skips_blank_entries():
    extraction = {"related_work": ["Attention Is All You Need", "", "   "]}
    refs = parse.references_from_extraction(extraction)
    assert len(refs) == 1


def test_extract_pmid_and_pmcid():
    assert parse.extract_pmid("Foo et al. PMID: 30449619. Cell 2018.") == "30449619"
    assert parse.extract_pmcid("Bar et al. PMC6289601.") == "PMC6289601"
    assert parse.extract_pmid("No id here") is None


def test_parse_reference_string_populates_pmid_and_strips_from_title():
    ref = parse.parse_reference_string("Shifrut E. CRISPR screens. Cell 2018. PMID: 30449619")
    assert ref.pmid == "30449619"
    assert "30449619" not in ref.title
    assert "PMID" not in ref.title
