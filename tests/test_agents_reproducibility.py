"""Tests for ReproducibilityAgent — deterministic, no LLM."""
from __future__ import annotations

import pytest

from research_companion import store
from research_companion.agents import events
from research_companion.agents.base import AgentContext
from research_companion.agents.bus import Bus
from research_companion.agents.reproducibility import ReproducibilityAgent


@pytest.mark.asyncio
async def test_reports_level_and_links():
    pid = "local:repro1"
    store.PaperMetadata(paper_id=pid, title="T", authors=[]).save()
    store.save_text(pid, (
        "Our code is available at https://github.com/acme/repo and data at "
        "https://zenodo.org/record/1. We report hyperparameters and the GPU used."))

    ctx = AgentContext(paper_id=pid, bus=Bus(), data={})
    result = await ReproducibilityAgent().run(ctx)

    assert result.ok
    assert result.data["level"] == "high"
    assert result.data["code_links"] == ["https://github.com/acme/repo"]
    kinds = [e.kind for e in ctx.bus.history if isinstance(e, events.Finding)]
    assert "reproducibility" in kinds


@pytest.mark.asyncio
async def test_low_level_lists_missing():
    pid = "local:repro2"
    store.PaperMetadata(paper_id=pid, title="T", authors=[]).save()
    store.save_text(pid, "A short theoretical note with no artifacts.")

    ctx = AgentContext(paper_id=pid, bus=Bus(), data={})
    result = await ReproducibilityAgent().run(ctx)

    assert result.ok
    assert result.data["level"] == "low"
    assert result.data["missing"]


@pytest.mark.asyncio
async def test_folds_in_reference_links():
    pid = "local:repro3"
    store.PaperMetadata(paper_id=pid, title="T", authors=[]).save()
    store.save_text(pid, "See our supplementary code.")

    ctx = AgentContext(paper_id=pid, bus=Bus(), data={
        "citation": {"references": [{"title": "https://github.com/x/y"}]}})
    result = await ReproducibilityAgent().run(ctx)

    assert result.data["code_links"] == ["https://github.com/x/y"]
