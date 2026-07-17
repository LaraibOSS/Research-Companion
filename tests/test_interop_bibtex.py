"""BibTeX export, cite-key generation, and parsing (incl. round-trip)."""
from research_companion.interop.bibtex import (
    cite_key,
    papers_to_bibtex,
    parse_bibtex,
)

REC = {
    "title": "Attention Is All You Need",
    "authors": ["Ashish Vaswani", "Noam Shazeer"],
    "year": 2017,
    "source_url": "https://arxiv.org/abs/1706.03762",
    "doi": "10.5555/3295222",
}


def test_cite_key_first_author_year():
    assert cite_key(REC) == "Vaswani2017"
    assert cite_key({"authors": ["Doe, Jane"], "year": 2020}) == "Doe2020"
    assert cite_key({"authors": [], "year": None, "paper_id": "x"}) == "x"


def test_papers_to_bibtex_fields():
    out = papers_to_bibtex([REC])
    assert out.startswith("@article{Vaswani2017,")
    assert "title = {Attention Is All You Need}" in out
    assert "author = {Ashish Vaswani and Noam Shazeer}" in out
    assert "year = {2017}" in out
    assert "doi = {10.5555/3295222}" in out
    assert "url = {https://arxiv.org/abs/1706.03762}" in out


def test_duplicate_keys_disambiguated():
    a = {"authors": ["Jane Doe"], "year": 2020, "title": "One"}
    b = {"authors": ["John Doe"], "year": 2020, "title": "Two"}
    out = papers_to_bibtex([a, b])
    assert "@article{Doe2020," in out
    assert "@article{Doe2020a," in out


def test_duplicate_keys_stay_alphabetic_past_z():
    """28+ same surname+year must not overflow past 'z' into '{' (corrupt BibTeX)."""
    import re

    from research_companion.interop.bibtex import parse_bibtex
    recs = [{"authors": ["Smith"], "year": 2020, "title": f"P{i}"} for i in range(30)]
    out = papers_to_bibtex(recs)
    assert "@article{Smith2020z," in out    # 27th
    assert "@article{Smith2020aa," in out   # 28th
    # every generated cite key is purely alphanumeric (no stray '{' from a bad suffix)
    keys = re.findall(r"@article\{([^,]+),", out)
    assert len(keys) == 30
    assert all(re.fullmatch(r"[A-Za-z0-9]+", k) for k in keys), keys
    assert len(parse_bibtex(out)) == 30   # round-trips cleanly


def test_parse_bibtex_round_trip():
    out = papers_to_bibtex([REC])
    parsed = parse_bibtex(out)
    assert len(parsed) == 1
    e = parsed[0]
    assert e["entry_type"] == "article"
    assert e["key"] == "Vaswani2017"
    assert e["title"] == "Attention Is All You Need"
    assert e["authors"] == ["Ashish Vaswani", "Noam Shazeer"]
    assert e["year"] == 2017


def test_parse_bibtex_quoted_and_nested_braces():
    src = '''@article{smith2019,
      title = "A {Nested} Title",
      author = "Smith, Jane and Doe, John",
      year = {2019}
    }'''
    parsed = parse_bibtex(src)
    assert parsed[0]["title"] == "A Nested Title"
    assert parsed[0]["authors"] == ["Smith, Jane", "Doe, John"]
    assert parsed[0]["year"] == 2019


def test_parse_bibtex_ignores_comment_and_malformed():
    src = "@comment{ignore me}\n@article{ok2021, title={T}, year={2021}}\nrandom text"
    parsed = parse_bibtex(src)
    assert len(parsed) == 1
    assert parsed[0]["key"] == "ok2021"


def test_empty_inputs():
    assert papers_to_bibtex([]) == ""
    assert parse_bibtex("") == []
