"""Tests for CitationAgent's biomedical connectors nudge wiring."""
from __future__ import annotations

import pytest

from research_companion.agents.base import AgentContext
from research_companion.agents.bus import Bus
from research_companion.agents.citation import CitationAgent


def _ctx_with_pmid_ref():
    ctx = AgentContext(paper_id="local:nudge1", bus=Bus(), data={})
    ctx.data["_extraction"] = {"related_work": ["Some Paper Title PMID: 123456 (2020)"]}
    ctx.data["_lookup"] = lambda ref: None
    return ctx


@pytest.mark.asyncio
async def test_nudge_present_when_connectors_off_and_pmid_ref(monkeypatch):
    import research_companion.settings as settings_mod

    monkeypatch.setattr(settings_mod, "get_settings", lambda: {"connectors": []})
    ctx = _ctx_with_pmid_ref()
    result = await CitationAgent().run(ctx)
    assert result.ok
    assert isinstance(result.data["connectors_nudge"], str)
    assert result.data["connectors_nudge"]


@pytest.mark.asyncio
async def test_nudge_absent_when_connectors_enabled(monkeypatch):
    import research_companion.settings as settings_mod

    monkeypatch.setattr(settings_mod, "get_settings", lambda: {"connectors": ["europepmc"]})
    ctx = _ctx_with_pmid_ref()
    result = await CitationAgent().run(ctx)
    assert result.ok
    assert result.data["connectors_nudge"] is None
