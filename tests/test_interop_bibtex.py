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


def test_bibtex_escapes_latex_specials():
    """% & _ # $ in a title must be backslash-escaped or they break LaTeX
    compilation (an unescaped % comments out the rest of the field)."""
    rec = {
        "title": "50% Faster Training & Fine_Tuning #1 costs $5",
        "authors": ["A"],
        "year": 2021,
    }
    out = papers_to_bibtex([rec])
    assert r"50\% Faster Training \& Fine\_Tuning \#1 costs \$5" in out
    # Every special must be *preceded* by a backslash — no bare occurrence
    # (checked positionally rather than by naive substring, since e.g. "#1"
    # is a substring of the correctly-escaped "\#1").
    for raw in ("%", "&", "_", "#", "$"):
        idx = out.find(raw)
        while idx != -1:
            assert out[idx - 1] == "\\", f"unescaped {raw!r} at {idx}: ...{out[idx-5:idx+5]}..."
            idx = out.find(raw, idx + 1)


def test_bibtex_escapes_backslash_tilde_caret():
    rec = {"title": r"A~B^C\D", "authors": ["A"], "year": 2022}
    out = papers_to_bibtex([rec])
    assert r"A\textasciitilde{}B\textasciicircum{}C\textbackslash{}D" in out


def test_bibtex_url_and_doi_are_emitted_raw_unescaped():
    """A URL/DOI legitimately contains ~ _ % # & — LaTeX-escaping them (as if
    they were prose) corrupts the value; \\url{}/\\path{} need the raw bytes.
    Meanwhile the title (prose) must still be escaped as before."""
    rec = {
        "title": "50% Faster Training & Fine_Tuning",
        "authors": ["A"],
        "year": 2021,
        "url": "https://example.org/~smith/p%20df#sec",
        "doi": "10.1000/abc_def&x",
    }
    out = papers_to_bibtex([rec])

    # Raw substrings survive intact in url/doi (extract each field's own line
    # so the check can't be satisfied by coincidental substrings elsewhere).
    url_line = next(line for line in out.splitlines() if line.strip().startswith("url ="))
    doi_line = next(line for line in out.splitlines() if line.strip().startswith("doi ="))
    assert "https://example.org/~smith/p%20df#sec" in url_line
    assert "10.1000/abc_def&x" in doi_line

    # None of the LaTeX-escape replacements leaked into the url/doi fields.
    for line in (url_line, doi_line):
        assert r"\textasciitilde" not in line
        assert r"\%" not in line
        assert r"\_" not in line
        assert r"\&" not in line
        assert r"\#" not in line

    # Title (prose) is still escaped as before.
    assert r"50\% Faster Training \& Fine\_Tuning" in out
