"""Typed outcome of trying to obtain a paper's PDF.

Replaces `bytes | None`. The None told the caller a file was absent; it never
told anyone WHY, so a paywall, a bot filter, a timeout and an HTML error page
all arrived as the same absence and were reported with the same sentence.

`Acquisition` borrows the vocabulary of signals.py (a Reason, provenance) but
is deliberately NOT a Signal: a Signal asserts a proposition about a paper,
this records the outcome of an operation.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AcquireReason(str, Enum):
    """Why we do not have the bytes. Six, because there are six genuinely
    different situations that used to share one sentence."""

    BLOCKED_BY_HOST = "blocked_by_host"      # free copy exists, robot refused
    PAYWALLED = "paywalled"                  # no free copy found
    NO_LOCATION_FOUND = "no_location_found"  # no index knows of any copy
    SOURCE_UNAVAILABLE = "source_unavailable"  # network/timeout, survived retries
    NOT_A_PDF = "not_a_pdf"                  # HTML or junk where a PDF was promised
    NOT_ATTEMPTED = "not_attempted"          # no usable identifier


class HostClass(str, Enum):
    """Ranked by how likely the host is to serve a robot. Repositories exist to
    be harvested; publishers are the ones that answer 403."""

    NATIVE = "native"          # arXiv, PMC — the path that never fails today
    REPOSITORY = "repository"  # institutional repos, Zenodo, CORE, HAL
    PREPRINT = "preprint"      # bioRxiv, SSRN, OpenReview
    PUBLISHER = "publisher"    # ACM, IEEE, Springer, Elsevier


@dataclass(frozen=True)
class Attempt:
    """One URL we tried, and what came back. Kept so a failure can say
    'tried 4 sources' rather than nothing."""

    url: str
    host_class: HostClass
    status: int | None          # HTTP status, or None if never reached
    outcome: str                # "pdf" | "403" | "not-pdf" | "timeout" | ...

    def to_dict(self) -> dict:
        return {"url": self.url, "host_class": self.host_class.value,
                "status": self.status, "outcome": self.outcome}

    @classmethod
    def from_dict(cls, d: dict) -> Attempt:
        return cls(url=d["url"], host_class=HostClass(d["host_class"]),
                   status=d.get("status"), outcome=d.get("outcome", ""))


# The one reason a person cannot usefully act on: retrying is the machine's job.
_MACHINE_OWNED = frozenset({AcquireReason.SOURCE_UNAVAILABLE})


@dataclass(frozen=True)
class Acquisition:
    obtained: bool
    reason: AcquireReason | None
    attempts: tuple[Attempt, ...] = ()
    source: str | None = None      # the URL the bytes came from

    def __post_init__(self) -> None:
        # Mirrors the signals.py invariant: a completed outcome cannot carry a
        # reason for not completing, and an incomplete one cannot lack it.
        if self.obtained and self.reason is not None:
            raise ValueError("an obtained acquisition cannot carry a reason")
        if not self.obtained and self.reason is None:
            raise ValueError("a failed acquisition must name a reason")

    @property
    def human_can_help(self) -> bool:
        """Queue membership, computed here so JS never re-derives it.

        PAYWALLED is included on purpose: we cannot know whether this user has
        institutional access, and deciding on their behalf that they do not is
        worse than offering the action.
        """
        if self.obtained:
            return False
        return self.reason not in _MACHINE_OWNED

    def to_dict(self) -> dict:
        return {
            "obtained": self.obtained,
            "reason": self.reason.value if self.reason else None,
            "human_can_help": self.human_can_help,
            "attempts": [a.to_dict() for a in self.attempts],
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Acquisition:
        return cls(
            obtained=bool(d.get("obtained")),
            reason=AcquireReason(d["reason"]) if d.get("reason") else None,
            attempts=tuple(Attempt.from_dict(a) for a in d.get("attempts", [])),
            source=d.get("source"),
        )
