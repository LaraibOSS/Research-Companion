"""Tests for research_companion.store."""
from __future__ import annotations

import pytest

from research_companion import store


def test_arxiv_id_normalisation():
    assert store.make_arxiv_id("2410.05779") == "arxiv:2410.05779"
    assert store.make_arxiv_id("2410.05779v3") == "arxiv:2410.05779"
    assert store.make_arxiv_id("  2410.05779  ") == "arxiv:2410.05779"


def test_local_id_is_content_hash(fake_pdf_bytes: bytes):
    a = store.make_local_id(fake_pdf_bytes)
    b = store.make_local_id(fake_pdf_bytes)
    assert a == b
    assert a.startswith("local:") and len(a.split(":")[1]) == 12

    different = store.make_local_id(fake_pdf_bytes + b"x")
    assert different != a


def test_papergraph_dir_uses_env(isolated_papergraph_dir):
    assert store.papergraph_dir() == isolated_papergraph_dir
    assert store.papers_dir().exists()
    assert store.papers_dir().parent == isolated_papergraph_dir


def test_paper_dir_filesystem_safe():
    d = store.paper_dir("arxiv:2410.05779")
    assert d.name == "arxiv__2410_05779"
    d2 = store.paper_dir("local:abc123def456")
    assert d2.name == "local__abc123def456"


def test_metadata_save_load_roundtrip():
    meta = store.PaperMetadata(
        paper_id="arxiv:2410.05779",
        title="GraphRAG: foo bar baz",
        authors=["Alice", "Bob"],
        year=2024,
        abstract="An abstract.",
        source_url="https://arxiv.org/abs/2410.05779",
        added_at="2026-04-26T10:00:00",
    )
    meta.save()
    loaded = store.PaperMetadata.load("arxiv:2410.05779")
    assert loaded is not None
    assert loaded.title == "GraphRAG: foo bar baz"
    assert loaded.authors == ["Alice", "Bob"]
    assert loaded.year == 2024


def test_metadata_load_missing_returns_none():
    assert store.PaperMetadata.load("arxiv:9999.99999") is None


def test_metadata_parse_provenance_defaults():
    meta = store.PaperMetadata(
        paper_id="arxiv:2410.05780",
        title="Untouched provenance",
        authors=["Carol"],
    )
    assert meta.parse_source == ""
    assert meta.ocr_used is False


def test_metadata_parse_provenance_roundtrip():
    meta = store.PaperMetadata(
        paper_id="arxiv:2410.05781",
        title="OCR provenance",
        authors=["Dave"],
        parse_source="docling+ocr",
        ocr_used=True,
    )
    meta.save()
    loaded = store.PaperMetadata.load("arxiv:2410.05781")
    assert loaded is not None
    assert loaded.parse_source == "docling+ocr"
    assert loaded.ocr_used is True


def test_metadata_load_backward_compat_without_provenance_fields(isolated_papergraph_dir):
    """Old metadata.json files written before parse_source/ocr_used existed
    must still load, defaulting the new fields."""
    import json

    paper_id = "arxiv:2410.05782"
    d = store.paper_dir(paper_id)
    d.mkdir(parents=True, exist_ok=True)
    old_data = {
        "paper_id": paper_id,
        "title": "Legacy paper",
        "authors": ["Eve"],
        "year": 2020,
        "abstract": "",
        "source_url": "",
        "arxiv_categories": [],
        "added_at": "2026-01-01T00:00:00",
    }
    (d / "metadata.json").write_text(json.dumps(old_data), encoding="utf-8")

    loaded = store.PaperMetadata.load(paper_id)
    assert loaded is not None
    assert loaded.title == "Legacy paper"
    assert loaded.parse_source == ""
    assert loaded.ocr_used is False


def test_extraction_cache_key_on_prompt_sha(sample_extraction: dict):
    paper_id = "arxiv:2410.05779"
    store.PaperMetadata(
        paper_id=paper_id, title="t", authors=[], added_at="2026-01-01",
    ).save()
    store.save_extraction(paper_id, sample_extraction, prompt_sha="abc123")

    # Same SHA -> hit.
    assert store.load_extraction(paper_id, prompt_sha="abc123") == sample_extraction
    # Different SHA -> miss (cache invalidated by prompt change).
    assert store.load_extraction(paper_id, prompt_sha="def456") is None


def test_load_extraction_corrupt_json_returns_none():
    """A corrupt/legacy extraction.json must be treated as a cache miss, not raise.

    build_graph() calls load_extraction() for every paper in the workspace; a
    single malformed file (e.g. from a pre-0.4 migrated 'Main') would otherwise
    throw and abort the whole graph stage, failing an unrelated draft's ingest.
    """
    paper_id = "arxiv:2410.05779"
    d = store.paper_dir(paper_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "extraction.json").write_text("not valid json }{", encoding="utf-8")
    assert store.load_extraction(paper_id, prompt_sha="abc123") is None


def test_save_and_load_simplified_roundtrip():
    payload = {"provider": "anthropic", "model": "m", "created_at": "2026-07-22T00:00:00Z",
               "groups": [{"title": "Key claims", "bullets": [{"text": "t", "section_id": "s1"}]}]}
    store.save_simplified("local:abc", payload)
    assert store.load_simplified("local:abc") == payload
    assert store.load_simplified("local:missing") is None


def test_load_simplified_corrupt_json_returns_none():
    """Mirrors load_extraction/load_gaps: a corrupt simplified.json must be a
    cache miss, not raise -- the GET /simplified endpoint must never 500."""
    paper_id = "local:corrupt_simplified"
    d = store.paper_dir(paper_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "simplified.json").write_text("not valid json }{", encoding="utf-8")
    assert store.load_simplified(paper_id) is None


def test_list_and_remove_paper():
    a = store.PaperMetadata(paper_id="arxiv:2410.00001", title="A", authors=[],
                            added_at="2026-04-01T10:00:00")
    b = store.PaperMetadata(paper_id="arxiv:2410.00002", title="B", authors=[],
                            added_at="2026-04-02T10:00:00")
    a.save()
    b.save()

    listed = store.list_papers()
    assert {p.paper_id for p in listed} == {"arxiv:2410.00001", "arxiv:2410.00002"}
    # Sorted by added_at desc — newest first.
    assert listed[0].paper_id == "arxiv:2410.00002"

    assert store.remove_paper("arxiv:2410.00001") is True
    assert store.remove_paper("arxiv:2410.00001") is False  # already gone
    assert {p.paper_id for p in store.list_papers()} == {"arxiv:2410.00002"}


def test_rmtree_retry_recovers_from_transient_permission_error(tmp_path, monkeypatch):
    import shutil
    import time

    real_rmtree = shutil.rmtree
    calls = {"n": 0}

    def flaky(path, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise PermissionError("[WinError 32] file in use")
        real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(time, "sleep", lambda _s: None)
    monkeypatch.setattr(shutil, "rmtree", flaky)
    victim = tmp_path / "victim"
    victim.mkdir()

    store._rmtree_retry(victim)  # must not raise

    assert calls["n"] == 3
    assert not victim.exists()


def test_rmtree_retry_raises_after_five_failures(tmp_path, monkeypatch):
    import shutil
    import time

    calls = {"n": 0}

    def always_fail(_path, *args, **kwargs):
        calls["n"] += 1
        raise PermissionError("[WinError 32] file in use")

    monkeypatch.setattr(time, "sleep", lambda _s: None)
    monkeypatch.setattr(shutil, "rmtree", always_fail)
    victim = tmp_path / "victim"
    victim.mkdir()

    with pytest.raises(PermissionError):
        store._rmtree_retry(victim)
    assert calls["n"] == 5


# ---------------------------------------------------------------------------
# update_paper_metadata (manual title/authors/year edit)
# ---------------------------------------------------------------------------

def _seed_paper(paper_id: str = "local:abc123def456") -> None:
    store.PaperMetadata(
        paper_id=paper_id, title="Old Title", authors=["Alice"], year=2020,
        added_at="2024-01-01T00:00:00Z",
    ).save()


def test_update_paper_metadata_title(isolated_papergraph_dir):
    _seed_paper()
    meta = store.update_paper_metadata("local:abc123def456", title="New Title")
    assert meta is not None
    assert meta.title == "New Title"
    # authors/year untouched (omitted -> sentinel -> leave)
    assert meta.authors == ["Alice"]
    assert meta.year == 2020
    assert store.PaperMetadata.load("local:abc123def456").title == "New Title"


def test_update_paper_metadata_authors_trimmed_and_blank_dropped(isolated_papergraph_dir):
    _seed_paper()
    meta = store.update_paper_metadata(
        "local:abc123def456", authors=["  Bob  ", "", "   ", "Carol"])
    assert meta.authors == ["Bob", "Carol"]


def test_update_paper_metadata_authors_empty_clears(isolated_papergraph_dir):
    _seed_paper()
    meta = store.update_paper_metadata("local:abc123def456", authors=[])
    assert meta.authors == []


def test_update_paper_metadata_year_set(isolated_papergraph_dir):
    _seed_paper()
    meta = store.update_paper_metadata("local:abc123def456", year=1999)
    assert meta.year == 1999


def test_update_paper_metadata_year_none_clears(isolated_papergraph_dir):
    """Explicit year=None clears; sentinel makes this distinct from omission."""
    _seed_paper()
    meta = store.update_paper_metadata("local:abc123def456", year=None)
    assert meta.year is None
    assert store.PaperMetadata.load("local:abc123def456").year is None


def test_update_paper_metadata_omitted_leaves_year(isolated_papergraph_dir):
    _seed_paper()
    meta = store.update_paper_metadata("local:abc123def456", title="X")
    assert meta.year == 2020  # not passed -> unchanged


def test_update_paper_metadata_blank_title_keeps_old(isolated_papergraph_dir):
    _seed_paper()
    meta = store.update_paper_metadata("local:abc123def456", title="   ")
    assert meta.title == "Old Title"


def test_update_paper_metadata_unknown_id_returns_none(isolated_papergraph_dir):
    assert store.update_paper_metadata("local:missing", title="X") is None


# ---------------------------------------------------------------------------
# find_existing_paper_for — cross-namespace duplicate detection
# ---------------------------------------------------------------------------

def _seed_arxiv_with_pdf(paper_id: str, pdf_bytes: bytes) -> None:
    store.save_pdf(paper_id, pdf_bytes)
    store.PaperMetadata(paper_id=paper_id, title="Seed", authors=["A"], year=2025,
                        added_at="2026-01-01T00:00:00Z").save()


def test_find_existing_paper_for_content_match_across_namespace(fake_pdf_bytes):
    """A local PDF byte-identical to an existing arXiv paper resolves to it."""
    aid = "arxiv:2501.13956"
    _seed_arxiv_with_pdf(aid, fake_pdf_bytes)
    assert store.find_existing_paper_for(fake_pdf_bytes) == aid


def test_find_existing_paper_for_arxiv_id_in_filename(fake_pdf_bytes):
    """Different bytes but the filename carries an arXiv id already in library."""
    aid = "arxiv:2501.13956"
    _seed_arxiv_with_pdf(aid, fake_pdf_bytes)
    got = store.find_existing_paper_for(fake_pdf_bytes + b"x",
                                        filename="zep_arXiv-2501.13956.pdf")
    assert got == aid


def test_find_existing_paper_for_returns_none_for_new(fake_pdf_bytes):
    _seed_arxiv_with_pdf("arxiv:2501.13956", fake_pdf_bytes)
    assert store.find_existing_paper_for(fake_pdf_bytes + b"unique",
                                         filename="brand_new_paper.pdf") is None


def test_find_existing_paper_for_does_not_create_dirs(fake_pdf_bytes):
    """The read-only check must not leave empty paper directories behind."""
    before = {d.name for d in store.papers_dir().iterdir()} if store.papers_dir().exists() else set()
    store.find_existing_paper_for(fake_pdf_bytes + b"z", filename="x_arXiv-9999.99999.pdf")
    after = {d.name for d in store.papers_dir().iterdir()} if store.papers_dir().exists() else set()
    assert after == before


# ---------------------------------------------------------------------------
# Gap synthesis cache persistence
# ---------------------------------------------------------------------------


class TestGapSynthesisCache:
    def test_save_and_load_roundtrip(self, isolated_papergraph_dir):
        payload = {
            "gap_prompt_sha256": "sha_a",
            "resolution_prompt_sha256": "sha_b",
            "papers_sha256": "sha_c",
            "synthesis_prompt_sha256": "sha_d",
            "computed_at": "2024-01-01T00:00:00Z",
            "themes": [{"theme_id": "theme_1", "title": "T"}],
        }
        store.save_gap_synthesis(payload)
        loaded = store.load_gap_synthesis()
        assert loaded == payload

    def test_load_returns_none_when_missing(self, isolated_papergraph_dir):
        assert store.load_gap_synthesis() is None

    def test_load_returns_none_on_corrupt_json(self, isolated_papergraph_dir):
        p = store.gap_synthesis_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{not valid json", encoding="utf-8")
        assert store.load_gap_synthesis() is None

    def test_load_returns_none_when_file_is_a_json_list(self, isolated_papergraph_dir):
        p = store.gap_synthesis_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("[1, 2, 3]", encoding="utf-8")
        assert store.load_gap_synthesis() is None

    def test_save_overwrites_previous_payload(self, isolated_papergraph_dir):
        store.save_gap_synthesis({"themes": [{"theme_id": "old"}]})
        store.save_gap_synthesis({"themes": [{"theme_id": "new"}]})
        loaded = store.load_gap_synthesis()
        assert loaded["themes"] == [{"theme_id": "new"}]

    def test_save_returns_none_when_no_active_workspace(self, isolated_papergraph_dir, monkeypatch):
        """save_gap_synthesis returns None and writes nothing when no active workspace."""
        monkeypatch.setattr(store, "gap_synthesis_path", lambda: None)
        result = store.save_gap_synthesis({"themes": []})
        assert result is None


# ---------------------------------------------------------------------------
# Deep-Research Report artifact persistence (2e-1)
# ---------------------------------------------------------------------------


class TestReportArtifact:
    def test_save_and_load_roundtrip(self, isolated_papergraph_dir):
        payload = {
            "topic": "graph retrieval",
            "sections": [{"question": "Q1?", "answer": "A1", "citations": [], "unverified_quotes": []}],
            "generated_from": {"topic_sha256": "abc", "papers_sha256": "def",
                                "report_questions_prompt_sha256": "ghi"},
            "question_count": 1,
        }
        store.save_report(payload)
        loaded = store.load_report()
        assert loaded == payload

    def test_load_returns_none_when_missing(self, isolated_papergraph_dir):
        assert store.load_report() is None

    def test_load_returns_none_on_corrupt_json(self, isolated_papergraph_dir):
        p = store.report_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{not valid json", encoding="utf-8")
        assert store.load_report() is None

    def test_load_returns_none_when_file_is_a_json_list(self, isolated_papergraph_dir):
        p = store.report_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("[1, 2, 3]", encoding="utf-8")
        assert store.load_report() is None

    def test_save_overwrites_previous_payload(self, isolated_papergraph_dir):
        store.save_report({"topic": "old", "sections": []})
        store.save_report({"topic": "new", "sections": []})
        loaded = store.load_report()
        assert loaded["topic"] == "new"

    def test_save_returns_none_when_no_active_workspace(self, isolated_papergraph_dir, monkeypatch):
        """save_report returns None and writes nothing when no active workspace."""
        monkeypatch.setattr(store, "report_path", lambda: None)
        result = store.save_report({"topic": "x"})
        assert result is None
