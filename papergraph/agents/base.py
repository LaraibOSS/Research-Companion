"""Agent protocol: every agent is a thin, named unit with declared dependencies.

ctx.data is the shared blackboard. Keys starting with `_` carry injected
callables or non-JSON objects (graphs, lookups) and are never serialized;
plain keys hold each agent's JSON-safe result data.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from papergraph.agents.bus import Bus


@dataclass
class AgentContext:
    paper_id: str
    bus: Bus
    data: dict = field(default_factory=dict)


@dataclass
class AgentResult:
    agent: str
    ok: bool
    data: dict = field(default_factory=dict)
    error: str = ""


class Agent(ABC):
    name: str = ""
    role: str = ""
    depends_on: tuple[str, ...] = ()

    @abstractmethod
    async def run(self, ctx: AgentContext) -> AgentResult: ...
