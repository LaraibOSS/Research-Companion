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
    "IngestSkipped": "ingest_skipped",
    "JobDone": "job_done",
    "SuggestionsUpdated": "suggestions_updated",
    # Journey events (Task W3-T8)
    "DraftVersionAdded": "draft_version_added",
    # Gaps events (Task W3-T9)
    "GapsUpdated": "gaps_updated",
    # Deep-Research Report events (Phase 2, slice 2e-1)
    "ReportUpdated": "report_updated",
    # Embed events (Task W3-T11)
    "EmbeddingsReady": "embeddings_ready",
    # Workspace events (Task W4-B4)
    "WorkspaceChanged": "workspace_changed",
    # Citation coverage events (Task W5-C2)
    "CitationCoverageUpdated": "citation_coverage_updated",
    # Background-activity lifecycle (v0.5.2)
    "JobStarted": "job_started",
    "JobFinished": "job_finished",
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
    path: str = ""


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
class IngestSkipped:
    """An already-in-library file was skipped during folder ingest (Task F-I1)."""
    path: str
    paper_id: str = ""
    reason: str = "already in library"


@dataclass
class JobDone:
    job: str = "ingest"


@dataclass
class SuggestionsUpdated:
    draft_paper_id: str
    open: int
    addressed: int
    dismissed: int


# ---------------------------------------------------------------------------
# Journey events (Task W3-T8)
# ---------------------------------------------------------------------------

@dataclass
class DraftVersionAdded:
    paper_id: str
    version: int


@dataclass
class GapsUpdated:
    n_gaps: int
    n_open: int
    n_themes: int = 0


# ---------------------------------------------------------------------------
# Deep-Research Report events (Phase 2, slice 2e-1)
# ---------------------------------------------------------------------------

@dataclass
class ReportUpdated:
    """A deep-research report finished generating -- drives the 'report'
    topic so views/report.js refetches GET /api/report."""
    question_count: int
    topic: str


# ---------------------------------------------------------------------------
# Embed events (Task W3-T11)
# ---------------------------------------------------------------------------

@dataclass
class EmbeddingsReady:
    paper_id: str
    n_vectors: int


@dataclass
class WorkspaceChanged:
    workspace_id: str | None


@dataclass
class CitationCoverageUpdated:
    draft_paper_id: str
    total: int
    in_library: int
    available: int
    unchecked: int
    unresolved: int
    usable: int = 0


@dataclass
class JobStarted:
    """A background job began — drives the activity indicator.

    `target` carries the add-target (arXiv id / DOI) for kind=="add" so the
    citations panel can mark the matching row as downloading; empty otherwise.
    """
    job_id: str
    kind: str
    label: str
    target: str = ""


@dataclass
class JobFinished:
    """A background job ended (done or failed) — clears the activity entry."""
    job_id: str
    kind: str
    status: str


def event_to_dict(event) -> dict[str, object]:
    """Serialize an event with an `event` discriminator key.

    Registered event dataclasses use their kind; an unregistered type falls back
    to its class name (and best-effort field extraction) rather than raising, so a
    newly-added event type can never abort a run from an un-guarded publish.
    """
    name = type(event).__name__
    kind = _KIND.get(name)
    if kind is not None:
        return {"event": kind, **asdict(event)}
    try:
        payload = asdict(event)
    except TypeError:
        payload = dict(vars(event)) if hasattr(event, "__dict__") else {"repr": repr(event)}
    return {"event": name, **payload}


class EventLog:
    """Append-only JSONL log of events — the run's audit trail."""

    def __init__(self, path: Path | str):
        self.path = Path(path)

    def append(self, event) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event_to_dict(event), ensure_ascii=False) + "\n")
