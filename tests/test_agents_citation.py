"""Tests for CitationAgent — wraps the deterministic reference validator."""
from __future__ import annotations

import pytest

from papergraph.agents import events
from papergraph.agents.base import AgentContext
from papergraph.agents.bus import Bus
from papergraph.agents.citation import CitationAgent


def _ctx_with_extraction(related_work, lookup):
    ctx = AgentContext(paper_id="local:x", bus=Bus(), data={})
    ctx.data["_extraction"] = {"related_work": related_work}
    ctx.data["_lookup"] = lookup
    return ctx


def _known_title_lookup(known):
    def _lookup(ref):
        if known.lower() in ref.title.lower():
            return {"title": ref.title, "authors": [], "year": 2017,
                    "doi": None, "arxiv_id": None}
        return None
    return _lookup


@pytest.mark.asyncio
async def test_citation_agent_reports_counts_and_flags_bad_refs():
    ctx = _ctx_with_extraction(
        ["Attention Is All You Need", "A Totally Fabricated Paper"],
        _known_title_lookup("Attention Is All You Need"),
    )
    result = await CitationAgent().run(ctx)
    assert result.ok
    assert result.data["counts"] == {"verified": 1, "suspect": 0, "unverified": 1}
    bad = [e for e in ctx.bus.history
           if isinstance(e, events.Finding) and e.kind == "bad_reference"]
    assert len(bad) == 1
    assert "Fabricated" in bad[0].summary
    reports = [e for e in ctx.bus.history
               if isinstance(e, events.Finding) and e.kind == "citation_report"]
    assert len(reports) == 1


@pytest.mark.asyncio
async def test_citation_agent_empty_bibliography_is_ok():
    ctx = _ctx_with_extraction([], _known_title_lookup("x"))
    result = await CitationAgent().run(ctx)
    assert result.ok
    assert result.data["counts"] == {"verified": 0, "suspect": 0, "unverified": 0}


@pytest.mark.asyncio
async def test_citation_report_finding_carries_references():
    ctx = _ctx_with_extraction(["Attention Is All You Need"],
                               _known_title_lookup("Attention Is All You Need"))
    await CitationAgent().run(ctx)
    report = next(e for e in ctx.bus.history
                  if isinstance(e, events.Finding) and e.kind == "citation_report")
    assert report.data["references"][0]["status"] == "verified"
