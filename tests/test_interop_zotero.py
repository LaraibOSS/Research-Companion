"""Zotero local-API import: status, pagination, planning, and the import loop.

No network and no real Zotero: every test drives a fake transport with the
response shapes Zotero's local API serves (the web API's JSON under
/api/users/0/...). The fetch functions are replaced, so no DOI or arXiv add
leaves the machine.
"""
from __future__ import annotations

import pytest

from research_companion import fetch, store
from research_companion.interop import zotero

PDF_BYTES = b"%PDF-1.4\n% zotero test\n"


def _item(key, title, *, item_type="journalArticle", doi=None, extra=None, url=None,
          date="2021-03-04", creators=None):
    data = {"key": key, "itemType": item_type, "title": title, "date": date,
            "creators": creators if creators is not None else [
                {"creatorType": "author", "firstName": "Ada", "lastName": "Lovelace"}]}
    if doi is not None:
        data["DOI"] = doi
    if extra is not None:
        data["extra"] = extra
    if url is not None:
        data["url"] = url
    return {"key": key, "data": data}


class FakeZotero:
    """Answers like Zotero's local API, from in-memory items."""

    def __init__(self, items=None, *, collections=None, children=None, files=None,
                 status=200, raise_exc=None):
        self.items = items or []
        self.collections = collections or {}
        self.children = children or {}
        self.files = files or {}
        self.status = status
        self.raise_exc = raise_exc
        self.calls: list[tuple[str, dict | None]] = []

    def _page(self, rows, params):
        start = int((params or {}).get("start", 0))
        limit = int((params or {}).get("limit", 25))
        return 200, {"Total-Results": str(len(rows))}, rows[start:start + limit]

    def __call__(self, path, params=None):
        self.calls.append((path, params))
        if self.raise_exc is not None:
            raise self.raise_exc
        if self.status != 200:
            return self.status, {}, None
        p = zotero.USER_PREFIX
        if path == f"{p}/collections":
            rows = [{"key": k, "data": {"key": k, "name": v["name"]},
                     "meta": {"numItems": len(v["items"])}}
                    for k, v in self.collections.items()]
            return self._page(rows, params)
        if path == f"{p}/items/top":
            return self._page(self.items, params)
        if path.startswith(f"{p}/collections/") and path.endswith("/items/top"):
            ckey = path.split("/")[-3]
            if ckey not in self.collections:
                return 404, {}, None
            return self._page(self.collections[ckey]["items"], params)
        if path.endswith("/children"):
            key = path.split("/")[-2]
            return 200, {}, self.children.get(key, [])
        if path.endswith("/file"):
            key = path.split("/")[-2]
            if key in self.files:
                return 302, {"Location": self.files[key]}, None
            return 404, {}, None
        return 404, {}, None


def _pdf_child(key, *, href=None):
    child = {"key": key, "data": {"key": key, "itemType": "attachment",
                                  "contentType": "application/pdf",
                                  "linkMode": "imported_file"}}
    if href:
        child["links"] = {"enclosure": {"href": href, "type": "application/pdf"}}
    return child


@pytest.fixture
def no_fetch(monkeypatch):
    """Replace the network adds with recorders that write a paper locally."""
    calls = []

    def fake_arxiv(aid):
        calls.append(("arxiv", aid))
        meta = store.PaperMetadata(paper_id=store.make_arxiv_id(aid), title=f"arXiv {aid}",
                                   authors=[])
        meta.save()
        store.save_pdf(meta.paper_id, PDF_BYTES + aid.encode())
        return meta

    def fake_doi(doi):
        calls.append(("doi", doi))
        meta = store.PaperMetadata(paper_id=store.make_doi_id(doi), title=f"DOI {doi}",
                                   authors=[])
        meta.save()  # no PDF: the publisher refused
        return meta

    monkeypatch.setattr(fetch, "add_arxiv", fake_arxiv)
    monkeypatch.setattr(fetch, "add_doi", fake_doi)
    return calls


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

class TestCheck:
    def test_ready(self):
        s = zotero.check(FakeZotero())
        assert s["state"] == "ready" and s["ok"] is True

    def test_local_api_off_says_where_to_turn_it_on(self):
        s = zotero.check(FakeZotero(status=403))
        assert s["state"] == "disabled" and s["ok"] is False
        assert "Settings" in s["message"] and "Advanced" in s["message"]
        assert "Allow other applications on this computer to communicate with Zotero" \
            in s["message"]

    def test_not_running(self):
        s = zotero.check(FakeZotero(raise_exc=zotero.ZoteroNotRunning("refused")))
        assert s["state"] == "not_running" and s["ok"] is False
        assert "not running" in s["message"]

    def test_old_zotero_without_local_api(self):
        s = zotero.check(FakeZotero(status=404))
        assert s["state"] == "error"
        assert "Zotero 7" in s["message"]

    def test_default_transport_reports_connection_refused(self, monkeypatch):
        # Nothing listens on port 9 (discard) on a test machine; the real
        # httpx transport must turn the refusal into "not running".
        monkeypatch.setenv("RESEARCH_COMPANION_ZOTERO_URL", "http://127.0.0.1:9")
        s = zotero.check()
        assert s["state"] == "not_running"
        assert s["url"] == "http://127.0.0.1:9"


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

class TestListing:
    def test_items_paginate_past_one_page(self):
        items = [_item(f"K{i:04d}", f"Paper {i}") for i in range(250)]
        fake = FakeZotero(items)
        got = zotero.list_items(get=fake)
        assert len(got) == 250
        starts = [params["start"] for _, params in fake.calls]
        assert starts == [0, 100, 200]

    def test_stops_when_total_reached_on_a_full_page(self):
        items = [_item(f"K{i:04d}", f"Paper {i}") for i in range(200)]
        fake = FakeZotero(items)
        assert len(zotero.list_items(get=fake)) == 200
        # 0, 100 -> 200 == Total-Results: no third, empty request
        assert [p["start"] for _, p in fake.calls] == [0, 100]

    def test_notes_attachments_annotations_are_skipped(self):
        items = [_item("A1", "A paper"),
                 _item("N1", "", item_type="note"),
                 _item("T1", "loose.pdf", item_type="attachment"),
                 _item("H1", "", item_type="annotation"),
                 _item("B1", "A book", item_type="book")]
        got = zotero.list_items(get=FakeZotero(items))
        assert [i["key"] for i in got] == ["A1", "B1"]

    def test_collection_items(self):
        fake = FakeZotero(collections={"COLL1": {"name": "Thesis",
                                                 "items": [_item("A1", "In it")]}})
        got = zotero.list_items("COLL1", get=fake)
        assert [i["key"] for i in got] == ["A1"]
        assert fake.calls[0][0] == f"{zotero.USER_PREFIX}/collections/COLL1/items/top"

    def test_unknown_collection_is_a_plain_error(self):
        with pytest.raises(zotero.ZoteroError, match="could not find collection"):
            zotero.list_items("NOPE", get=FakeZotero())

    def test_collection_key_is_not_a_path(self):
        with pytest.raises(zotero.ZoteroError):
            zotero.list_items("../items", get=FakeZotero())

    def test_local_api_off_while_listing(self):
        with pytest.raises(zotero.ZoteroError, match="Advanced"):
            zotero.list_items(get=FakeZotero(status=403))

    def test_collections(self):
        fake = FakeZotero(collections={"B": {"name": "beta", "items": []},
                                       "A": {"name": "Alpha", "items": [1, 2]}})
        rows = zotero.list_collections(fake)
        assert [r["name"] for r in rows] == ["Alpha", "beta"]
        assert rows[0] == {"key": "A", "name": "Alpha", "parent": None, "items": 2}


class TestAttachment:
    def test_enclosure_file_url(self, tmp_path):
        pdf = tmp_path / "paper one.pdf"
        pdf.write_bytes(PDF_BYTES)
        fake = FakeZotero(children={"A1": [_pdf_child("ATT1", href=pdf.as_uri())]})
        assert zotero.find_pdf_attachment("A1", fake) == pdf

    def test_file_endpoint_redirect(self, tmp_path):
        pdf = tmp_path / "p.pdf"
        pdf.write_bytes(PDF_BYTES)
        fake = FakeZotero(children={"A1": [_pdf_child("ATT1")]},
                          files={"ATT1": pdf.as_uri()})
        assert zotero.find_pdf_attachment("A1", fake) == pdf

    def test_unresolvable_file_is_no_pdf(self, tmp_path):
        missing = (tmp_path / "gone.pdf").as_uri()
        fake = FakeZotero(children={"A1": [_pdf_child("ATT1", href=missing),
                                           _pdf_child("ATT2")]},
                          files={"ATT2": "https://example.org/remote.pdf"})
        assert zotero.find_pdf_attachment("A1", fake) is None

    def test_non_pdf_attachment_ignored(self, tmp_path):
        f = tmp_path / "snap.html"
        f.write_text("x")
        child = _pdf_child("ATT1", href=f.as_uri())
        child["data"]["contentType"] = "text/html"
        assert zotero.find_pdf_attachment("A1", FakeZotero(children={"A1": [child]})) is None


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------

class TestTarget:
    def test_arxiv_from_extra_beats_doi_and_pdf(self, tmp_path):
        t = zotero.to_import_target(
            _item("A", "T", doi="10.1000/xyz", extra="arXiv: 2101.00001v2\nother"),
            pdf_path=tmp_path / "p.pdf")
        assert (t.method, t.arxiv_id, t.doi) == ("arxiv", "2101.00001", "10.1000/xyz")

    def test_arxiv_from_10_48550_doi(self):
        t = zotero.to_import_target(_item("A", "T", doi="10.48550/arXiv.2305.12345"))
        assert (t.method, t.arxiv_id) == ("arxiv", "2305.12345")

    def test_arxiv_from_url(self):
        t = zotero.to_import_target(_item("A", "T", url="https://arxiv.org/abs/1706.03762v5"))
        assert (t.method, t.arxiv_id) == ("arxiv", "1706.03762")

    def test_doi_beats_pdf(self, tmp_path):
        t = zotero.to_import_target(_item("A", "T", doi="https://doi.org/10.1145/3.4"),
                                    pdf_path=tmp_path / "p.pdf")
        assert (t.method, t.doi) == ("doi", "10.1145/3.4")
        assert t.pdf_path  # kept: used if the DOI add ends without a PDF

    def test_pdf_beats_metadata(self, tmp_path):
        t = zotero.to_import_target(_item("A", "T"), pdf_path=tmp_path / "p.pdf")
        assert t.method == "pdf"

    def test_metadata_only(self):
        t = zotero.to_import_target(_item("A", "  A   Title  ", date="Spring 2019"))
        assert t.method == "metadata"
        assert t.title == "A Title"
        assert t.year == 2019
        assert t.authors == ["Ada Lovelace"]

    def test_creators_single_field_names_and_editors_dropped(self):
        t = zotero.to_import_target(_item("A", "T", creators=[
            {"creatorType": "author", "name": "OpenAI"},
            {"creatorType": "editor", "firstName": "E", "lastName": "Ditor"},
            {"creatorType": "author", "firstName": "", "lastName": "Solo"}]))
        assert t.authors == ["OpenAI", "Solo"]


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

class TestImport:
    def test_each_method_adds(self, tmp_path, no_fetch):
        pdf = tmp_path / "local.pdf"
        pdf.write_bytes(PDF_BYTES + b"local")
        items = [_item("A1", "Via arXiv", extra="arXiv: 2101.00001"),
                 _item("D1", "Via DOI", doi="10.1000/abc"),
                 _item("P1", "Via the Zotero PDF"),
                 _item("M1", "Only metadata")]
        fake = FakeZotero(children={"P1": [_pdf_child("ATT", href=pdf.as_uri())]})
        rep = zotero.import_items(items, dry_run=False, get=fake)
        assert rep["total"] == 4
        assert rep["added"] == 3
        assert rep["metadata_only"] == 1
        assert rep["no_pdf"] == 1          # the DOI add got no PDF
        assert rep["failed"] == []
        assert ("arxiv", "2101.00001") in no_fetch and ("doi", "10.1000/abc") in no_fetch
        meta = store.PaperMetadata.load("zotero:M1")
        assert meta.title == "Only metadata" and meta.parse_source == "zotero"
        local = [p for p in store.list_papers() if p.paper_id.startswith("local:")]
        assert len(local) == 1 and local[0].title == "Via the Zotero PDF"

    def test_doi_add_without_pdf_takes_the_zotero_pdf(self, tmp_path, no_fetch):
        pdf = tmp_path / "paywalled.pdf"
        pdf.write_bytes(PDF_BYTES + b"pw")
        fake = FakeZotero(children={"D1": [_pdf_child("ATT", href=pdf.as_uri())]})
        rep = zotero.import_items([_item("D1", "Paywalled", doi="10.1000/pw")],
                                  dry_run=False, get=fake)
        assert rep["added"] == 1 and rep["no_pdf"] == 0
        assert store.pdf_path("doi:10.1000/pw").read_bytes() == PDF_BYTES + b"pw"

    def test_dedupes_against_existing_library_paper(self, no_fetch):
        store.PaperMetadata(paper_id="arxiv:2101.00001", title="Existing",
                            authors=[]).save()
        store.PaperMetadata(paper_id="local:abc",
                            title="A Long Enough Distinctive Title For Matching",
                            authors=[]).save()
        items = [_item("A1", "Something", doi="10.48550/arXiv.2101.00001"),
                 _item("M1", "A Long Enough Distinctive Title For Matching")]
        rep = zotero.import_items(items, dry_run=False, get=FakeZotero())
        assert rep["already_in_library"] == 2
        assert rep["added"] == 0 and rep["metadata_only"] == 0
        assert no_fetch == []
        assert {r["paper_id"] for r in rep["items"]} == {"arxiv:2101.00001", "local:abc"}

    def test_reimport_is_idempotent(self, no_fetch):
        items = [_item("M1", "Only metadata")]
        zotero.import_items(items, dry_run=False, get=FakeZotero())
        rep = zotero.import_items(items, dry_run=False, get=FakeZotero())
        assert rep["already_in_library"] == 1 and rep["metadata_only"] == 0

    def test_failing_item_does_not_stop_the_rest(self, monkeypatch, no_fetch):
        def boom(doi):
            raise fetch.FetchError("Crossref API returned no entry for DOI '10.1000/bad'")
        monkeypatch.setattr(fetch, "add_doi", boom)
        items = [_item("D1", "Bad DOI", doi="10.1000/bad"),
                 _item("A1", "Good", extra="arXiv: 2101.00002")]
        rep = zotero.import_items(items, dry_run=False, get=FakeZotero())
        assert rep["failed"] == [{"title": "Bad DOI",
                                  "reason": "Crossref API returned no entry for DOI '10.1000/bad'"}]
        assert rep["added"] == 1
        assert store.PaperMetadata.load("arxiv:2101.00002") is not None

    def test_dry_run_writes_nothing(self, tmp_path, no_fetch):
        pdf = tmp_path / "local.pdf"
        pdf.write_bytes(PDF_BYTES)
        items = [_item("A1", "Via arXiv", extra="arXiv: 2101.00001"),
                 _item("D1", "Via DOI", doi="10.1000/abc"),
                 _item("P1", "Via PDF"),
                 _item("M1", "Only metadata")]
        fake = FakeZotero(children={"P1": [_pdf_child("ATT", href=pdf.as_uri())]})
        rep = zotero.import_items(items, dry_run=True, get=fake)
        assert rep["dry_run"] is True
        assert rep["added"] == 3 and rep["metadata_only"] == 1
        assert [r["outcome"] for r in rep["items"]] == [
            "would_add", "would_add", "would_add", "would_add_metadata_only"]
        assert [r["method"] for r in rep["items"]] == ["arxiv", "doi", "pdf", "metadata"]
        assert store.list_papers() == []
        assert no_fetch == []

    def test_never_writes_to_zotero(self, no_fetch):
        # The transport has no verb: every request is a GET by construction.
        # Pin that only read paths were asked for.
        fake = FakeZotero()
        zotero.import_items([_item("M1", "x")], dry_run=False, get=fake)
        assert all(path.startswith(zotero.USER_PREFIX) for path, _ in fake.calls)

    def test_progress_callback_errors_are_ignored(self, no_fetch):
        def bad(*_a):
            raise RuntimeError("display broke")
        rep = zotero.import_items([_item("M1", "x")], dry_run=False, get=FakeZotero(),
                                  progress=bad)
        assert rep["metadata_only"] == 1 and rep["failed"] == []
