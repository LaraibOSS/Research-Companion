"""Tests for research_companion.agents.base — Agent protocol, context, result."""
from __future__ import annotations

import json

import pytest

from research_companion.agents.base import Agent, AgentContext, AgentResult
from research_companion.agents.bus import Bus


class EchoAgent(Agent):
    name = "echo"
    role = "Echoes its input for testing."

    async def run(self, ctx: AgentContext) -> AgentResult:
        return AgentResult(agent=self.name, ok=True, data={"paper": ctx.paper_id})


@pytest.mark.asyncio
async def test_agent_subclass_runs_with_context():
    ctx = AgentContext(paper_id="local:abc", bus=Bus(), data={})
    result = await EchoAgent().run(ctx)
    assert result.ok
    assert result.data == {"paper": "local:abc"}
    assert EchoAgent.depends_on == ()


def test_agent_result_data_json_serializable():
    r = AgentResult(agent="a", ok=False, error="boom")
    json.dumps(r.data)
    assert r.error == "boom"


def test_agent_cannot_instantiate_without_run():
    class BadAgent(Agent):
        name = "bad"
        role = "missing run"

    with pytest.raises(TypeError):
        BadAgent()
