from research_companion import graph, store
from research_companion.store import PaperMetadata


def _seed(tmp_path, monkeypatch, paper_id, title, related_work, prompt_sha):
    monkeypatch.setattr(store, "papers_dir", lambda: tmp_path)
    PaperMetadata(paper_id=paper_id, title=title, authors=[]).save()
    store.save_extraction(paper_id, {
        "concepts": [], "methods": [], "datasets": [], "claims": [], "results": [],
        "related_work": related_work, "paper_meta": {"title": title}}, prompt_sha=prompt_sha)


def test_cites_edge_gets_polarity_from_sidecar(tmp_path, monkeypatch):
    from research_companion.prompts import extraction_prompt_sha256
    sha = extraction_prompt_sha256()
    _seed(tmp_path, monkeypatch, "p:a", "Alpha Method", ["Beta Work"], sha)
    _seed(tmp_path, monkeypatch, "p:b", "Beta Work", [], sha)
    store.save_citation_polarity("p:a", {"Beta Work": {"polarity": "contrast", "verified": True}})
    G = graph.build_graph()
    assert G["p:a"]["p:b"]["relation"] == "cites"
    assert G["p:a"]["p:b"]["polarity"] == "contrast"


def test_cites_edge_untyped_without_sidecar(tmp_path, monkeypatch):
    from research_companion.prompts import extraction_prompt_sha256
    sha = extraction_prompt_sha256()
    _seed(tmp_path, monkeypatch, "p:a", "Alpha Method", ["Beta Work"], sha)
    _seed(tmp_path, monkeypatch, "p:b", "Beta Work", [], sha)
    G = graph.build_graph()
    assert G["p:a"]["p:b"]["relation"] == "cites"
    assert "polarity" not in G["p:a"]["p:b"]   # degradation: identical to today


def test_cites_edge_gets_evidence_when_verified(tmp_path, monkeypatch):
    from research_companion.prompts import extraction_prompt_sha256
    sha = extraction_prompt_sha256()
    _seed(tmp_path, monkeypatch, "p:a", "Alpha Method", ["Beta Work"], sha)
    _seed(tmp_path, monkeypatch, "p:b", "Beta Work", [], sha)
    store.save_citation_polarity("p:a", {"Beta Work": {
        "polarity": "contrast", "verified": True, "evidence_quote": "some quote"}})
    G = graph.build_graph()
    assert G["p:a"]["p:b"]["evidence"] == "some quote"


def test_cites_edge_no_evidence_when_unverified(tmp_path, monkeypatch):
    from research_companion.prompts import extraction_prompt_sha256
    sha = extraction_prompt_sha256()
    _seed(tmp_path, monkeypatch, "p:a", "Alpha Method", ["Beta Work"], sha)
    _seed(tmp_path, monkeypatch, "p:b", "Beta Work", [], sha)
    store.save_citation_polarity("p:a", {"Beta Work": {
        "polarity": "contrast", "verified": False, "evidence_quote": "some quote"}})
    G = graph.build_graph()
    assert "evidence" not in G["p:a"]["p:b"]
