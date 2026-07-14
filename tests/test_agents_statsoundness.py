"""Tests for StatSoundnessAgent + report inclusion — deterministic, no LLM."""
from __future__ import annotations

import pytest

from research_companion import store
from research_companion.agents import events
from research_companion.agents.base import AgentContext, AgentResult
from research_companion.agents.bus import Bus
from research_companion.agents.statsoundness import StatSoundnessAgent
from research_companion.report import build_report_json, render_report_html
from research_companion.statcheck import check_stats


@pytest.mark.asyncio
async def test_agent_flags_decision_inconsistency():
    pid = "local:stat1"
    store.PaperMetadata(paper_id=pid, title="T", authors=[]).save()
    # Recomputes to ~ .04 (significant) but the paper claims p = .20.
    store.save_text(pid, "The result was reliable, t(48) = 2.10, p = .20.")

    ctx = AgentContext(paper_id=pid, bus=Bus(), data={})
    result = await StatSoundnessAgent().run(ctx)

    assert result.ok
    assert result.data["summary"]["n_decision_inconsistent"] == 1
    kinds = [e.kind for e in ctx.bus.history if isinstance(e, events.Finding)]
    assert "statsoundness" in kinds


@pytest.mark.asyncio
async def test_agent_non_alarming_on_stat_free_paper():
    pid = "local:stat2"
    store.PaperMetadata(paper_id=pid, title="T", authors=[]).save()
    store.save_text(pid, "A purely qualitative discussion with no statistics.")

    ctx = AgentContext(paper_id=pid, bus=Bus(), data={})
    result = await StatSoundnessAgent().run(ctx)

    assert result.ok
    assert result.data["findings"] == []
    assert result.data["summary"]["text"] == "no parseable statistics found"


def test_report_includes_statsoundness_section():
    data = check_stats("The effect held, t(48) = 2.10, p = .20.")
    results = {"statsoundness": AgentResult(agent="statsoundness", ok=True, data=data)}
    report = build_report_json("local:stat3", "Title", results)
    html = render_report_html(report)
    assert "Statistical Soundness" in html
    assert "recomputed" in html.lower()
