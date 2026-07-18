"""Connector protocol + shared helpers for domain connectors.

A connector resolves references, searches for prior art, and fetches OA full
text against one scholarly source. Network lives in injectable `_*` functions
on each concrete connector; this module holds only shared, pure-ish helpers.
"""
from __future__ import annotations

import time as _time
from collections.abc import Callable
from typing import Protocol, runtime_checkable

from research_companion.discover import DiscoveredPaper
from research_companion.refcheck.validate import Reference

USER_AGENT = "research-companion/0.1 (https://github.com/Laraib-Hasan-Future/Research-Companion)"

# A record dict: {title, authors, year, doi, arxiv_id, pmid, pmcid}.
Record = dict


@runtime_checkable
class Connector(Protocol):
    name: str
    def resolve(self, ref: Reference) -> Record | None: ...
    def search(self, query: str, *, limit: int) -> list[DiscoveredPaper]: ...
    def fetch_fulltext(self, ident: str) -> str | None: ...


class RateLimiter:
    """Minimal in-process spacing so we respect NCBI's 3 req/s etiquette.

    clock/sleep are injectable so tests never actually sleep.
    """

    def __init__(self, min_interval_s: float, *,
                 clock: Callable[[], float] = _time.monotonic,
                 sleep: Callable[[float], None] = _time.sleep) -> None:
        self._min = min_interval_s
        self._clock = clock
        self._sleep = sleep
        self._last: float | None = None

    def wait(self) -> None:
        now = self._clock()
        if self._last is not None:
            delta = now - self._last
            if delta < self._min:
                self._sleep(self._min - delta)
        self._last = self._clock()
