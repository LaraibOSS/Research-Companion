import asyncio

from research_companion import store
from research_companion.agents.base import AgentContext
from research_companion.agents.bus import Bus
from research_companion.agents.compliance import ComplianceAgent


def _run(agent, ctx):
    return asyncio.run(agent.run(ctx))


def test_skips_without_venue(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "papers_dir", lambda: tmp_path)
    monkeypatch.setattr(store, "load_text", lambda pid: "body")
    ctx = AgentContext(paper_id="p", bus=Bus(), data={"_extraction": {"related_work": []}})
    res = _run(ComplianceAgent(), ctx)
    assert res.ok and res.data.get("checks", []) == []


def test_runs_for_known_venue(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "papers_dir", lambda: tmp_path)
    monkeypatch.setattr(store, "load_text", lambda pid: "Introduction\nBody")
    monkeypatch.setattr(store, "load_sections", lambda pid: None)
    monkeypatch.setattr(store, "pdf_page_count", lambda pid: 20)
    ctx = AgentContext(paper_id="p", bus=Bus(),
                       data={"_venue": "neurips", "_extraction": {"related_work": []}})
    res = _run(ComplianceAgent(), ctx)
    assert res.ok
    assert res.data["venue"] == "neurips"
    # neurips page_limit 9, 20 pages -> a desk_reject finding exists
    assert res.data["counts"]["desk_reject"] >= 1


def test_uses_cached_sections_payload_dict(tmp_path, monkeypatch):
    # Real store.load_sections() shape: a payload dict of plain Section-shaped
    # dicts (as persisted to disk), not a bare list of Section objects. This
    # exercises the `Section(**s)` conversion branch in the agent (as opposed
    # to the None-fallback -> build_section_tree path that the other tests use).
    monkeypatch.setattr(store, "papers_dir", lambda: tmp_path)
    monkeypatch.setattr(store, "load_text", lambda pid: "Introduction\nBody\n")
    monkeypatch.setattr(store, "load_sections", lambda pid: {
        "sections": [
            {"section_id": "s1", "title": "Limitations", "level": 1,
             "parent": None, "char_start": 0, "char_end": 5},
        ],
    })
    monkeypatch.setattr(store, "pdf_page_count", lambda pid: 1)
    ctx = AgentContext(paper_id="p", bus=Bus(),
                       data={"_venue": "neurips", "_extraction": {"related_work": []}})
    res = _run(ComplianceAgent(), ctx)
    assert res.ok
    # neurips requires a "limitations" section; the converted payload section
    # (title "Limitations") must satisfy it, so there must be no desk-reject
    # finding for section:limitations.
    findings = [c for c in res.data["checks"]
                if c["check"] == "section:limitations" and c["status"] == "finding"]
    assert findings == []
    ok_checks = [c for c in res.data["checks"]
                 if c["check"] == "section:limitations" and c["status"] == "ok"]
    assert ok_checks, "expected section:limitations to be satisfied from the payload dict"
