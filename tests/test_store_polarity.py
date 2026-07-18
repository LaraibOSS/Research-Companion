from research_companion import store


def test_save_then_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "papers_dir", lambda: tmp_path)
    mapping = {"Lewis et al. 2020": {"polarity": "based_on", "verified": True}}
    store.save_citation_polarity("arxiv:1", mapping)
    assert store.load_citation_polarity("arxiv:1") == mapping


def test_load_absent_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "papers_dir", lambda: tmp_path)
    assert store.load_citation_polarity("arxiv:missing") == {}


def test_load_corrupt_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "papers_dir", lambda: tmp_path)
    d = store.paper_dir("arxiv:2")
    (d / "citation_polarity.json").write_text("{not json", encoding="utf-8")
    assert store.load_citation_polarity("arxiv:2") == {}
