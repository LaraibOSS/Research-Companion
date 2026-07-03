"""Typed agent events and the JSONL audit log.

Every observable thing an agent does is an event. The dashboard renders the
stream; the EventLog file is the run's audit trail.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

_KIND = {
    "AgentStarted": "agent_started",
    "Finding": "finding",
    "AgentMessage": "agent_message",
    "AgentDone": "agent_done",
    "AgentError": "agent_error",
}


@dataclass
class AgentStarted:
    agent: str


@dataclass
class Finding:
    agent: str
    kind: str
    summary: str
    data: dict = field(default_factory=dict)


@dataclass
class AgentMessage:
    agent: str
    to: str
    content: str


@dataclass
class AgentDone:
    agent: str
    summary: str = ""


@dataclass
class AgentError:
    agent: str
    error: str


def event_to_dict(event) -> dict:
    """Serialize an event with an `event` discriminator key."""
    return {"event": _KIND[type(event).__name__], **asdict(event)}


class EventLog:
    """Append-only JSONL log of events — the run's audit trail."""

    def __init__(self, path: Path | str):
        self.path = Path(path)

    def append(self, event) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event_to_dict(event), ensure_ascii=False) + "\n")
