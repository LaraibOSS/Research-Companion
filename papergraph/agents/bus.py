"""In-process async pub/sub. Keeps full history; optionally mirrors to an EventLog."""
from __future__ import annotations

import asyncio

from papergraph.agents.events import EventLog


class Bus:
    def __init__(self, log: EventLog | None = None):
        self.history: list = []
        self._queues: list[asyncio.Queue] = []
        self._log = log

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._queues.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        try:
            self._queues.remove(q)
        except ValueError:
            pass

    async def publish(self, event) -> None:
        self.history.append(event)
        if self._log is not None:
            self._log.append(event)
        for q in self._queues:
            q.put_nowait(event)
