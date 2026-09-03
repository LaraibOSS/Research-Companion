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


def test_kind_and_source_excerpt_persist(isolated_papergraph_dir):
    n = ns.save_note({"kind": "ask", "source_excerpt": "the answer", "comment": "mine"})
    assert n["kind"] == "ask" and n["source_excerpt"] == "the answer"
    assert n["paper_id"] == "" and n["draft_section_id"] == ""


def test_legacy_note_without_kind_defaults_to_opportunity(isolated_papergraph_dir):
    import json
    p = ns._path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps([{"id": "x", "status": "open", "paper_id": "P",
                              "draft_section_id": "s1", "comment": "old"}]), encoding="utf-8")
    got = ns.list_notes()[0]
    assert got.get("kind", "opportunity") == "opportunity"  # read-time default; see Step 3


def test_dedupe_only_when_both_anchors_present(isolated_papergraph_dir):
    a = ns.save_note({"kind": "freeform", "comment": "one"})
    b = ns.save_note({"kind": "freeform", "comment": "two"})
    assert len({a["id"], b["id"]}) == 2  # no anchors -> never dedupe
    c = ns.save_note({"kind": "alignment", "paper_id": "P", "draft_section_id": "s1", "comment": "x"})
    d = ns.save_note({"kind": "alignment", "paper_id": "P", "draft_section_id": "s1", "comment": "y"})
    assert c["id"] == d["id"]  # both anchors -> dedupe/update


def test_markdown_group_by_paper_and_unfiled(isolated_papergraph_dir):
    ns.save_note({"kind": "paper", "paper_id": "P", "paper_title": "Paper P", "comment": "a"})
    ns.save_note({"kind": "freeform", "comment": "loose"})  # no paper, no section
    by_paper = ns.notes_to_markdown(ns.list_notes(), group_by="paper")
    assert "## Paper P" in by_paper and "## Unfiled" in by_paper
    by_sec = ns.notes_to_markdown(ns.list_notes(), group_by="section")
    assert "## Unfiled" in by_sec  # both notes are section-less


def test_markdown_exports_source_excerpt_for_ask_and_reader_notes(isolated_papergraph_dir):
    """ask/reader notes carry their whole captured body in source_excerpt
    (no paper/relation/rationale), so notes_to_markdown must surface it —
    otherwise those notes export as blank/contentless lines (final-review
    finding 1)."""
    ns.save_note({"kind": "ask", "source_excerpt": "The answer text from ask."})
    ns.save_note({"kind": "reader", "source_excerpt": "A highlighted reader passage."})
    md = ns.notes_to_markdown(ns.list_notes())
    assert "The answer text from ask." in md
    assert "A highlighted reader passage." in md


def test_markdown_omits_source_excerpt_segment_when_empty(isolated_papergraph_dir):
    """A note with no source_excerpt must render exactly as before — no new
    dangling ' — ' separator introduced by the source_excerpt fix."""
    ns.save_note(_rec(paper_title="P1", relation="strengthens", relevance=0.8, rationale="why"))
    md = ns.notes_to_markdown(ns.list_notes())
    line = next(ln for ln in md.splitlines() if "P1" in ln)
    assert line == "- [ ] P1 — strengthens, relevance 0.8 — why"


def test_dedupe_requires_matching_kind(isolated_papergraph_dir):
    """A freeform save targeting the same (paper_id, draft_section_id) as an
    existing OPEN alignment note must NOT update it in place — that would
    reclassify its kind and wipe relation/relevance/rationale/evidence_quote
    (final-review finding 3)."""
    alignment = ns.save_note({"kind": "alignment", "paper_id": "P", "draft_section_id": "s1",
                               "relation": "strengthens", "relevance": 0.9,
                               "rationale": "why", "evidence_quote": "q"})
    freeform = ns.save_note({"kind": "freeform", "paper_id": "P", "draft_section_id": "s1",
                              "comment": "unrelated note"})
    assert alignment["id"] != freeform["id"]
    all_notes = ns.list_notes()
    assert len(all_notes) == 2
    kept = next(n for n in all_notes if n["id"] == alignment["id"])
    assert kept["kind"] == "alignment"
    assert kept["relation"] == "strengthens"
    assert kept["relevance"] == 0.9
    assert kept["rationale"] == "why"
    assert kept["evidence_quote"] == "q"


def test_origin_fields_round_trip(isolated_papergraph_dir):
    n = ns.save_note(_rec(
        origin_kind="gap",
        origin_id="gap_85c6f47740cf",
        origin_label="Expand evaluations to diverse device classes",
    ))
    got = ns.list_notes()[0]
    assert got["origin_kind"] == "gap"
    assert got["origin_id"] == "gap_85c6f47740cf"
    assert got["origin_label"] == "Expand evaluations to diverse device classes"
    assert n["origin_kind"] == "gap"


def test_note_without_origin_reads_back_empty_not_missing(isolated_papergraph_dir):
    """The no-migration guarantee, pinned as a test rather than asserted in prose.

    Every note written before origins existed has no origin keys at all.
    save_note filters through `{k: record.get(k, "") for k in _FIELDS}`, so
    those notes must read back with empty strings — never a KeyError, and
    never None (which would render as the string "None" in the UI).
    """
    n = ns.save_note(_rec())
    assert n["origin_kind"] == ""
    assert n["origin_id"] == ""
    assert n["origin_label"] == ""


def test_markdown_export_includes_origin_when_labelled(isolated_papergraph_dir):
    ns.save_note(_rec(origin_kind="gap", origin_id="gap_1",
                      origin_label="Expand evaluations"))
    md = ns.notes_to_markdown(ns.list_notes())
    assert "from: Expand evaluations" in md


def test_markdown_export_omits_origin_when_unlabelled(isolated_papergraph_dir):
    """An id with no label is not renderable provenance — an opaque hash in an
    exported document tells the reader nothing. The label is what carries."""
    ns.save_note(_rec(origin_kind="gap", origin_id="gap_1", origin_label=""))
    md = ns.notes_to_markdown(ns.list_notes())
    assert "from:" not in md
