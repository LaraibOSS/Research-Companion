"""The catalogue as a user meets it: the `agents` command and GET /api/agents."""
from __future__ import annotations

import pytest

from research_companion.agents import catalog
from research_companion.agents.catalog import CARDS


def test_the_agents_command_lists_every_agent_with_its_cost(capsys):
    import json

    from research_companion import cli

    assert cli.main(["agents"]) == 0
    out = capsys.readouterr().out
    for card in CARDS:
        assert card.title in out
    assert "paid" in out and "free" in out
    # Agents nothing can start yet are said to be so, not listed as if usable.
    assert out.count("Not available from a command yet.") == sum(
        1 for c in CARDS if not c.reachable_from)

    assert cli.main(["agents", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert [a["name"] for a in payload["agents"]] == [r["name"] for r in catalog.catalog()]


def test_the_agents_endpoint_needs_no_workspace(isolated_papergraph_dir, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from research_companion import store
    from research_companion.agents.bus import Bus
    from research_companion.lab_api import create_lab_app

    monkeypatch.setattr(store, "active_workspace_id", lambda: None)
    resp = TestClient(create_lab_app(Bus())).get("/api/agents")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["agents"]) == len(CARDS)
    assert {"from", "to", "passes", "direct"} <= set(body["handoffs"][0])
