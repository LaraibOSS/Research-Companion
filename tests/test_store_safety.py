"""A damaged store file must never be replaced by an almost-empty one.

Every loader treats an unparseable file as "empty". That is right for a reader
and destructive for a writer: load, append, save would overwrite everything
the file held with the one record being saved.
"""
from __future__ import annotations

import json

import pytest

from research_companion import notes_store as ns
from research_companion import store


def _note(**kw):
    base = dict(draft_section_id="s1", draft_section_title="Intro", paper_id="A",
                paper_title="Paper A", relation="strengthens", relevance=0.5,
                rationale="r", evidence_quote="q", evidence_section_id="s1", comment="")
    base.update(kw)
    return base


def test_truncated_notes_file_is_kept_aside_not_overwritten(isolated_papergraph_dir):
    ns.save_note(_note(paper_id="A"))
    ns.save_note(_note(paper_id="B"))
    path = ns._path()
    whole = path.read_text(encoding="utf-8")
    path.write_text(whole[: len(whole) // 2], encoding="utf-8")   # a torn write

    ns.save_note(_note(paper_id="C"))

    kept = list(path.parent.glob("notes.json.corrupt-*"))
    assert len(kept) == 1, "the damaged file must survive for recovery"
    assert kept[0].read_text(encoding="utf-8") == whole[: len(whole) // 2]
    assert [n["paper_id"] for n in ns.list_notes()] == ["C"]


def test_truncated_failures_file_is_kept_aside(isolated_papergraph_dir):
    store.record_failure("k1", {"stage": "add", "error": "x"})
    path = store.failed_json_path()
    path.write_text('{"k1": {"stage": "ad', encoding="utf-8")

    store.record_failure("k2", {"stage": "add", "error": "y"})

    assert list(path.parent.glob("failed.json.corrupt-*"))
    assert set(store.list_failures()) == {"k2"}


def test_a_healthy_file_is_never_moved_aside(isolated_papergraph_dir):
    ns.save_note(_note(paper_id="A"))
    ns.save_note(_note(paper_id="B"))
    assert not list(ns._path().parent.glob("*.corrupt-*"))
    assert len(ns.list_notes()) == 2


def test_atomic_write_leaves_no_temp_file_and_replaces_whole(tmp_path):
    target = tmp_path / "own" / "x.json"      # tmp_path also holds the isolated store
    store.atomic_write_text(target, json.dumps({"a": 1}))
    store.atomic_write_text(target, json.dumps({"a": 2}))
    assert json.loads(target.read_text(encoding="utf-8")) == {"a": 2}
    assert [p.name for p in target.parent.iterdir()] == ["x.json"]


def test_a_failed_write_keeps_the_previous_content(tmp_path, monkeypatch):
    target = tmp_path / "own" / "x.json"
    store.atomic_write_text(target, "old")

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(store.os, "replace", boom)
    with pytest.raises(OSError):
        store.atomic_write_text(target, "new")
    assert target.read_text(encoding="utf-8") == "old"
    assert [p.name for p in target.parent.iterdir()] == ["x.json"]
