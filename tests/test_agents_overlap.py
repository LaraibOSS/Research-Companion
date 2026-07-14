"""Tests for OverlapAgent + report inclusion + CLI — deterministic, no network."""
from __future__ import annotations

import argparse
import io
import json
from contextlib import redirect_stdout

import pytest

from research_companion import store
from research_companion.agents import events
from research_companion.agents.base import AgentContext, AgentResult
from research_companion.agents.bus import Bus
from research_companion.agents.overlap import OverlapAgent
from research_companion.cli import _cmd_check_overlap
from research_companion.report import build_report_json, render_report_html

_SHARED = ("Contrastive learning maximizes agreement between differently augmented "
           "views of the same data example via a contrastive loss in the latent "
           "space and improves representation quality across many downstream "
           "recognition benchmarks and datasets by a wide margin overall. ")


def _seed_two_overlapping_papers():
    store.PaperMetadata(paper_id="local:a", title="A", authors=[]).save()
    store.save_text("local:a", "Intro A. " + _SHARED + "Our unique method X here.")
    store.PaperMetadata(paper_id="local:b", title="B", authors=[]).save()
    store.save_text("local:b", "Intro B. " + _SHARED + "A different conclusion Y.")


@pytest.mark.asyncio
async def test_agent_flags_library_overlap():
    _seed_two_overlapping_papers()
    ctx = AgentContext(paper_id="local:a", bus=Bus(), data={})
    result = await OverlapAgent().run(ctx)

    assert result.ok
    assert result.data["summary"]["n_passages"] >= 1
    assert "local:b" in result.data["summary"]["papers"]
    kinds = [e.kind for e in ctx.bus.history if isinstance(e, events.Finding)]
    assert "overlap" in kinds


@pytest.mark.asyncio
async def test_agent_non_alarming_when_alone():
    store.PaperMetadata(paper_id="local:solo", title="S", authors=[]).save()
    store.save_text("local:solo", "A singular paper about a niche topic in its field.")
    ctx = AgentContext(paper_id="local:solo", bus=Bus(), data={})
    result = await OverlapAgent().run(ctx)
    assert result.ok
    assert result.data["findings"] == []


def test_report_includes_overlap_section():
    _seed_two_overlapping_papers()
    from research_companion.overlap import near_duplicate_passages
    data = near_duplicate_passages(
        store.load_text("local:a"),
        [("local:b", store.load_text("local:b"))],
        min_shingles=5,
    )
    results = {"overlap": AgentResult(agent="overlap", ok=True, data=data)}
    html = render_report_html(build_report_json("local:a", "A", results))
    assert "Near-duplicate passages" in html
    assert "local:b" in html


def test_cli_check_overlap_json_and_external_not_configured():
    _seed_two_overlapping_papers()
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = _cmd_check_overlap(argparse.Namespace(paper_id="local:a", external=True, json=True))
    assert rc == 0
    payload = json.loads(buf.getvalue())
    assert payload["paper_id"] == "local:a"
    assert payload["findings"]
    # --external with no provider registered: disabled, nothing sent
    assert payload["external"]["enabled"] is False
