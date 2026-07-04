"""Tests for research_companion.agents.orchestrator — DAG execution with failure isolation."""
from __future__ import annotations

import asyncio

import pytest

from research_companion.agents import events
from research_companion.agents.base import Agent, AgentContext, AgentResult
from research_companion.agents.bus import Bus
from research_companion.agents.orchestrator import run_agents


def make_agent(agent_name, deps=(), fail=False, delay=0.0, record=None):
    class _A(Agent):
        name = agent_name
        role = f"test agent {agent_name}"
        depends_on = tuple(deps)

        async def run(self, ctx: AgentContext) -> AgentResult:
            if delay:
                await asyncio.sleep(delay)
            if record is not None:
                record.append(agent_name)
            if fail:
                raise RuntimeError(f"{agent_name} exploded")
            return AgentResult(agent=agent_name, ok=True, data={"ran": agent_name})

    return _A()


def _ctx():
    return AgentContext(paper_id="local:x", bus=Bus(), data={})


@pytest.mark.asyncio
async def test_dependencies_run_in_order_and_share_data():
    order: list[str] = []
    ctx = _ctx()
    results = await run_agents(
        [make_agent("b", deps=("a",), record=order), make_agent("a", record=order)], ctx
    )
    assert order == ["a", "b"]
    assert results["a"].ok and results["b"].ok
    assert ctx.data["a"] == {"ran": "a"}


@pytest.mark.asyncio
async def test_independent_agents_run_concurrently():
    ctx = _ctx()
    await run_agents([make_agent("a", delay=0.05), make_agent("b", delay=0.05)], ctx)
    kinds = [type(e).__name__ for e in ctx.bus.history]
    # Both starts precede both dones — they overlapped.
    assert kinds[:2] == ["AgentStarted", "AgentStarted"]


@pytest.mark.asyncio
async def test_failure_isolated_and_dependents_skipped():
    ctx = _ctx()
    results = await run_agents(
        [make_agent("a", fail=True), make_agent("b", deps=("a",)), make_agent("c")], ctx
    )
    assert not results["a"].ok and "exploded" in results["a"].error
    assert not results["b"].ok and results["b"].error == "dependency failed: a"
    assert results["c"].ok
    assert any(isinstance(e, events.AgentError) for e in ctx.bus.history)


@pytest.mark.asyncio
async def test_unknown_dependency_raises():
    with pytest.raises(ValueError, match="unknown dependency"):
        await run_agents([make_agent("a", deps=("ghost",))], _ctx())


@pytest.mark.asyncio
async def test_cycle_raises():
    with pytest.raises(ValueError, match="cycle"):
        await run_agents([make_agent("a", deps=("b",)), make_agent("b", deps=("a",))], _ctx())


@pytest.mark.asyncio
async def test_duplicate_agent_names_raise():
    with pytest.raises(ValueError, match="duplicate agent name"):
        await run_agents([make_agent("a"), make_agent("a")], _ctx())


@pytest.mark.asyncio
async def test_empty_agent_name_raises():
    with pytest.raises(ValueError, match="empty agent name"):
        await run_agents([make_agent("")], _ctx())
