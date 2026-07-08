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
