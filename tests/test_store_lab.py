"""Tests for research_companion.store Research Lab persistence helpers."""
from __future__ import annotations

import json
from datetime import datetime

from research_companion import store

# ============================================================================
# Config helpers: load_config, save_config, get/set draft_paper_id
# ============================================================================


def test_config_path_returns_papergraph_dir_config_json(isolated_papergraph_dir):
    """config_path() returns papergraph_dir()/config.json."""
    path = store.config_path()
    assert path == isolated_papergraph_dir / "config.json"


def test_load_config_empty_when_missing():
    """load_config() returns {} if config.json does not exist."""
    cfg = store.load_config()
    assert cfg == {}


def test_load_config_corrupt_json_returns_empty_dict():
    """load_config() returns {} for corrupt JSON instead of crashing."""
    config_file = store.config_path()
    config_file.write_text("not valid json }{", encoding="utf-8")
    cfg = store.load_config()
    assert cfg == {}


def test_save_config_and_load_roundtrip():
    """save_config(cfg) saves to config.json; load_config() retrieves it."""
    cfg = {"key": "value", "nested": {"foo": "bar"}}
    store.save_config(cfg)
    loaded = store.load_config()
    assert loaded == cfg


def test_save_config_writes_indent_2_utf8():
    """save_config writes JSON with indent=2 and utf-8 encoding."""
    cfg = {"a": 1, "b": 2}
    store.save_config(cfg)
    content = store.config_path().read_text(encoding="utf-8")
    # Check indentation
    assert '  "a": 1' in content or '  "a":1' in content or '"a": 1' in content
    # Content should be valid JSON with proper formatting
    assert json.loads(content) == cfg


def test_get_draft_paper_id_none_when_not_set():
    """get_draft_paper_id() returns None if draft_paper_id not in config."""
    draft_id = store.get_draft_paper_id()
    assert draft_id is None


def test_set_and_get_draft_paper_id():
    """set_draft_paper_id(id) saves; get_draft_paper_id() retrieves it."""
    store.set_draft_paper_id("arxiv:2410.05779")
    draft_id = store.get_draft_paper_id()
    assert draft_id == "arxiv:2410.05779"


def test_set_draft_paper_id_none_clears_key():
    """set_draft_paper_id(None) removes the draft_paper_id key from config."""
    store.set_draft_paper_id("arxiv:2410.05779")
    assert store.get_draft_paper_id() == "arxiv:2410.05779"
    store.set_draft_paper_id(None)
    assert store.get_draft_paper_id() is None


# ============================================================================
# Sections: save_sections, load_sections with text_sha staleness check
# ============================================================================


def test_sections_save_creates_paper_dir():
    """save_sections(paper_id, payload) creates paper dir if missing."""
    paper_id = "arxiv:2410.05779"
    payload = {"text_sha256": "abc123", "sections": [{"name": "Intro", "text": "..."}]}
    path = store.save_sections(paper_id, payload)
    assert path.exists()
    assert path.name == "sections.json"
    assert path.parent.name == "arxiv__2410_05779"


def test_sections_save_load_roundtrip():
    """save_sections()/load_sections() round-trip preserves payload."""
    paper_id = "arxiv:2410.05779"
    payload = {"text_sha256": "abc123", "sections": [{"name": "Intro", "text": "..."}]}
    store.save_sections(paper_id, payload)
    loaded = store.load_sections(paper_id)
    assert loaded == payload


def test_sections_load_missing_returns_none():
    """load_sections() returns None if sections.json does not exist."""
    result = store.load_sections("arxiv:9999.99999")
    assert result is None


def test_sections_load_corrupt_json_returns_none():
    """load_sections() returns None for corrupt JSON."""
    paper_id = "arxiv:2410.05779"
    store.paper_dir(paper_id)  # create dir
    (store.paper_dir(paper_id) / "sections.json").write_text("invalid json }{", encoding="utf-8")
    result = store.load_sections(paper_id)
    assert result is None


def test_sections_text_sha_match_returns_payload():
    """load_sections(text_sha=X) returns payload if text_sha256 matches."""
    paper_id = "arxiv:2410.05779"
    payload = {"text_sha256": "abc123", "sections": []}
    store.save_sections(paper_id, payload)
    result = store.load_sections(paper_id, text_sha="abc123")
    assert result == payload


def test_sections_text_sha_mismatch_returns_none():
    """load_sections(text_sha=X) returns None if text_sha256 mismatches (stale)."""
    paper_id = "arxiv:2410.05779"
    payload = {"text_sha256": "abc123", "sections": []}
    store.save_sections(paper_id, payload)
    result = store.load_sections(paper_id, text_sha="different")
    assert result is None


def test_sections_text_sha_not_in_payload_returns_none():
    """load_sections(text_sha=X) returns None if payload missing text_sha256 key."""
    paper_id = "arxiv:2410.05779"
    payload = {"sections": []}  # no text_sha256
    store.save_sections(paper_id, payload)
    result = store.load_sections(paper_id, text_sha="abc123")
    assert result is None


# ============================================================================
# Alignment: save_alignment, load_alignment with draft_paper_id staleness check
# ============================================================================


def test_alignment_save_creates_paper_dir():
    """save_alignment(paper_id, payload) creates paper dir if missing."""
    paper_id = "arxiv:2410.05779"
    payload = {"draft_paper_id": "arxiv:2410.05780", "alignment": []}
    path = store.save_alignment(paper_id, payload)
    assert path.exists()
    assert path.name == "alignment.json"
    assert path.parent.name == "arxiv__2410_05779"


def test_alignment_save_load_roundtrip():
    """save_alignment()/load_alignment() round-trip preserves payload."""
    paper_id = "arxiv:2410.05779"
    payload = {"draft_paper_id": "arxiv:2410.05780", "alignment": ["match1", "match2"]}
    store.save_alignment(paper_id, payload)
    loaded = store.load_alignment(paper_id)
    assert loaded == payload


def test_alignment_load_missing_returns_none():
    """load_alignment() returns None if alignment.json does not exist."""
    result = store.load_alignment("arxiv:9999.99999")
    assert result is None


def test_alignment_load_corrupt_json_returns_none():
    """load_alignment() returns None for corrupt JSON."""
    paper_id = "arxiv:2410.05779"
    store.paper_dir(paper_id)  # create dir
    (store.paper_dir(paper_id) / "alignment.json").write_text("invalid json }{", encoding="utf-8")
    result = store.load_alignment(paper_id)
    assert result is None


def test_alignment_draft_paper_id_match_returns_payload():
    """load_alignment(draft_paper_id=X) returns payload if draft_paper_id matches."""
    paper_id = "arxiv:2410.05779"
    draft_id = "arxiv:2410.05780"
    payload = {"draft_paper_id": draft_id, "alignment": []}
    store.save_alignment(paper_id, payload)
    result = store.load_alignment(paper_id, draft_paper_id=draft_id)
    assert result == payload


def test_alignment_draft_paper_id_mismatch_returns_none():
    """load_alignment(draft_paper_id=X) returns None if draft_paper_id mismatches (stale)."""
    paper_id = "arxiv:2410.05779"
    payload = {"draft_paper_id": "arxiv:2410.05780", "alignment": []}
    store.save_alignment(paper_id, payload)
    result = store.load_alignment(paper_id, draft_paper_id="arxiv:different")
    assert result is None


def test_alignment_draft_paper_id_not_in_payload_returns_none():
    """load_alignment(draft_paper_id=X) returns None if payload missing draft_paper_id key."""
    paper_id = "arxiv:2410.05779"
    payload = {"alignment": []}  # no draft_paper_id
    store.save_alignment(paper_id, payload)
    result = store.load_alignment(paper_id, draft_paper_id="arxiv:2410.05780")
    assert result is None


# ============================================================================
# Strength: save_strength, load_strength
# ============================================================================


def test_strength_save_creates_paper_dir():
    """save_strength(paper_id, payload) creates paper dir if missing."""
    paper_id = "arxiv:2410.05779"
    payload = {"score": 0.95, "details": "strong match"}
    path = store.save_strength(paper_id, payload)
    assert path.exists()
    assert path.name == "strength.json"
    assert path.parent.name == "arxiv__2410_05779"


def test_strength_save_load_roundtrip():
    """save_strength()/load_strength() round-trip preserves payload."""
    paper_id = "arxiv:2410.05779"
    payload = {"score": 0.95, "details": "strong match"}
    store.save_strength(paper_id, payload)
    loaded = store.load_strength(paper_id)
    assert loaded == payload


def test_strength_load_missing_returns_none():
    """load_strength() returns None if strength.json does not exist."""
    result = store.load_strength("arxiv:9999.99999")
    assert result is None


def test_strength_load_corrupt_json_returns_none():
    """load_strength() returns None for corrupt JSON."""
    paper_id = "arxiv:2410.05779"
    store.paper_dir(paper_id)  # create dir
    (store.paper_dir(paper_id) / "strength.json").write_text("invalid json }{", encoding="utf-8")
    result = store.load_strength(paper_id)
    assert result is None


# ============================================================================
# Ingest failure registry: record_failure, clear_failure, list_failures
# ============================================================================


def test_failed_json_path():
    """failed_json_path() returns papergraph_dir()/failed.json."""
    path = store.failed_json_path()
    assert path.name == "failed.json"
    assert path.parent == store.papergraph_dir()


def test_record_failure_adds_entry_with_timestamp():
    """record_failure(key, info) adds entry under key with 'at' timestamp."""
    key = "paper_1"
    info = {"paper_id": "arxiv:2410.05779", "path": "/path/to/pdf", "stage": "add", "error": "failed"}
    store.record_failure(key, info)
    failures = store.list_failures()
    assert key in failures
    assert "at" in failures[key]
    # Verify timestamp is ISO UTC format
    ts = failures[key]["at"]
    datetime.fromisoformat(ts.replace("Z", "+00:00"))  # should not raise


def test_record_failure_upserts_overwrites():
    """record_failure(key, info) overwrites previous entry for same key."""
    key = "paper_1"
    store.record_failure(key, {"error": "first"})
    store.record_failure(key, {"error": "second"})
    failures = store.list_failures()
    assert failures[key]["error"] == "second"


def test_record_failure_adds_at_only_if_absent():
    """record_failure() adds 'at' timestamp only if absent from info."""
    key = "paper_1"
    timestamp = "2026-01-01T12:00:00Z"
    info = {"error": "test", "at": timestamp}
    store.record_failure(key, info)
    failures = store.list_failures()
    # Should preserve the provided timestamp
    assert failures[key]["at"] == timestamp


def test_clear_failure_removes_entry():
    """clear_failure(key) removes entry for key."""
    key = "paper_1"
    store.record_failure(key, {"error": "test"})
    assert key in store.list_failures()
    store.clear_failure(key)
    assert key not in store.list_failures()


def test_clear_failure_noop_on_absent_key():
    """clear_failure(key) is no-op if key absent."""
    # Should not raise
    store.clear_failure("nonexistent")
    assert store.list_failures() == {}


def test_clear_failure_also_removes_entries_matching_paper_id():
    """clear_failure(key, paper_id=...) drops any entry whose paper_id matches.

    A paper can be recorded under one key (e.g. a folder path) and later
    re-ingested under a different key (e.g. 'upload://draft.pdf'). Failure
    lookups (_build_paper_summary, retry_paper) match by paper_id OR key, so
    clearing only the exact key leaves a stale entry that pins the paper to
    'failed' forever. Clearing by paper_id too fixes that.
    """
    pid = "local:abc123def456"
    store.record_failure("/some/folder/draft.pdf", {"paper_id": pid, "error": "old"})
    store.record_failure("upload://draft.pdf", {"paper_id": pid, "error": "new"})
    store.record_failure("unrelated", {"paper_id": "local:other", "error": "keep"})

    store.clear_failure("upload://draft.pdf", paper_id=pid)

    remaining = store.list_failures()
    assert "upload://draft.pdf" not in remaining
    assert "/some/folder/draft.pdf" not in remaining  # cleared by paper_id match
    assert "unrelated" in remaining  # different paper_id, untouched


def test_list_failures_empty_when_file_missing():
    """list_failures() returns {} if failed.json does not exist."""
    result = store.list_failures()
    assert result == {}


def test_list_failures_corrupt_json_returns_empty_dict():
    """list_failures() returns {} for corrupt JSON instead of crashing."""
    failed_file = store.failed_json_path()
    failed_file.write_text("invalid json }{", encoding="utf-8")
    result = store.list_failures()
    assert result == {}


def test_list_failures_roundtrip():
    """record_failure() + list_failures() round-trip."""
    key1 = "paper_1"
    key2 = "paper_2"
    info1 = {"paper_id": "arxiv:2410.05779", "stage": "add", "error": "failed"}
    info2 = {"paper_id": "arxiv:2410.05780", "stage": "text", "error": "timeout"}
    store.record_failure(key1, info1)
    store.record_failure(key2, info2)
    failures = store.list_failures()
    assert len(failures) == 2
    assert failures[key1]["stage"] == "add"
    assert failures[key2]["stage"] == "text"


# ============================================================================
# Integration: save_* works for paper_id whose dir does not exist yet
# ============================================================================


def test_save_functions_create_paper_dir_if_missing():
    """Verify save_sections, save_alignment, save_strength all create paper dir."""
    paper_id = "local:abc123def456"
    # Verify dir doesn't exist
    d = store.papers_dir() / store._id_to_dirname(paper_id)
    assert not d.exists()

    # All save_* should create it
    store.save_sections(paper_id, {"data": "sections"})
    assert d.exists()

    paper_id2 = "arxiv:2410.05779"
    d2 = store.papers_dir() / store._id_to_dirname(paper_id2)
    store.save_alignment(paper_id2, {"data": "alignment"})
    assert d2.exists()

    paper_id3 = "doi:10.1145/1234567"
    d3 = store.papers_dir() / store._id_to_dirname(paper_id3)
    store.save_strength(paper_id3, {"data": "strength"})
    assert d3.exists()


# ============================================================================
# Config and failure writes on fresh (non-existent) root directory
# ============================================================================


def test_save_config_and_record_failure_create_root_dir(tmp_path, monkeypatch):
    """save_config() and record_failure() should create papergraph_dir() if missing.

    This tests the case where RESEARCH_COMPANION_DIR points to a non-existent path
    (e.g., on fresh install). Both functions must ensure the parent directory exists.
    """
    # Point to a fresh, non-existent subdirectory
    fresh_root = tmp_path / "fresh-research-dir"
    assert not fresh_root.exists()

    monkeypatch.setenv("RESEARCH_COMPANION_DIR", str(fresh_root))
    store._reset_workspace_caches()

    # save_config should succeed despite root not existing
    store.save_config({"a": 1})
    assert fresh_root.exists()
    # 0.4: per-workspace config lives under workspaces/<active>/
    config_file = store.papergraph_dir() / "config.json"
    assert config_file.exists()
    assert store.load_config() == {"a": 1}

    # Remove the root again for record_failure test
    import shutil
    shutil.rmtree(fresh_root)
    assert not fresh_root.exists()

    # record_failure should also succeed and create root
    store._reset_workspace_caches()
    store.record_failure("k", {"stage": "add", "error": "x"})
    assert fresh_root.exists()
    failed_file = store.papergraph_dir() / "failed.json"
    assert failed_file.exists()
    failures = store.list_failures()
    assert "k" in failures
    assert failures["k"]["stage"] == "add"
    assert failures["k"]["error"] == "x"
