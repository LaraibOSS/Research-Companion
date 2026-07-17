"""Tests for research_companion.agents.events — typed events and the JSONL audit log."""
from __future__ import annotations

import json

from research_companion.agents import events


def test_event_to_dict_has_discriminator_and_fields():
    e = events.Finding(agent="citation", kind="suspect_ref", summary="1 suspect", data={"n": 1})
    d = events.event_to_dict(e)
    assert d["event"] == "finding"
    assert d["agent"] == "citation"
    assert d["kind"] == "suspect_ref"
    assert d["data"] == {"n": 1}


def test_event_to_dict_all_types_roundtrip_json():
    all_events = [
        events.AgentStarted(agent="a"),
        events.Finding(agent="a", kind="k", summary="s", data={}),
        events.AgentMessage(agent="a", to="b", content="hi"),
        events.AgentDone(agent="a", summary="ok"),
        events.AgentError(agent="a", error="boom"),
    ]
    names = [events.event_to_dict(e)["event"] for e in all_events]
    assert names == ["agent_started", "finding", "agent_message", "agent_done", "agent_error"]
    for e in all_events:
        json.dumps(events.event_to_dict(e))  # must not raise


def test_event_to_dict_falls_back_on_unknown_type():
    """Forward-safety: an unregistered event serializes (class name) instead of
    raising, so a newly-added event type can't abort a run from an un-guarded publish."""
    d = events.event_to_dict(object())
    assert d["event"] == "object"
    json.dumps(d)  # must remain JSON-serializable


def test_suggestions_updated_event_roundtrip():
    from research_companion.agents.events import SuggestionsUpdated, event_to_dict
    e = SuggestionsUpdated(draft_paper_id="local:d001", open=3, addressed=1, dismissed=0)
    d = event_to_dict(e)
    assert d["event"] == "suggestions_updated"
    assert d["draft_paper_id"] == "local:d001"
    assert d["open"] == 3
    assert d["addressed"] == 1
    assert d["dismissed"] == 0
    import json
    json.dumps(d)


def test_event_log_appends_jsonl(tmp_path):
    log = events.EventLog(tmp_path / "run.jsonl")
    log.append(events.AgentStarted(agent="ingest"))
    log.append(events.AgentDone(agent="ingest", summary="done"))
    lines = (tmp_path / "run.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0]) == {"event": "agent_started", "agent": "ingest"}
    assert json.loads(lines[1])["summary"] == "done"
