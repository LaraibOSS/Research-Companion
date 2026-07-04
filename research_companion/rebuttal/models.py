"""Data models for the rebuttal pipeline. All JSON-safe via to_dict/asdict."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field


@dataclass
class Concern:
    concern_id: str
    reviewer: str
    text: str
    kind: str = ""


@dataclass
class Passage:
    location: str
    text: str
    score: float


@dataclass
class ResponseDraft:
    concern_id: str
    reply: str
    cited_passages: list[Passage] = field(default_factory=list)
    verified: bool = False
    unverified_spans: list[str] = field(default_factory=list)
    planned_revision: str = ""
    evidence_status: str = ""


@dataclass
class RebuttalReport:
    drafts: list[ResponseDraft] = field(default_factory=list)
    changelog: list[str] = field(default_factory=list)
    groups: list[list[str]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def concerns_to_json(concerns: list[Concern]) -> str:
    return json.dumps([asdict(c) for c in concerns], indent=2, ensure_ascii=False)


def concerns_from_json(blob: str) -> list[Concern]:
    return [Concern(**d) for d in json.loads(blob)]
