"""Tests for papergraph.agents.bus — in-process async pub/sub with history."""
from __future__ import annotations

import pytest

from papergraph.agents import events
from papergraph.agents.bus import Bus


@pytest.mark.asyncio
async def test_publish_reaches_all_subscribers_and_history():
    bus = Bus()
    q1, q2 = bus.subscribe(), bus.subscribe()
    e = events.AgentStarted(agent="ingest")
    await bus.publish(e)
    assert q1.get_nowait() is e
    assert q2.get_nowait() is e
    assert bus.history == [e]


@pytest.mark.asyncio
async def test_publish_writes_to_event_log(tmp_path):
    log = events.EventLog(tmp_path / "run.jsonl")
    bus = Bus(log=log)
    await bus.publish(events.AgentDone(agent="a", summary="ok"))
    assert "agent_done" in (tmp_path / "run.jsonl").read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_history_without_subscribers():
    bus = Bus()
    await bus.publish(events.AgentError(agent="a", error="x"))
    assert len(bus.history) == 1


@pytest.mark.asyncio
async def test_unsubscribe_stops_delivery_and_is_idempotent():
    bus = Bus()
    q = bus.subscribe()
    bus.unsubscribe(q)
    bus.unsubscribe(q)  # no-op, must not raise
    await bus.publish(events.AgentStarted(agent="a"))
    assert q.empty() and len(bus.history) == 1
