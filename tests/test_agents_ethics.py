"""Tests for EthicsAgent — deterministic, no LLM."""
from __future__ import annotations

import pytest

from research_companion import store
from research_companion.agents import events
from research_companion.agents.base import AgentContext
from research_companion.agents.bus import Bus
from research_companion.agents.ethics import EthicsAgent


@pytest.mark.asyncio
async def test_reports_present_and_missing():
    pid = "local:eth1"
    store.PaperMetadata(paper_id=pid, title="T", authors=[]).save()
    store.save_text(pid, "This work was supported by grant 1. Author contributions: equal.")

    ctx = AgentContext(paper_id=pid, bus=Bus(), data={})
    result = await EthicsAgent().run(ctx)

    assert result.ok
    assert "funding" in result.data["present"]
    assert "author_contributions" in result.data["present"]
    # conflict_of_interest expected by default but absent here.
    assert "conflict_of_interest" in result.data["missing_expected"]
    kinds = [e.kind for e in ctx.bus.history if isinstance(e, events.Finding)]
    assert "ethics_declarations" in kinds


@pytest.mark.asyncio
async def test_empty_paper_has_all_expected_missing():
    pid = "local:eth2"
    store.PaperMetadata(paper_id=pid, title="T", authors=[]).save()
    store.save_text(pid, "Body with no declarations.")

    ctx = AgentContext(paper_id=pid, bus=Bus(), data={})
    result = await EthicsAgent().run(ctx)

    assert result.ok
    assert set(result.data["missing_expected"]) == {
        "funding", "conflict_of_interest", "author_contributions"}
