"""In-process async pub/sub. Keeps full history; optionally mirrors to an EventLog."""
from __future__ import annotations

import asyncio
import contextlib

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
        with contextlib.suppress(ValueError):
            self._queues.remove(q)

    async def publish(self, event) -> None:
        self.history.append(event)
        if self._log is not None:
            self._log.append(event)
        # Cross-loop contract: queues may live on another thread's loop (e.g. the
        # dashboard server).  Delivery relies on the server's 0.2 s poll timeout;
        # put_nowait is best-effort — a RuntimeError or InvalidStateError from a
        # torn-down loop must never propagate to the agent runner.
        for q in self._queues:
            with contextlib.suppress(RuntimeError, asyncio.InvalidStateError):
                q.put_nowait(event)
