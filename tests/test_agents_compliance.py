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
