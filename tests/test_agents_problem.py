"""Tests for ProblemStatementAgent and PROBLEM_PROMPT — LLM injected, no network."""
from __future__ import annotations

import json

import networkx as nx
import pytest

from research_companion.agents import events
from research_companion.agents.base import AgentContext
from research_companion.agents.bus import Bus
from research_companion.discover import DiscoveredPaper

# ---------------------------------------------------------------------------
# Test 1: prompt formats + placeholders gone
# ---------------------------------------------------------------------------

def test_problem_prompt_formats_and_no_raw_placeholders():
    from research_companion.prompts import format_problem_prompt

    result = format_problem_prompt(
        statement="How can GNNs improve link prediction?",
        graph_context="- attention\n- graph neural network",
    )
    assert "How can GNNs improve link prediction?" in result
    assert "attention" in result
    assert "{statement}" not in result
    assert "{graph_context}" not in result


# ---------------------------------------------------------------------------
# Test 2: agent happy path
# ---------------------------------------------------------------------------

def _make_graph() -> nx.Graph:
    g = nx.Graph()
    # add 12 concept nodes; top-10 by degree will be n0..n9
    for i in range(12):
        g.add_node(f"c{i}", kind="concept", label=f"concept_{i}")
    # give n0-n9 higher degree than n10, n11
    for i in range(10):
        g.add_edge(f"c{i}", "hub")
    # hub node (no kind attr — should be ignored)
    return g


def _fake_llm(prompt: str) -> str:
    return json.dumps({
        "refined_statement": "How can attention-based GNNs improve link prediction?",
        "gaps": ["lack of temporal modelling", "scalability"],
        "next_steps": ["benchmark on OGB", "add temporal layers"],
    })


@pytest.mark.asyncio
async def test_problem_agent_happy_path():
    from research_companion.agents.problem import ProblemStatementAgent

    g = _make_graph()
    prior = [
        DiscoveredPaper(
            title=f"Paper {i}", authors=[], year=2024, citation_count=1,
            arxiv_id=None, doi=None, s2_id=None, url="", abstract="",
        )
        for i in range(15)  # 15 papers — agent must use only first 10
    ]

    ctx = AgentContext(paper_id="local:prob1", bus=Bus(), data={})
    ctx.data["_problem_statement"] = "How can GNNs improve link prediction?"
    ctx.data["_graph"] = g
    ctx.data["_priorart_papers"] = prior
    ctx.data["_llm"] = _fake_llm

    result = await ProblemStatementAgent().run(ctx)

    assert result.ok, result.error
    assert result.data["refined_statement"] == "How can attention-based GNNs improve link prediction?"
    assert isinstance(result.data["gaps"], list)
    assert isinstance(result.data["next_steps"], list)

    # exactly one Finding published with kind="problem_refined"
    findings = [e for e in ctx.bus.history if isinstance(e, events.Finding)]
    assert len(findings) == 1
    assert findings[0].kind == "problem_refined"
    assert "attention-based GNNs" in findings[0].summary


# ---------------------------------------------------------------------------
# Test 3: missing / empty statement → ok=False mentioning --problem
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_problem_agent_missing_statement():
    from research_companion.agents.problem import ProblemStatementAgent

    g = nx.Graph()
    ctx = AgentContext(paper_id="local:prob2", bus=Bus(), data={})
    ctx.data["_graph"] = g
    ctx.data["_priorart_papers"] = []
    ctx.data["_llm"] = _fake_llm
    # _problem_statement intentionally absent

    result = await ProblemStatementAgent().run(ctx)

    assert not result.ok
    assert "_problem_statement" in result.error


@pytest.mark.asyncio
async def test_problem_agent_empty_statement():
    from research_companion.agents.problem import ProblemStatementAgent

    g = nx.Graph()
    ctx = AgentContext(paper_id="local:prob3", bus=Bus(), data={})
    ctx.data["_problem_statement"] = ""   # present but empty
    ctx.data["_graph"] = g
    ctx.data["_priorart_papers"] = []
    ctx.data["_llm"] = _fake_llm

    result = await ProblemStatementAgent().run(ctx)

    assert not result.ok
    assert "_problem_statement" in result.error


# ---------------------------------------------------------------------------
# Test 4: bad JSON → ok=False with "problem" in error
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_problem_agent_bad_json():
    from research_companion.agents.problem import ProblemStatementAgent

    g = nx.Graph()
    ctx = AgentContext(paper_id="local:prob4", bus=Bus(), data={})
    ctx.data["_problem_statement"] = "some valid statement"
    ctx.data["_graph"] = g
    ctx.data["_priorart_papers"] = []
    ctx.data["_llm"] = lambda p: "NOT JSON AT ALL"

    result = await ProblemStatementAgent().run(ctx)

    assert not result.ok
    assert "problem" in result.error.lower()
