"""Socketless tests for the live dashboard (FastAPI TestClient)."""
from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from papergraph.agents import events  # noqa: E402
from papergraph.agents.bus import Bus  # noqa: E402
from papergraph.dashboard.server import create_app  # noqa: E402


def _client(bus, state):
    return TestClient(create_app(bus, state))


def test_index_serves_page():
    resp = _client(Bus(), {}).get("/")
    assert resp.status_code == 200
    assert "papergraph" in resp.text.lower()
    assert "EventSource" in resp.text


def test_state_endpoint():
    resp = _client(Bus(), {"lanes": {"ingest": "done"}, "done": True}).get("/state")
    assert resp.json() == {"lanes": {"ingest": "done"}, "done": True}


@pytest.mark.asyncio
async def test_events_replays_history_and_closes_when_done():
    bus = Bus()
    await bus.publish(events.AgentStarted(agent="ingest"))
    await bus.publish(events.AgentDone(agent="ingest", summary="ok"))
    state = {"done": True}
    with _client(bus, state).stream("GET", "/events") as resp:
        body = "".join(resp.iter_text())
    assert '"event": "agent_started"' in body or '"event":"agent_started"' in body
    assert "agent_done" in body
