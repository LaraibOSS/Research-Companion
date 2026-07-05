"""Zero-key offline demo for the Research Lab.

Replays the fixture event stream (tests/fixtures/lab_events.jsonl) through the
same Bus + _SeqRecorder shape the Lab server uses, and prints what a connecting
SSE client would see: papers added, sections built, graph deltas, one failure
with a retry hint, and strength updates.

No network calls, no API keys required.  If FastAPI is not installed the demo
degrades gracefully: events are still replayed through the Bus and printed, but
the HTTP server is not started.  Exit code 0 either way.  Runtime < 10 s.

Usage:
    python examples/demo_lab_offline.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

# Fixture lives next to tests/
_REPO_ROOT = Path(__file__).resolve().parent.parent
_FIXTURE = _REPO_ROOT / "tests" / "fixtures" / "lab_events.jsonl"


def _load_fixture_dicts() -> list[dict]:
    """Return every event in lab_events.jsonl as a plain dict."""
    lines = [ln.strip() for ln in _FIXTURE.read_text(encoding="utf-8").splitlines() if ln.strip()]
    return [json.loads(ln) for ln in lines]


def _dict_to_event(d: dict):
    """Convert a plain dict (from the JSONL fixture) to a typed event dataclass."""
    from research_companion.agents.events import (
        PaperAdded,
        SectionTreeBuilt,
        SectionExtracted,
        GraphDelta,
        StrengthUpdated,
        IngestFailed,
        IngestProgress,
        JobDone,
    )

    kind = d.get("event", "")
    if kind == "paper_added":
        return PaperAdded(paper_id=d["paper_id"], title=d["title"], source=d.get("source", ""))
    if kind == "section_tree_built":
        return SectionTreeBuilt(paper_id=d["paper_id"], n_sections=d["n_sections"])
    if kind == "section_extracted":
        return SectionExtracted(
            paper_id=d["paper_id"],
            section_id=d["section_id"],
            title=d["title"],
            counts=d.get("counts", {}),
        )
    if kind == "graph_delta":
        return GraphDelta(
            paper_id=d["paper_id"],
            nodes_added=d.get("nodes_added", []),
            edges_added=d.get("edges_added", []),
        )
    if kind == "strength_updated":
        return StrengthUpdated(
            paper_id=d["paper_id"],
            score=d.get("score"),
            band=d.get("band", ""),
            color=d.get("color", ""),
        )
    if kind == "ingest_failed":
        return IngestFailed(
            path=d["path"],
            stage=d.get("stage", ""),
            error=d.get("error", ""),
            paper_id=d.get("paper_id", ""),
        )
    if kind == "ingest_progress":
        return IngestProgress(done=d["done"], total=d["total"], current=d.get("current", ""))
    if kind == "job_done":
        return JobDone(job=d.get("job", "ingest"))
    # Unknown kind — return None (skipped by caller)
    return None


def _narrative(event) -> str | None:
    """Return a human-readable one-liner for an event, or None to skip."""
    from research_companion.agents.events import (
        PaperAdded,
        SectionTreeBuilt,
        SectionExtracted,
        GraphDelta,
        StrengthUpdated,
        IngestFailed,
        IngestProgress,
        JobDone,
    )

    if isinstance(event, PaperAdded):
        return f"  [paper_added]     {event.paper_id!r}  title={event.title!r}"
    if isinstance(event, SectionTreeBuilt):
        return f"  [section_tree]    {event.paper_id!r}  sections={event.n_sections}"
    if isinstance(event, SectionExtracted):
        counts_str = ", ".join(f"{k}={v}" for k, v in event.counts.items())
        return f"  [section]         {event.paper_id!r}  [{event.section_id}] {event.title!r}  {counts_str}"
    if isinstance(event, GraphDelta):
        return (
            f"  [graph_delta]     {event.paper_id!r}  "
            f"+{len(event.nodes_added)} nodes  +{len(event.edges_added)} edges"
        )
    if isinstance(event, StrengthUpdated):
        return (
            f"  [strength]        {event.paper_id!r}  "
            f"score={event.score}  band={event.band!r}  color={event.color!r}"
        )
    if isinstance(event, IngestFailed):
        return (
            f"  [ingest_failed]   path={event.path!r}  stage={event.stage!r}\n"
            f"                    error: {event.error}\n"
            f"                    retry hint: research-companion lab failures --retry {event.paper_id!r}"
        )
    if isinstance(event, IngestProgress):
        return f"  [progress]        {event.done}/{event.total}  current={event.current!r}"
    if isinstance(event, JobDone):
        return f"  [job_done]        job={event.job!r}"
    return None


def main() -> int:
    # Point RESEARCH_COMPANION_DIR at a temp dir before importing store
    tmp = tempfile.mkdtemp(prefix="rc-lab-demo-")
    os.environ["RESEARCH_COMPANION_DIR"] = tmp

    # Import after env var is set
    from research_companion.agents.bus import Bus

    print("Research Lab offline demo")
    print("=" * 60)
    print(f"Fixture : {_FIXTURE}")
    print(f"Temp dir: {tmp}")
    print()

    bus = Bus()  # no log needed for the demo

    fixture_dicts = _load_fixture_dicts()
    events = []
    for d in fixture_dicts:
        ev = _dict_to_event(d)
        if ev is not None:
            events.append(ev)

    print(f"Replaying {len(events)} events from fixture:")
    print()

    # Publish all events synchronously (Bus.publish is async but we can use history directly)
    # Use asyncio.run for a clean replay loop
    import asyncio

    async def _replay():
        for ev in events:
            await bus.publish(ev)

    asyncio.run(_replay())

    # Print narrative from bus.history
    node_total = 0
    edge_total = 0
    papers_added = []
    failures = []

    from research_companion.agents.events import GraphDelta, IngestFailed, PaperAdded

    for ev in bus.history:
        line = _narrative(ev)
        if line:
            print(line)
        if isinstance(ev, PaperAdded):
            papers_added.append(ev.paper_id)
        if isinstance(ev, GraphDelta):
            node_total += len(ev.nodes_added)
            edge_total += len(ev.edges_added)
        if isinstance(ev, IngestFailed):
            failures.append(ev)

    print()
    print("Summary")
    print("-" * 40)
    print(f"  Papers added  : {len(papers_added)}")
    print(f"  Graph nodes   : {node_total}")
    print(f"  Graph edges   : {edge_total}")
    print(f"  Failures      : {len(failures)}")
    if failures:
        for f in failures:
            print(f"    - {f.path!r}  ({f.error})")
            print(f"      retry: research-companion lab failures --retry {f.paper_id!r}")
    print()

    # Try to exercise create_lab_app if FastAPI is available
    try:
        from research_companion.lab_api import create_lab_app
        _fastapi_available = True
    except ImportError:
        _fastapi_available = False

    if _fastapi_available:
        print("FastAPI available — creating Lab app with replayed event history...")
        # Re-publish events into a fresh bus so the app sees history
        bus2 = Bus()

        async def _reload():
            for ev in events:
                await bus2.publish(ev)

        asyncio.run(_reload())
        app = create_lab_app(bus2)
        print(f"  Lab app created: {app.title!r}  routes={len(app.routes)}")
        print("  (To run the full server: pip install 'research-companion[server]'")
        print("   then: research-companion lab serve)")
    else:
        print("FastAPI not installed — server not started (Bus replay complete).")
        print("Install server deps: pip install 'research-companion[server]'")

    print()
    print("Demo complete.")
    print("  Zero API keys used / zero network calls made.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
