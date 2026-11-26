"""Regression tests for the Phase 0 trust fixes.

Each test pins a failure that was silent: data replaced by an empty file, a
"read" tool that wrote, and a paid check that could never say yes.
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


# --- a damaged file must not be replaced by an almost-empty one ---------------

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


# --- a tool advertised as a lookup must not write ------------------------------

_BIB = """Intro text.

References

[1] A. Vaswani, N. Shazeer, N. Parmar. Attention is all you need. NeurIPS, 2017.
[2] J. Devlin, M. Chang, K. Lee. BERT: Pre-training of deep bidirectional transformers. NAACL, 2019.
[3] K. He, X. Zhang, S. Ren, J. Sun. Deep residual learning for image recognition. CVPR, 2016.
"""


def _paper(pid: str, text: str):
    store.PaperMetadata(paper_id=pid, title=pid, authors=[]).save()
    store.save_text(pid, text)


def test_mcp_citation_coverage_does_not_replace_the_drafts_stored_coverage(isolated_papergraph_dir):
    from research_companion import citations_coverage as cc
    from research_companion import mcp_tools

    _paper("local:draft", _BIB)
    _paper("local:other", _BIB.replace("Attention is all you need", "Some other title entirely"))

    saved = cc.compute_coverage("local:draft")
    saved["resolved_at"] = "2026-01-01T00:00:00Z"
    cc.save_coverage(saved)
    before = cc.coverage_path().read_text(encoding="utf-8")

    res = mcp_tools.citation_coverage(paper_id="local:other")

    assert res["paper_id"] == "local:other" and res["counts"]["total"] == 3
    assert cc.coverage_path().read_text(encoding="utf-8") == before
    assert cc.load_coverage()["draft_paper_id"] == "local:draft"


# --- the paid "was this addressed" check must be able to say yes ---------------

def test_addressed_check_reads_section_text_from_offsets(isolated_papergraph_dir):
    """sections.json stores offsets, not text. Reading a missing "text" key
    made every unit empty, so the model was asked about nothing and the
    evidence quote could never verify."""
    from research_companion.journey import _llm_check_addressed

    intro = "Introduction. We study caching for language model inference. "
    related = ("Related work. Prior systems compress the key value cache with "
               "quantization and report a twofold memory reduction. ")
    draft = intro + related
    sections = {"sections": [
        {"section_id": "s1", "title": "Introduction", "char_start": 0, "char_end": len(intro)},
        {"section_id": "s2", "title": "Related work", "char_start": len(intro),
         "char_end": len(draft)},
    ]}
    seen = {}

    def llm(prompt: str) -> str:
        seen["prompt"] = prompt
        return json.dumps({"addressed": True,
                           "evidence": "compress the key value cache with quantization"})

    sug = {"kind": "related_work", "title": "Discuss key value cache quantization",
           "detail": "Cite prior work on cache compression"}
    assert _llm_check_addressed(sug, "local:draft", draft, sections, llm) is True
    assert "key value cache" in seen["prompt"]
