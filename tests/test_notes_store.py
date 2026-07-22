"""Tests for research_companion.notes_store — workspace-scoped revision notes.

Notes are structured, citable records captured from an uncited-paper
opportunity suggestion, persisted at papergraph_dir()/notes.json (mirrors
the failures-store accessors in research_companion.store).
"""
from __future__ import annotations

from research_companion import notes_store as ns


def _rec(**kw):
    base = dict(draft_section_id="s5", draft_section_title="Related Work",
                paper_id="B", paper_title="Paper B", relation="strengthens",
                relevance=0.8, rationale="why", evidence_quote="q",
                evidence_section_id="s1", comment="")
    base.update(kw)
    return base


def test_save_assigns_id_created_status(isolated_papergraph_dir):
    n = ns.save_note(_rec())
    assert n["id"] and n["created_at"].endswith("Z") and n["status"] == "open"
    assert ns.list_notes() == [n]


def test_save_dedupes_open_same_paper_section(isolated_papergraph_dir):
    a = ns.save_note(_rec(rationale="first"))
    b = ns.save_note(_rec(rationale="second"))
    assert len(ns.list_notes()) == 1 and b["id"] == a["id"]
    assert ns.list_notes()[0]["rationale"] == "second"


def test_update_and_delete(isolated_papergraph_dir):
    n = ns.save_note(_rec())
    ns.update_note(n["id"], status="done", comment="focus here")
    got = ns.list_notes()[0]
    assert got["status"] == "done" and got["comment"] == "focus here"
    assert ns.delete_note(n["id"]) is True and ns.list_notes() == []
    assert ns.update_note("missing") is None


def test_markdown_grouping_and_checkboxes(isolated_papergraph_dir):
    ns.save_note(_rec(draft_section_title="Methods", paper_title="P1", relevance=0.9))
    d = ns.save_note(_rec(draft_section_title="Methods", paper_id="C", paper_title="P2", relevance=0.5))
    ns.update_note(d["id"], status="done")
    md = ns.notes_to_markdown(ns.list_notes())
    assert "## Methods" in md
    assert "- [ ] P1" in md and "- [x] P2" in md
    assert md.index("P1") < md.index("P2")  # relevance desc
    assert ns.notes_to_markdown([]) == "# Revision notes\n\n_No notes yet._\n"


def test_markdown_omits_dismissed(isolated_papergraph_dir):
    n = ns.save_note(_rec(paper_title="Gone"))
    ns.update_note(n["id"], status="dismissed")
    assert "Gone" not in ns.notes_to_markdown(ns.list_notes())


def test_missing_relevance_coerced_and_export_survives(isolated_papergraph_dir):
    """A note posted without relevance (POST only validates paper_id +
    draft_section_id, so this is a legal payload) must not blow up
    notes_to_markdown's relevance-desc sort with a str/float comparison."""
    rec = _rec(paper_id="B", paper_title="No Relevance")
    del rec["relevance"]
    ns.save_note(rec)
    ns.save_note(_rec(paper_id="C", paper_title="Has Relevance", relevance=0.6))

    saved = {n["paper_id"]: n for n in ns.list_notes()}
    assert saved["B"]["relevance"] == 0.0  # coerced, not the string ""

    md = ns.notes_to_markdown(ns.list_notes())
    assert "No Relevance" in md and "Has Relevance" in md


def test_dedupe_preserves_existing_comment_when_resave_omits_it(isolated_papergraph_dir):
    n = ns.save_note(_rec())
    ns.update_note(n["id"], comment="keep me")
    again = ns.save_note(_rec())  # re-save with the default empty comment
    assert again["id"] == n["id"]
    assert again["comment"] == "keep me"
    assert ns.list_notes()[0]["comment"] == "keep me"
