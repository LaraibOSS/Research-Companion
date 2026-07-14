"""LaTeX cite-key extraction and resolution against a .bib."""
from research_companion.interop.latex import extract_cite_keys, resolve_tex_citations

TEX = r"""
\section{Intro}
As shown by \citet{vaswani2017}, attention works. See also
\citep[e.g.,][p. 3]{devlin2019, brown2020}.
% \cite{commented2000} should be ignored
Multiple \cite{vaswani2017} reuse is de-duplicated.
"""

BIB = r"""
@article{vaswani2017, title={Attention}, author={Vaswani, A}, year={2017}}
@article{devlin2019, title={BERT}, author={Devlin, J}, year={2019}}
@article{unused1999, title={Old}, year={1999}}
"""


def test_extract_cite_keys_dedup_and_options():
    keys = extract_cite_keys(TEX)
    assert keys == ["vaswani2017", "devlin2019", "brown2020"]


def test_extract_ignores_comments():
    assert "commented2000" not in extract_cite_keys(TEX)


def test_resolve_reports_missing_and_unused():
    res = resolve_tex_citations(TEX, BIB)
    assert res["resolved"] == ["vaswani2017", "devlin2019"]
    assert res["missing"] == ["brown2020"]
    assert res["unused"] == ["unused1999"]
    assert res["coverage"] == "2 of 3 cited keys resolved"


def test_empty_inputs():
    assert extract_cite_keys("") == []
    res = resolve_tex_citations("", "")
    assert res["cited_keys"] == [] and res["resolved"] == []
