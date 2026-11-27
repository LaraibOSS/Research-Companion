"""`research-companion import-zotero`: wording, --dry-run, --json, failures.

Drives cli.main against a fake Zotero (the module's default transport is
replaced), so nothing contacts a real Zotero or the network.
"""
from __future__ import annotations

import json

import pytest

from research_companion import cli, fetch, store
from research_companion.interop import zotero
from tests.test_interop_zotero import FakeZotero, _item


@pytest.fixture
def fake_zotero(monkeypatch):
    fake = FakeZotero(
        [_item("A1", "Attention Is All You Need", extra="arXiv: 1706.03762"),
         _item("M1", "Notes on a Workshop Talk")],
        collections={"COLL1": {"name": "Thesis", "items": [_item("M2", "Only here")]}})
    monkeypatch.setattr(zotero, "http_get", fake)

    def fake_arxiv(aid):
        meta = store.PaperMetadata(paper_id=store.make_arxiv_id(aid), title="Attention",
                                   authors=[])
        meta.save()
        store.save_pdf(meta.paper_id, b"%PDF-1.4 x")
        return meta

    monkeypatch.setattr(fetch, "add_arxiv", fake_arxiv)
    return fake


def test_dry_run_prints_plan_and_writes_nothing(fake_zotero, capsys):
    rc = cli.main(["import-zotero", "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "would add" in out and "by arXiv id" in out
    assert "details only" in out
    assert "Dry run: nothing was added." in out
    assert "1 would be added, 1 would be added as details only" in out
    assert store.list_papers() == []


def test_import_adds_and_summarises(fake_zotero, capsys):
    rc = cli.main(["import-zotero"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Of 2 items: 1 added, 1 added as details only, 0 already in your library, " \
           "0 could not be added." in out
    assert "Nothing was analysed yet" in out
    assert {p.paper_id for p in store.list_papers()} == {"arxiv:1706.03762", "zotero:M1"}


def test_json_output_is_clean_json(fake_zotero, monkeypatch, capsys):
    def noisy_arxiv(aid):
        print("warning: could not download PDF")  # what fetch prints on a miss
        meta = store.PaperMetadata(paper_id=store.make_arxiv_id(aid), title="x", authors=[])
        meta.save()
        return meta
    monkeypatch.setattr(fetch, "add_arxiv", noisy_arxiv)
    rc = cli.main(["import-zotero", "--json"])
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert rc == 0
    rep = data["report"]
    assert (rep["total"], rep["added"], rep["metadata_only"], rep["no_pdf"]) == (2, 1, 1, 1)
    assert "warning: could not download PDF" in captured.err


def test_collection_option(fake_zotero, capsys):
    rc = cli.main(["import-zotero", "--collection", "COLL1", "--json"])
    rep = json.loads(capsys.readouterr().out)["report"]
    assert rc == 0 and rep["total"] == 1 and rep["items"][0]["key"] == "M2"


def test_list_collections(fake_zotero, capsys):
    assert cli.main(["import-zotero", "--list-collections"]) == 0
    out = capsys.readouterr().out
    assert "COLL1  Thesis  (1 items)" in out
    assert store.list_papers() == []


def test_local_api_off_explains_where_to_enable(monkeypatch, capsys):
    monkeypatch.setattr(zotero, "http_get", FakeZotero(status=403))
    assert cli.main(["import-zotero", "--dry-run"]) == 1
    err = capsys.readouterr().err
    assert "Allow other applications on this computer to communicate with Zotero" in err


def test_not_running(monkeypatch, capsys):
    monkeypatch.setattr(zotero, "http_get",
                        FakeZotero(raise_exc=zotero.ZoteroNotRunning("refused")))
    assert cli.main(["import-zotero"]) == 1
    assert "Zotero is not running" in capsys.readouterr().err


def test_status_failure_with_json(monkeypatch, capsys):
    monkeypatch.setattr(zotero, "http_get", FakeZotero(status=403))
    assert cli.main(["import-zotero", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["status"]["state"] == "disabled"


def test_failed_item_is_named_with_its_reason(fake_zotero, monkeypatch, capsys):
    def boom(aid):
        raise fetch.FetchError(f"arXiv API returned no entry for id {aid!r}")
    monkeypatch.setattr(fetch, "add_arxiv", boom)
    rc = cli.main(["import-zotero"])
    out = capsys.readouterr().out
    assert rc == 0  # one of two failed; the other was added
    assert "could not add" in out and "arXiv API returned no entry" in out
    assert "1 could not be added." in out


def test_no_active_research(fake_zotero, capsys):
    reg = store.load_registry()
    reg["active"] = None
    store.save_registry(reg)
    store._reset_workspace_caches()
    assert cli.main(["import-zotero"]) == 1
    assert "no active research" in capsys.readouterr().err
