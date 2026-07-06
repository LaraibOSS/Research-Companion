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
    # Lab pipeline events (Task 8)
    "PaperAdded": "paper_added",
    "SectionTreeBuilt": "section_tree_built",
    "SectionExtracted": "section_extracted",
    "GraphDelta": "graph_delta",
    "AlignmentReady": "alignment_ready",
    "StrengthUpdated": "strength_updated",
    "IngestFailed": "ingest_failed",
    "IngestProgress": "ingest_progress",
    "JobDone": "job_done",
    "SuggestionsUpdated": "suggestions_updated",
}


@dataclass
class AgentStarted:
    agent: str


@dataclass
class Finding:
    agent: str
    kind: str
    summary: str
    data: dict[str, object] = field(default_factory=dict)


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


# ---------------------------------------------------------------------------
# Lab pipeline events (Task 8)
# ---------------------------------------------------------------------------

@dataclass
class PaperAdded:
    paper_id: str
    title: str
    source: str = ""


@dataclass
class SectionTreeBuilt:
    paper_id: str
    n_sections: int


@dataclass
class SectionExtracted:
    paper_id: str
    section_id: str
    title: str
    counts: dict = field(default_factory=dict)


@dataclass
class GraphDelta:
    paper_id: str
    nodes_added: list = field(default_factory=list)
    edges_added: list = field(default_factory=list)


@dataclass
class AlignmentReady:
    paper_id: str
    draft_paper_id: str
    verdict: str
    score: float


@dataclass
class StrengthUpdated:
    paper_id: str
    score: object  # float or None
    band: str
    color: str


@dataclass
class IngestFailed:
    path: str
    stage: str
    error: str
    paper_id: str = ""


@dataclass
class IngestProgress:
    done: int
    total: int
    current: str = ""


@dataclass
class JobDone:
    job: str = "ingest"


@dataclass
class SuggestionsUpdated:
    draft_paper_id: str
    open: int
    addressed: int
    dismissed: int


def event_to_dict(event) -> dict[str, object]:
    """Serialize an event with an `event` discriminator key."""
    kind = _KIND.get(type(event).__name__)
    if kind is None:
        raise ValueError(f"unknown event type: {type(event).__name__}")
    return {"event": kind, **asdict(event)}


class EventLog:
    """Append-only JSONL log of events — the run's audit trail."""

    def __init__(self, path: Path | str):
        self.path = Path(path)

    def append(self, event) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event_to_dict(event), ensure_ascii=False) + "\n")
