"""Retraction is a different fact from existence.

A retracted paper exists, so it is not "unverified"; it may be cited with the
right title and authors, so it is not "suspect". It gets its own field, and its
own denominator: only some catalogues record retractions, so a reference
matched elsewhere was not checked for this at all.
"""
from __future__ import annotations

import json

from research_companion.refcheck.retrieval import parse_crossref_item, parse_openalex_item
from research_companion.refcheck.validate import (
    BibReport,
    Reference,
    validate_bibliography,
    validate_reference,
)

_WAKEFIELD = {
    "title": ["Ileal-lymphoid-nodular hyperplasia, non-specific colitis, and pervasive "
              "developmental disorder in children"],
    "author": [{"given": "AJ", "family": "Wakefield"}],
    "issued": {"date-parts": [[1998]]},
    "DOI": "10.1016/S0140-6736(97)11096-0",
    "updated-by": [
        {"DOI": "10.1016/x", "type": "correction", "source": "publisher"},
        {"DOI": "10.1016/y", "type": "retraction", "source": "retraction-watch"},
    ],
}


def test_crossref_retraction_is_read_and_a_correction_is_not_one():
    rec = parse_crossref_item(_WAKEFIELD)
    assert rec["notices"] == ["retraction"]
    assert rec["retraction_checked"] is True

    corrected_only = dict(_WAKEFIELD, **{"updated-by": [{"type": "correction"}]})
    assert parse_crossref_item(corrected_only)["notices"] == []


def test_crossref_expression_of_concern_and_spelling_variants():
    for raw in ("expression_of_concern", "expression-of-concern", "Expression Of Concern"):
        item = dict(_WAKEFIELD, **{"updated-by": [{"type": raw}]})
        assert parse_crossref_item(item)["notices"] == ["expression_of_concern"]
    both = dict(_WAKEFIELD, **{"updated-by": [{"type": "expression_of_concern"},
                                              {"type": "retraction"}]})
    assert parse_crossref_item(both)["notices"] == ["retraction", "expression_of_concern"]


def test_a_clean_crossref_record_is_checked_and_clear():
    item = {k: v for k, v in _WAKEFIELD.items() if k != "updated-by"}
    rec = parse_crossref_item(item)
    assert rec["notices"] == [] and rec["retraction_checked"] is True


def test_openalex_flag_and_its_absence():
    base = {"title": "A paper", "authorships": [], "publication_year": 2020}
    assert parse_openalex_item(dict(base, is_retracted=True))["notices"] == ["retraction"]
    clear = parse_openalex_item(dict(base, is_retracted=False))
    assert clear["notices"] == [] and clear["retraction_checked"] is True
    # No flag on the record: nothing was established, so it is not "checked".
    assert parse_openalex_item(base)["retraction_checked"] is False


def test_a_retracted_reference_keeps_its_existence_verdict():
    rec = parse_crossref_item(_WAKEFIELD)
    line = ("Wakefield AJ. Ileal-lymphoid-nodular hyperplasia, non-specific colitis, and "
            "pervasive developmental disorder in children. Lancet, 1998.")
    verdict = validate_reference(Reference(title=line, raw=line), lambda r: rec)
    assert verdict.status == "verified"
    assert verdict.notices == ["retraction"] and verdict.retraction_checked is True


def test_a_match_from_a_catalogue_without_retraction_data_is_not_checked():
    arxiv_record = {"title": "Attention Is All You Need", "authors": ["Ashish Vaswani"],
                    "year": 2017, "doi": None, "arxiv_id": "1706.03762"}
    line = "Vaswani et al. Attention is all you need. 2017."
    verdict = validate_reference(Reference(title=line, raw=line), lambda r: arxiv_record)
    assert verdict.status == "verified"
    assert verdict.notices == [] and verdict.retraction_checked is False


def test_counts_state_the_denominator():
    retracted = parse_crossref_item(_WAKEFIELD)
    clean = parse_crossref_item({"title": ["Deep Residual Learning for Image Recognition"],
                                 "author": [{"given": "Kaiming", "family": "He"}],
                                 "DOI": "10.1109/cvpr.2016.90"})
    arxiv = {"title": "Attention Is All You Need", "authors": ["Ashish Vaswani"]}
    refs = [
        Reference(title="Wakefield. Ileal-lymphoid-nodular hyperplasia, non-specific colitis, "
                        "and pervasive developmental disorder in children."),
        Reference(title="He. Deep residual learning for image recognition."),
        Reference(title="Vaswani. Attention is all you need."),
        Reference(title="Nobody. A paper that no catalogue has ever heard of."),
    ]
    table = dict(zip([r.title for r in refs], [retracted, clean, arxiv, None]))
    for r in refs:
        r.raw = r.title
    report = validate_bibliography(refs, lambda r: table[r.title])
    assert isinstance(report, BibReport)
    assert report.retraction_counts() == {
        "checked": 2, "flagged": 1, "retracted": 1, "not_checked": 2}


def test_cli_reports_retraction_with_its_denominator(isolated_papergraph_dir, monkeypatch, capsys):
    from research_companion import cli, store
    from research_companion.refcheck import retrieval

    pid = "local:retract01"
    store.PaperMetadata(paper_id=pid, title="Draft", authors=[]).save()
    store.save_text(pid, "Body.\n\nReferences\n\n"
                    "[1] Wakefield AJ. Ileal-lymphoid-nodular hyperplasia, non-specific colitis, "
                    "and pervasive developmental disorder in children. Lancet, 1998.\n"
                    "[2] Vaswani A. Attention is all you need. NeurIPS, 2017.\n")
    rec = parse_crossref_item(_WAKEFIELD)
    arxiv = {"title": "Attention Is All You Need", "authors": ["Ashish Vaswani"], "year": 2017}
    monkeypatch.setattr(
        retrieval, "default_lookup",
        lambda **kw: (lambda ref: rec if "Wakefield" in ref.raw else arxiv))
    monkeypatch.setattr("research_companion.refcheck.default_lookup",
                        retrieval.default_lookup, raising=False)

    assert cli.main(["refcheck", pid, "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["retraction"] == {"checked": 1, "flagged": 1, "retracted": 1, "not_checked": 1}
    by_title = {r["title"][:9]: r for r in payload["references"]}
    assert by_title["Wakefield"]["notices"] == ["retraction"]

    assert cli.main(["refcheck", pid]) == 0
    out = capsys.readouterr().out
    assert "RETRACTED" in out
    assert "1 of 1 checked" in out and "NOT checked for" in out
