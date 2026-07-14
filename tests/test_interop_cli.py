"""CLI-level tests for the interoperability commands (export/import/cite-tex)."""
import argparse
import io
import json
from contextlib import redirect_stdout

from research_companion import store
from research_companion.cli import _cmd_cite_tex, _cmd_export_bib, _cmd_import_bib


def test_export_bib_to_stdout():
    store.PaperMetadata(paper_id="arxiv:1", title="Paper One",
                        authors=["Jane Doe"], year=2020).save()
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = _cmd_export_bib(argparse.Namespace(format="bibtex", output=None))
    out = buf.getvalue()
    assert rc == 0
    assert "@article{Doe2020," in out
    assert "Paper One" in out


def test_export_ris_to_file(tmp_path):
    store.PaperMetadata(paper_id="arxiv:2", title="P2",
                        authors=["Alan Turing"], year=2019).save()
    dest = tmp_path / "library.ris"
    rc = _cmd_export_bib(argparse.Namespace(format="ris", output=str(dest)))
    assert rc == 0
    assert "TY  - JOUR" in dest.read_text(encoding="utf-8")


def test_import_bib_adds_metadata_only_papers(tmp_path):
    bib = tmp_path / "in.bib"
    bib.write_text('@article{smith2019, title={Imported Work}, '
                   'author={Smith, Jane}, year={2019}}', encoding="utf-8")
    rc = _cmd_import_bib(argparse.Namespace(file=str(bib)))
    assert rc == 0
    ids = [p.paper_id for p in store.list_papers()]
    assert "bibtex:smith2019" in ids
    meta = store.PaperMetadata.load("bibtex:smith2019")
    assert meta.title == "Imported Work"
    assert meta.year == 2019
    assert meta.parse_source == "bibtex"


def test_import_bib_skips_existing(tmp_path):
    bib = tmp_path / "in.bib"
    bib.write_text("@article{dup2020, title={T}, year={2020}}", encoding="utf-8")
    assert _cmd_import_bib(argparse.Namespace(file=str(bib))) == 0
    # second import should not duplicate
    assert _cmd_import_bib(argparse.Namespace(file=str(bib))) == 0
    ids = [p.paper_id for p in store.list_papers()]
    assert ids.count("bibtex:dup2020") == 1


def test_cite_tex_resolves_against_bib(tmp_path):
    tex = tmp_path / "draft.tex"
    tex.write_text(r"Background \citep{smith2019, missing2000}.", encoding="utf-8")
    bib = tmp_path / "refs.bib"
    bib.write_text("@article{smith2019, title={T}, year={2019}}", encoding="utf-8")
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = _cmd_cite_tex(argparse.Namespace(tex_file=str(tex), bib=str(bib), json=True))
    assert rc == 0
    res = json.loads(buf.getvalue())
    assert res["resolved"] == ["smith2019"]
    assert res["missing"] == ["missing2000"]
