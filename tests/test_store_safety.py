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


def test_a_briefly_locked_target_is_retried_not_failed(tmp_path, monkeypatch):
    """On Windows a rename onto a file another thread has open fails with
    'Access is denied' for a moment. Seen in the suite as a find-pdf job
    failing on metadata.json. The write retries instead of losing the save."""
    target = tmp_path / "own" / "x.json"
    store.atomic_write_text(target, "old")
    real_replace = store.os.replace
    calls = {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError(5, "Access is denied")
        return real_replace(src, dst)

    monkeypatch.setattr(store.os, "replace", flaky)
    monkeypatch.setattr("time.sleep", lambda s: None)
    store.atomic_write_text(target, "new")
    assert target.read_text(encoding="utf-8") == "new"
    assert calls["n"] == 3
    assert [p.name for p in target.parent.iterdir()] == ["x.json"]


def test_concurrent_writers_never_share_a_temp_file(tmp_path):
    """Two threads saving the same file used the same temp name (it carried
    only the process id), so one could rename the other's half-written temp."""
    import json as _json
    import threading

    target = tmp_path / "own" / "shared.json"
    errors = []

    def writer(n):
        try:
            for i in range(40):
                store.atomic_write_text(target, _json.dumps({"writer": n, "i": i, "pad": "x" * 2000}))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    data = _json.loads(target.read_text(encoding="utf-8"))   # always whole, never torn
    assert data["i"] == 39
    assert [p.name for p in target.parent.iterdir()] == ["shared.json"]
