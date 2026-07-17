"""Agent-runtime hardening: per-agent timeout, result-identity keying, event fallback."""
import asyncio
from dataclasses import dataclass

import pytest

from research_companion.agents import events, orchestrator
from research_companion.agents.base import Agent, AgentContext, AgentResult
from research_companion.agents.bus import Bus


class _Sleeper(Agent):
    name = "sleeper"
    depends_on = ()

    async def run(self, ctx):
        await asyncio.sleep(3600)
        return AgentResult(agent=self.name, ok=True)


class _Liar(Agent):
    name = "liar"
    depends_on = ()

    async def run(self, ctx):
        return AgentResult(agent="someone-else", ok=True, data={"x": 1})


@pytest.mark.asyncio
async def test_agent_timeout_is_isolated(monkeypatch):
    monkeypatch.setattr(orchestrator, "AGENT_TIMEOUT_SECONDS", 0.05)
    ctx = AgentContext(paper_id="p", bus=Bus(), data={})
    results = await orchestrator.run_agents([_Sleeper()], ctx)
    assert results["sleeper"].ok is False
    assert "timed out" in results["sleeper"].error


@pytest.mark.asyncio
async def test_result_keyed_by_scheduled_name_not_returned():
    ctx = AgentContext(paper_id="p", bus=Bus(), data={})
    results = await orchestrator.run_agents([_Liar()], ctx)
    assert "liar" in results and "someone-else" not in results
    assert results["liar"].ok and ctx.data["liar"] == {"x": 1}


def test_event_to_dict_falls_back_on_unknown_type():
    @dataclass
    class NewEvent:
        agent: str

    d = events.event_to_dict(NewEvent(agent="x"))
    assert d["event"] == "NewEvent" and d["agent"] == "x"
