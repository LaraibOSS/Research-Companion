from research_companion import fetch, store


def test_parse_pubmed_input_ids():
    assert fetch.parse_pubmed_id("pmid:30449619") == ("pmid", "30449619")
    assert fetch.parse_pubmed_id("PMC6289601") == ("pmcid", "PMC6289601")
    assert fetch.parse_pubmed_id("https://pubmed.ncbi.nlm.nih.gov/30449619/") == ("pmid", "30449619")
    assert fetch.parse_pubmed_id("2401.00001") is None


def test_add_pubmed_saves_metadata_and_fulltext(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "papers_dir", lambda: tmp_path)
    rec = {"title": "CRISPR screens", "authors": ["Shifrut E"], "year": 2018,
           "doi": "10.1/x", "arxiv_id": None, "pmid": "30449619", "pmcid": "PMC6289601"}
    meta = fetch.add_pubmed("pmid:30449619",
                            resolve=lambda ident: rec,
                            fetch_text=lambda pmcid: "Methods\nWe did things.")
    assert meta.paper_id == "pmid:30449619"
    assert meta.pmid == "30449619" and meta.pmcid == "PMC6289601"
    assert meta.full_text_available is True
    assert store.load_text("pmid:30449619") == "Methods\nWe did things."


def test_add_pubmed_abstract_only_when_no_fulltext(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "papers_dir", lambda: tmp_path)
    rec = {"title": "T", "authors": [], "year": 2020, "doi": None,
           "arxiv_id": None, "pmid": "111", "pmcid": None}
    meta = fetch.add_pubmed("pmid:111", resolve=lambda ident: rec, fetch_text=lambda pmcid: None)
    assert meta.full_text_available is False


def test_add_pubmed_pmid_idempotent_skips_resolve(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "papers_dir", lambda: tmp_path)
    rec = {"title": "T", "authors": [], "year": 2020, "doi": None,
           "arxiv_id": None, "pmid": "30449619", "pmcid": None}
    fetch.add_pubmed("pmid:30449619", resolve=lambda ident: rec, fetch_text=lambda p: None)
    # Second add must return the existing paper WITHOUT resolving again.
    def _boom(ident):
        raise AssertionError("resolve must not be called for an already-ingested pmid")
    meta = fetch.add_pubmed("pmid:30449619", resolve=_boom, fetch_text=lambda p: None)
    assert meta.paper_id == "pmid:30449619"
