# Agent Runtime + Core Agents Implementation Plan (Plan 1 of 5)

> **⚠️ Status: HISTORICAL / SUPERSEDED — do NOT execute.**
> This plan targets the former `papergraph` package and an early test baseline
> (~112 tests). The runtime it describes has long since shipped and evolved in
> the current `research_companion` package (1,860+ tests). It is retained only for
> design provenance. Do not run it against the current codebase, and do not copy
> its code snippets verbatim — several role/summary strings here predate the
> project's honesty conventions (e.g. "flags fabricated citations", "maps it onto
> the graph") and have since been corrected in the shipped agents. Any concurrency,
> validation, or event-contract concerns in this document are evaluated against
> the *current* code in the OSS-launch audit
> (`docs/superpowers/plans/2026-07-15-oss-launch-readiness.md`, Task 7), not here.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The async agent runtime (events, bus, orchestrator) plus three wrapper agents (Ingest, Citation, PriorArt) behind a new `papergraph review <paper_id>` CLI command.

**Architecture:** In-process asyncio agent orchestra. Typed events flow over a pub/sub Bus (which also keeps history); a DAG orchestrator runs all ready agents concurrently and isolates failures. Agents are thin wrappers over existing modules (`store`/`graph`, `refcheck`, `discover`). Spec: `docs/superpowers/specs/2026-06-29-agentic-review-design.md`.

**Tech Stack:** Python 3.10, asyncio, dataclasses, pytest + pytest-asyncio (already in dev deps), existing papergraph modules. No new runtime dependencies in this plan.

## Global Constraints

- Python ≥ 3.10 (`pyproject.toml`), line length 110, ruff rules `E,F,I,B,UP,SIM` (E501 ignored).
- TDD: write the failing test first, watch it fail, minimal code, watch it pass. Never skip the fail run.
- All LLM/network calls injectable and mocked in tests — zero real network in the test suite.
- Full suite must stay green after every task: `python -m pytest -q` (112 tests before this plan).
- `AgentResult.data` must stay JSON-serializable; non-JSON objects (graphs, callables) travel only in `ctx.data` under `_`-prefixed keys.
- Async tests: decorate with `@pytest.mark.asyncio` (pytest-asyncio ≥ 0.23 is installed). If pytest errors with "async def functions are not natively supported", add `asyncio_mode = "auto"` under `[tool.pytest.ini_options]` in `pyproject.toml` instead of decorating.
- Run commands from the repository root. Use forward-slash paths in cross-platform command examples.

---

### Task 1: Typed events + JSONL event log

**Files:**
- Create: `papergraph/agents/__init__.py`
- Create: `papergraph/agents/events.py`
- Test: `tests/test_agents_events.py`

**Interfaces:**
- Consumes: nothing.
- Produces: dataclasses `AgentStarted(agent)`, `Finding(agent, kind, summary, data)`, `AgentMessage(agent, to, content)`, `AgentDone(agent, summary)`, `AgentError(agent, error)`; function `event_to_dict(event) -> dict` (adds `"event"` discriminator key); class `EventLog(path)` with `append(event) -> None` writing one JSON line per event.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_agents_events.py
"""Tests for papergraph.agents.events — typed events and the JSONL audit log."""
from __future__ import annotations

import json

from papergraph.agents import events


def test_event_to_dict_has_discriminator_and_fields():
    e = events.Finding(agent="citation", kind="suspect_ref", summary="1 suspect", data={"n": 1})
    d = events.event_to_dict(e)
    assert d["event"] == "finding"
    assert d["agent"] == "citation"
    assert d["kind"] == "suspect_ref"
    assert d["data"] == {"n": 1}


def test_event_to_dict_all_types_roundtrip_json():
    all_events = [
        events.AgentStarted(agent="a"),
        events.Finding(agent="a", kind="k", summary="s", data={}),
        events.AgentMessage(agent="a", to="b", content="hi"),
        events.AgentDone(agent="a", summary="ok"),
        events.AgentError(agent="a", error="boom"),
    ]
    names = [events.event_to_dict(e)["event"] for e in all_events]
    assert names == ["agent_started", "finding", "agent_message", "agent_done", "agent_error"]
    for e in all_events:
        json.dumps(events.event_to_dict(e))  # must not raise


def test_event_log_appends_jsonl(tmp_path):
    log = events.EventLog(tmp_path / "run.jsonl")
    log.append(events.AgentStarted(agent="ingest"))
    log.append(events.AgentDone(agent="ingest", summary="done"))
    lines = (tmp_path / "run.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0]) == {"event": "agent_started", "agent": "ingest"}
    assert json.loads(lines[1])["summary"] == "done"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_agents_events.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'papergraph.agents'`

- [ ] **Step 3: Write minimal implementation**

```python
# papergraph/agents/__init__.py
"""Async agent runtime: events, bus, base protocol, orchestrator, and agents."""
```

```python
# papergraph/agents/events.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_agents_events.py -q`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add papergraph/agents/__init__.py papergraph/agents/events.py tests/test_agents_events.py
git commit -m "feat(agents): typed events and JSONL event log"
```

---

### Task 2: Async pub/sub bus with history

**Files:**
- Create: `papergraph/agents/bus.py`
- Test: `tests/test_agents_bus.py`

**Interfaces:**
- Consumes: event dataclasses from Task 1 (any object is publishable; the bus doesn't inspect them).
- Produces: `Bus` with `subscribe() -> asyncio.Queue`, `async publish(event) -> None` (appends to `history`, puts to every subscriber queue, and appends to the optional `EventLog`), attribute `history: list`, constructor `Bus(log: EventLog | None = None)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_agents_bus.py
"""Tests for papergraph.agents.bus — in-process async pub/sub with history."""
from __future__ import annotations

import pytest

from papergraph.agents import events
from papergraph.agents.bus import Bus


@pytest.mark.asyncio
async def test_publish_reaches_all_subscribers_and_history():
    bus = Bus()
    q1, q2 = bus.subscribe(), bus.subscribe()
    e = events.AgentStarted(agent="ingest")
    await bus.publish(e)
    assert q1.get_nowait() is e
    assert q2.get_nowait() is e
    assert bus.history == [e]


@pytest.mark.asyncio
async def test_publish_writes_to_event_log(tmp_path):
    log = events.EventLog(tmp_path / "run.jsonl")
    bus = Bus(log=log)
    await bus.publish(events.AgentDone(agent="a", summary="ok"))
    assert "agent_done" in (tmp_path / "run.jsonl").read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_history_without_subscribers():
    bus = Bus()
    await bus.publish(events.AgentError(agent="a", error="x"))
    assert len(bus.history) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_agents_bus.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'papergraph.agents.bus'`
(If instead you see "async def functions are not natively supported", apply the asyncio_mode note from Global Constraints, then re-run and confirm the ModuleNotFoundError failure.)

- [ ] **Step 3: Write minimal implementation**

```python
# papergraph/agents/bus.py
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

    async def publish(self, event) -> None:
        self.history.append(event)
        if self._log is not None:
            self._log.append(event)
        for q in self._queues:
            q.put_nowait(event)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_agents_bus.py -q`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add papergraph/agents/bus.py tests/test_agents_bus.py
git commit -m "feat(agents): async pub/sub bus with history and log mirroring"
```

---

### Task 3: Agent protocol, context, and result

**Files:**
- Create: `papergraph/agents/base.py`
- Test: `tests/test_agents_base.py`

**Interfaces:**
- Consumes: `Bus` (Task 2).
- Produces: `AgentContext(paper_id: str, bus: Bus, data: dict)` — `data` is the shared blackboard; `_`-prefixed keys hold injected callables/objects (never serialized). `AgentResult(agent: str, ok: bool, data: dict = {}, error: str = "")`. Abstract class `Agent` with class attrs `name: str`, `role: str`, `depends_on: tuple[str, ...] = ()` and abstract `async run(ctx: AgentContext) -> AgentResult`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_agents_base.py
"""Tests for papergraph.agents.base — Agent protocol, context, result."""
from __future__ import annotations

import json

import pytest

from papergraph.agents.base import Agent, AgentContext, AgentResult
from papergraph.agents.bus import Bus


class EchoAgent(Agent):
    name = "echo"
    role = "Echoes its input for testing."

    async def run(self, ctx: AgentContext) -> AgentResult:
        return AgentResult(agent=self.name, ok=True, data={"paper": ctx.paper_id})


@pytest.mark.asyncio
async def test_agent_subclass_runs_with_context():
    ctx = AgentContext(paper_id="local:abc", bus=Bus(), data={})
    result = await EchoAgent().run(ctx)
    assert result.ok
    assert result.data == {"paper": "local:abc"}
    assert EchoAgent.depends_on == ()


def test_agent_result_data_json_serializable():
    r = AgentResult(agent="a", ok=False, error="boom")
    json.dumps(r.data)
    assert r.error == "boom"


def test_agent_cannot_instantiate_without_run():
    class BadAgent(Agent):
        name = "bad"
        role = "missing run"

    with pytest.raises(TypeError):
        BadAgent()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_agents_base.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'papergraph.agents.base'`

- [ ] **Step 3: Write minimal implementation**

```python
# papergraph/agents/base.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_agents_base.py -q`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add papergraph/agents/base.py tests/test_agents_base.py
git commit -m "feat(agents): Agent protocol, context blackboard, and result types"
```

---

### Task 4: DAG orchestrator — parallel, failure-isolating

**Files:**
- Create: `papergraph/agents/orchestrator.py`
- Test: `tests/test_agents_orchestrator.py`

**Interfaces:**
- Consumes: `Agent`, `AgentContext`, `AgentResult` (Task 3); events (Task 1); `Bus` (Task 2).
- Produces: `async run_agents(agents: list[Agent], ctx: AgentContext) -> dict[str, AgentResult]`. Semantics: validates unknown/cyclic dependencies with `ValueError` before running anything; runs every ready agent concurrently; publishes `AgentStarted` before each run and `AgentDone`/`AgentError` after; an exception inside `run()` becomes `AgentResult(ok=False, error=str(exc))`; agents whose dependency finished `ok=False` are skipped with `error="dependency failed: <dep>"`; each ok result's `data` is copied to `ctx.data[agent.name]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_agents_orchestrator.py
"""Tests for papergraph.agents.orchestrator — DAG execution with failure isolation."""
from __future__ import annotations

import asyncio

import pytest

from papergraph.agents import events
from papergraph.agents.base import Agent, AgentContext, AgentResult
from papergraph.agents.bus import Bus
from papergraph.agents.orchestrator import run_agents


def make_agent(agent_name, deps=(), fail=False, delay=0.0, record=None):
    class _A(Agent):
        name = agent_name
        role = f"test agent {agent_name}"
        depends_on = tuple(deps)

        async def run(self, ctx: AgentContext) -> AgentResult:
            if delay:
                await asyncio.sleep(delay)
            if record is not None:
                record.append(agent_name)
            if fail:
                raise RuntimeError(f"{agent_name} exploded")
            return AgentResult(agent=agent_name, ok=True, data={"ran": agent_name})

    return _A()


def _ctx():
    return AgentContext(paper_id="local:x", bus=Bus(), data={})


@pytest.mark.asyncio
async def test_dependencies_run_in_order_and_share_data():
    order: list[str] = []
    ctx = _ctx()
    results = await run_agents(
        [make_agent("b", deps=("a",), record=order), make_agent("a", record=order)], ctx
    )
    assert order == ["a", "b"]
    assert results["a"].ok and results["b"].ok
    assert ctx.data["a"] == {"ran": "a"}


@pytest.mark.asyncio
async def test_independent_agents_run_concurrently():
    ctx = _ctx()
    await run_agents([make_agent("a", delay=0.05), make_agent("b", delay=0.05)], ctx)
    kinds = [type(e).__name__ for e in ctx.bus.history]
    # Both starts precede both dones — they overlapped.
    assert kinds[:2] == ["AgentStarted", "AgentStarted"]


@pytest.mark.asyncio
async def test_failure_isolated_and_dependents_skipped():
    ctx = _ctx()
    results = await run_agents(
        [make_agent("a", fail=True), make_agent("b", deps=("a",)), make_agent("c")], ctx
    )
    assert not results["a"].ok and "exploded" in results["a"].error
    assert not results["b"].ok and results["b"].error == "dependency failed: a"
    assert results["c"].ok
    assert any(isinstance(e, events.AgentError) for e in ctx.bus.history)


@pytest.mark.asyncio
async def test_unknown_dependency_raises():
    with pytest.raises(ValueError, match="unknown dependency"):
        await run_agents([make_agent("a", deps=("ghost",))], _ctx())


@pytest.mark.asyncio
async def test_cycle_raises():
    with pytest.raises(ValueError, match="cycle"):
        await run_agents([make_agent("a", deps=("b",)), make_agent("b", deps=("a",))], _ctx())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_agents_orchestrator.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'papergraph.agents.orchestrator'`

- [ ] **Step 3: Write minimal implementation**

```python
# papergraph/agents/orchestrator.py
"""Run agents as a dependency DAG: every ready agent runs concurrently,
one agent's failure never kills the run, and dependents of a failed agent
are skipped with an explanatory error.
"""
from __future__ import annotations

import asyncio

from papergraph.agents import events
from papergraph.agents.base import Agent, AgentContext, AgentResult


def _validate(agents: list[Agent]) -> None:
    names = {a.name for a in agents}
    for a in agents:
        for dep in a.depends_on:
            if dep not in names:
                raise ValueError(f"unknown dependency: {a.name} -> {dep}")
    # Kahn's algorithm for cycle detection.
    remaining = {a.name: set(a.depends_on) for a in agents}
    while remaining:
        ready = [n for n, deps in remaining.items() if not deps]
        if not ready:
            raise ValueError(f"cycle among agents: {sorted(remaining)}")
        for n in ready:
            del remaining[n]
        for deps in remaining.values():
            deps.difference_update(ready)


async def _run_one(agent: Agent, ctx: AgentContext) -> AgentResult:
    await ctx.bus.publish(events.AgentStarted(agent=agent.name))
    try:
        result = await agent.run(ctx)
    except Exception as exc:  # noqa: BLE001 — failure isolation is the contract
        result = AgentResult(agent=agent.name, ok=False, error=str(exc))
    if result.ok:
        ctx.data[agent.name] = result.data
        await ctx.bus.publish(events.AgentDone(agent=agent.name, summary=str(result.data)[:200]))
    else:
        await ctx.bus.publish(events.AgentError(agent=agent.name, error=result.error))
    return result


async def run_agents(agents: list[Agent], ctx: AgentContext) -> dict[str, AgentResult]:
    _validate(agents)
    pending = {a.name: a for a in agents}
    results: dict[str, AgentResult] = {}
    while pending:
        ready = [
            a for a in pending.values()
            if all(d in results for d in a.depends_on)
        ]
        skipped = []
        runnable = []
        for a in ready:
            failed = next((d for d in a.depends_on if not results[d].ok), None)
            if failed is not None:
                skipped.append((a, failed))
            else:
                runnable.append(a)
        for a, failed_dep in skipped:
            results[a.name] = AgentResult(
                agent=a.name, ok=False, error=f"dependency failed: {failed_dep}"
            )
            await ctx.bus.publish(events.AgentError(agent=a.name, error=results[a.name].error))
            del pending[a.name]
        if not runnable:
            continue
        outcomes = await asyncio.gather(*(_run_one(a, ctx) for a in runnable))
        for r in outcomes:
            results[r.agent] = r
            del pending[r.agent]
    return results
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_agents_orchestrator.py -q`
Expected: `5 passed`

- [ ] **Step 5: Run the whole suite**

Run: `python -m pytest -q`
Expected: all pass (112 pre-existing + 14 new so far), no regressions.

- [ ] **Step 6: Commit**

```bash
git add papergraph/agents/orchestrator.py tests/test_agents_orchestrator.py
git commit -m "feat(agents): DAG orchestrator with parallel execution and failure isolation"
```

---

### Task 5: IngestAgent — paper + knowledge graph

**Files:**
- Create: `papergraph/agents/ingest.py`
- Test: `tests/test_agents_ingest.py`

**Interfaces:**
- Consumes: `store.load_extraction(paper_id, prompt_sha=...)`, `prompts.extraction_prompt_sha256()`, `graph.build_graph()` (all existing); base types (Task 3); `Finding` (Task 1).
- Produces: `IngestAgent` — `name="ingest"`, `depends_on=()`. On success: `ctx.data["_graph"]` holds the `networkx.Graph`; `ctx.data["_extraction"]` holds the extraction dict; result data `{"graph_nodes": int, "graph_edges": int}`; publishes one `Finding(kind="graph_built")`. On missing extraction: `ok=False`, error mentions `papergraph build`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_agents_ingest.py
"""Tests for IngestAgent — loads extraction and builds the knowledge graph."""
from __future__ import annotations

import pytest

from papergraph import store
from papergraph.agents import events
from papergraph.agents.base import AgentContext
from papergraph.agents.bus import Bus
from papergraph.agents.ingest import IngestAgent
from papergraph.prompts import extraction_prompt_sha256


def _seed(paper_id="local:ingest0001", extraction=None):
    store.PaperMetadata(paper_id=paper_id, title="Seed Paper", authors=["A"]).save()
    store.save_extraction(
        paper_id,
        extraction or {"concepts": [{"name": "RAG", "definition": "d"}],
                       "methods": [], "datasets": [], "claims": [], "results": [],
                       "related_work": []},
        prompt_sha=extraction_prompt_sha256(),
    )
    return paper_id


@pytest.mark.asyncio
async def test_ingest_builds_graph_and_publishes_finding():
    paper_id = _seed()
    ctx = AgentContext(paper_id=paper_id, bus=Bus(), data={})
    result = await IngestAgent().run(ctx)
    assert result.ok
    assert result.data["graph_nodes"] > 0
    assert "_graph" in ctx.data and "_extraction" in ctx.data
    assert any(isinstance(e, events.Finding) and e.kind == "graph_built"
               for e in ctx.bus.history)


@pytest.mark.asyncio
async def test_ingest_fails_cleanly_without_extraction():
    ctx = AgentContext(paper_id="local:doesnotexist", bus=Bus(), data={})
    result = await IngestAgent().run(ctx)
    assert not result.ok
    assert "papergraph build" in result.error
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_agents_ingest.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'papergraph.agents.ingest'`

- [ ] **Step 3: Write minimal implementation**

```python
# papergraph/agents/ingest.py
"""IngestAgent: load the paper's cached extraction and build the knowledge graph."""
from __future__ import annotations

from papergraph.agents import events
from papergraph.agents.base import Agent, AgentContext, AgentResult


class IngestAgent(Agent):
    name = "ingest"
    role = "Loads the paper and builds the cross-paper knowledge graph."

    async def run(self, ctx: AgentContext) -> AgentResult:
        from papergraph.graph import build_graph
        from papergraph.prompts import extraction_prompt_sha256
        from papergraph.store import load_extraction

        ext = load_extraction(ctx.paper_id, prompt_sha=extraction_prompt_sha256())
        if ext is None:
            return AgentResult(
                agent=self.name, ok=False,
                error=f"no extraction for {ctx.paper_id}; run `papergraph build` first",
            )
        graph = build_graph()
        ctx.data["_graph"] = graph
        ctx.data["_extraction"] = ext
        data = {"graph_nodes": graph.number_of_nodes(), "graph_edges": graph.number_of_edges()}
        await ctx.bus.publish(events.Finding(
            agent=self.name, kind="graph_built",
            summary=f"graph: {data['graph_nodes']} nodes / {data['graph_edges']} edges",
            data=data,
        ))
        return AgentResult(agent=self.name, ok=True, data=data)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_agents_ingest.py -q`
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add papergraph/agents/ingest.py tests/test_agents_ingest.py
git commit -m "feat(agents): IngestAgent builds knowledge graph from stored extraction"
```

---

### Task 6: CitationAgent — refcheck as an agent

**Files:**
- Create: `papergraph/agents/citation.py`
- Test: `tests/test_agents_citation.py`

**Interfaces:**
- Consumes: `ctx.data["_extraction"]` (Task 5); `refcheck.parse.references_from_extraction`, `refcheck.validate.validate_bibliography`, `refcheck.retrieval.default_lookup` (existing); injectable lookup via `ctx.data["_lookup"]`.
- Produces: `CitationAgent` — `name="citation"`, `depends_on=("ingest",)`. Result data `{"counts": {"verified": n, "suspect": n, "unverified": n}, "references": [{"title", "status", "reasons"}]}`. Publishes one `Finding(kind="citation_report")` always, plus one `Finding(kind="bad_reference")` per non-verified reference.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_agents_citation.py
"""Tests for CitationAgent — wraps the deterministic reference validator."""
from __future__ import annotations

import pytest

from papergraph.agents import events
from papergraph.agents.base import AgentContext
from papergraph.agents.bus import Bus
from papergraph.agents.citation import CitationAgent


def _ctx_with_extraction(related_work, lookup):
    ctx = AgentContext(paper_id="local:x", bus=Bus(), data={})
    ctx.data["_extraction"] = {"related_work": related_work}
    ctx.data["_lookup"] = lookup
    return ctx


def _known_title_lookup(known):
    def _lookup(ref):
        if known.lower() in ref.title.lower():
            return {"title": ref.title, "authors": [], "year": 2017,
                    "doi": None, "arxiv_id": None}
        return None
    return _lookup


@pytest.mark.asyncio
async def test_citation_agent_reports_counts_and_flags_bad_refs():
    ctx = _ctx_with_extraction(
        ["Attention Is All You Need", "A Totally Fabricated Paper"],
        _known_title_lookup("Attention Is All You Need"),
    )
    result = await CitationAgent().run(ctx)
    assert result.ok
    assert result.data["counts"] == {"verified": 1, "suspect": 0, "unverified": 1}
    bad = [e for e in ctx.bus.history
           if isinstance(e, events.Finding) and e.kind == "bad_reference"]
    assert len(bad) == 1
    assert "Fabricated" in bad[0].summary


@pytest.mark.asyncio
async def test_citation_agent_empty_bibliography_is_ok():
    ctx = _ctx_with_extraction([], _known_title_lookup("x"))
    result = await CitationAgent().run(ctx)
    assert result.ok
    assert result.data["counts"] == {"verified": 0, "suspect": 0, "unverified": 0}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_agents_citation.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'papergraph.agents.citation'`

- [ ] **Step 3: Write minimal implementation**

```python
# papergraph/agents/citation.py
"""CitationAgent: validate the paper's bibliography against live scholarly databases."""
from __future__ import annotations

from papergraph.agents import events
from papergraph.agents.base import Agent, AgentContext, AgentResult


class CitationAgent(Agent):
    name = "citation"
    role = "Verifies every reference against CrossRef/OpenAlex; flags fabricated citations."
    depends_on = ("ingest",)

    async def run(self, ctx: AgentContext) -> AgentResult:
        from papergraph.refcheck.parse import references_from_extraction
        from papergraph.refcheck.retrieval import default_lookup
        from papergraph.refcheck.validate import validate_bibliography

        ext = ctx.data["_extraction"]
        refs = references_from_extraction(ext)
        lookup = ctx.data.get("_lookup") or default_lookup()
        report = validate_bibliography(refs, lookup)

        for ref, verdict in report.entries:
            if verdict.status != "verified":
                await ctx.bus.publish(events.Finding(
                    agent=self.name, kind="bad_reference",
                    summary=f"[{verdict.status}] {ref.title}",
                    data={"title": ref.title, "status": verdict.status,
                          "reasons": verdict.reasons},
                ))
        counts = report.counts()
        await ctx.bus.publish(events.Finding(
            agent=self.name, kind="citation_report",
            summary=(f"{counts['verified']} verified · {counts['suspect']} suspect · "
                     f"{counts['unverified']} unverified"),
            data={"counts": counts},
        ))
        return AgentResult(agent=self.name, ok=True, data={
            "counts": counts,
            "references": [
                {"title": ref.title, "status": v.status, "reasons": v.reasons}
                for ref, v in report.entries
            ],
        })
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_agents_citation.py -q`
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add papergraph/agents/citation.py tests/test_agents_citation.py
git commit -m "feat(agents): CitationAgent wraps refcheck bibliography validation"
```

---

### Task 7: PriorArtAgent — related-work discovery

**Files:**
- Create: `papergraph/agents/priorart.py`
- Test: `tests/test_agents_priorart.py`

**Interfaces:**
- Consumes: `ctx.data["_extraction"]` (Task 5); `discover.search_topic(query, *, limit=...) -> list[DiscoveredPaper]` (existing; fields `title, authors, year, citation_count, arxiv_id, doi, s2_id, url`); paper title via `store.PaperMetadata.load(paper_id)`; injectable search via `ctx.data["_search"]` (callable `(query: str) -> list[DiscoveredPaper]`).
- Produces: `PriorArtAgent` — `name="priorart"`, `depends_on=("ingest",)`. Result data `{"count": n, "papers": [{"title", "year", "id"}]}` where `id` = arxiv/doi/s2 id or "". Query = paper title + top-3 concept names. Publishes one `Finding(kind="prior_art")`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_agents_priorart.py
"""Tests for PriorArtAgent — maps related work via scholarly search."""
from __future__ import annotations

import pytest

from papergraph import store
from papergraph.agents import events
from papergraph.agents.base import AgentContext
from papergraph.agents.bus import Bus
from papergraph.agents.priorart import PriorArtAgent
from papergraph.discover import DiscoveredPaper


def _paper(title, year=2024, arxiv_id="2401.00001"):
    return DiscoveredPaper(title=title, authors=["A"], year=year, citation_count=10,
                           arxiv_id=arxiv_id, doi=None, s2_id=None, url="")


@pytest.mark.asyncio
async def test_priorart_returns_related_papers_and_query_uses_concepts():
    store.PaperMetadata(paper_id="local:pa1", title="Graph RAG Survey", authors=[]).save()
    seen_queries = []

    def fake_search(query):
        seen_queries.append(query)
        return [_paper("GraphRAG"), _paper("LightRAG", arxiv_id=None)]

    ctx = AgentContext(paper_id="local:pa1", bus=Bus(), data={})
    ctx.data["_extraction"] = {"concepts": [{"name": "Knowledge graph"}, {"name": "RAG"}]}
    ctx.data["_search"] = fake_search
    result = await PriorArtAgent().run(ctx)

    assert result.ok
    assert result.data["count"] == 2
    assert result.data["papers"][0] == {"title": "GraphRAG", "year": 2024, "id": "2401.00001"}
    assert "Graph RAG Survey" in seen_queries[0]
    assert "Knowledge graph" in seen_queries[0]
    assert any(isinstance(e, events.Finding) and e.kind == "prior_art"
               for e in ctx.bus.history)


@pytest.mark.asyncio
async def test_priorart_empty_results_still_ok():
    store.PaperMetadata(paper_id="local:pa2", title="T", authors=[]).save()
    ctx = AgentContext(paper_id="local:pa2", bus=Bus(), data={})
    ctx.data["_extraction"] = {"concepts": []}
    ctx.data["_search"] = lambda q: []
    result = await PriorArtAgent().run(ctx)
    assert result.ok and result.data["count"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_agents_priorart.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'papergraph.agents.priorart'`

- [ ] **Step 3: Write minimal implementation**

```python
# papergraph/agents/priorart.py
"""PriorArtAgent: find and map related work for the paper."""
from __future__ import annotations

from papergraph.agents import events
from papergraph.agents.base import Agent, AgentContext, AgentResult


class PriorArtAgent(Agent):
    name = "priorart"
    role = "Searches scholarly databases for related work and maps it onto the graph."
    depends_on = ("ingest",)

    async def run(self, ctx: AgentContext) -> AgentResult:
        from papergraph.discover import search_topic
        from papergraph.store import PaperMetadata

        meta = PaperMetadata.load(ctx.paper_id)
        title = meta.title if meta else ""
        concepts = [c.get("name", "") for c in ctx.data["_extraction"].get("concepts", [])]
        query = " ".join([title] + [c for c in concepts[:3] if c]).strip()

        search = ctx.data.get("_search") or (lambda q: search_topic(q, limit=15))
        found = search(query)
        papers = [
            {"title": p.title, "year": p.year,
             "id": p.arxiv_id or p.doi or p.s2_id or ""}
            for p in found
        ]
        await ctx.bus.publish(events.Finding(
            agent=self.name, kind="prior_art",
            summary=f"{len(papers)} related papers mapped",
            data={"count": len(papers)},
        ))
        return AgentResult(agent=self.name, ok=True,
                           data={"count": len(papers), "papers": papers})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_agents_priorart.py -q`
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add papergraph/agents/priorart.py tests/test_agents_priorart.py
git commit -m "feat(agents): PriorArtAgent discovers related work via injectable search"
```

---

### Task 8: `papergraph review` CLI command + end-to-end test

**Files:**
- Modify: `papergraph/cli.py` (add `_cmd_review` before `_build_parser`, register subparser after the `refcheck` block at the end of `_build_parser`)
- Test: `tests/test_cli_review.py`

**Interfaces:**
- Consumes: `run_agents` (Task 4); `IngestAgent`, `CitationAgent`, `PriorArtAgent` (Tasks 5–7); existing CLI patterns (`_cmd_refcheck`, `main`).
- Produces: `papergraph review <paper_id> [--json]`. Human output: one `▸ <name>  <ok|FAILED>  <summary>` lane per agent (order: ingest, citation, priorart) + trailing summary line. `--json`: `{"paper_id", "agents": {name: {"ok", "data", "error"}}}`. Exit 0 if all agents ok, else 1. Tests inject `_lookup`/`_search` through a `ctx_overrides` hook: `_cmd_review` builds `ctx.data` from module-level `REVIEW_CONTEXT_OVERRIDES: dict` (default empty) so tests can monkeypatch it.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_review.py
"""End-to-end test for `papergraph review` — all network injected, no LLM."""
from __future__ import annotations

import json

import pytest

from papergraph import cli, store
from papergraph.discover import DiscoveredPaper
from papergraph.prompts import extraction_prompt_sha256


def _seed():
    paper_id = "local:review00001"
    store.PaperMetadata(paper_id=paper_id, title="Graph RAG Survey", authors=["A"]).save()
    store.save_extraction(
        paper_id,
        {"concepts": [{"name": "RAG", "definition": "d"}], "methods": [], "datasets": [],
         "claims": [], "results": [],
         "related_work": ["Attention Is All You Need", "A Fabricated Paper Title"]},
        prompt_sha=extraction_prompt_sha256(),
    )
    return paper_id


def _overrides():
    def lookup(ref):
        if "attention" in ref.title.lower():
            return {"title": ref.title, "authors": [], "year": 2017,
                    "doi": None, "arxiv_id": None}
        return None

    def search(query):
        return [DiscoveredPaper(title="GraphRAG", authors=[], year=2024, citation_count=5,
                                arxiv_id="2404.00001", doi=None, s2_id=None, url="")]

    return {"_lookup": lookup, "_search": search}


def test_review_cli_runs_all_agents(monkeypatch: pytest.MonkeyPatch, capsys):
    paper_id = _seed()
    monkeypatch.setattr(cli, "REVIEW_CONTEXT_OVERRIDES", _overrides())
    rc = cli.main(["review", paper_id])
    out = capsys.readouterr().out
    assert rc == 0
    for lane in ("ingest", "citation", "priorart"):
        assert lane in out
    assert "1 verified" in out and "1 unverified" in out
    assert "1 related papers" in out


def test_review_cli_json(monkeypatch: pytest.MonkeyPatch, capsys):
    paper_id = _seed()
    monkeypatch.setattr(cli, "REVIEW_CONTEXT_OVERRIDES", _overrides())
    rc = cli.main(["review", paper_id, "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["paper_id"] == paper_id
    assert payload["agents"]["citation"]["ok"] is True
    assert payload["agents"]["citation"]["data"]["counts"]["verified"] == 1


def test_review_cli_fails_without_extraction(capsys):
    rc = cli.main(["review", "local:nothere"])
    assert rc == 1
    out = capsys.readouterr().out
    assert "FAILED" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cli_review.py -q`
Expected: FAIL — argparse error `invalid choice: 'review'` (SystemExit: 2)

- [ ] **Step 3: Write minimal implementation**

Add to `papergraph/cli.py` immediately before `def _build_parser()`:

```python
# Test seam: tests monkeypatch this to inject offline lookup/search callables.
REVIEW_CONTEXT_OVERRIDES: dict = {}


def _cmd_review(args: argparse.Namespace) -> int:
    import asyncio

    from papergraph.agents.base import AgentContext
    from papergraph.agents.bus import Bus
    from papergraph.agents.citation import CitationAgent
    from papergraph.agents.ingest import IngestAgent
    from papergraph.agents.orchestrator import run_agents
    from papergraph.agents.priorart import PriorArtAgent

    agents = [IngestAgent(), CitationAgent(), PriorArtAgent()]
    ctx = AgentContext(paper_id=args.paper_id, bus=Bus(),
                       data=dict(REVIEW_CONTEXT_OVERRIDES))
    results = asyncio.run(run_agents(agents, ctx))

    if args.json:
        payload = {
            "paper_id": args.paper_id,
            "agents": {name: {"ok": r.ok, "data": r.data, "error": r.error}
                       for name, r in results.items()},
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0 if all(r.ok for r in results.values()) else 1

    summaries = {
        "ingest": lambda d: f"graph: {d['graph_nodes']} nodes / {d['graph_edges']} edges",
        "citation": lambda d: (f"{d['counts']['verified']} verified · "
                               f"{d['counts']['suspect']} suspect · "
                               f"{d['counts']['unverified']} unverified"),
        "priorart": lambda d: f"{d['count']} related papers",
    }
    for agent in agents:
        r = results[agent.name]
        if r.ok:
            print(f"  {agent.name:<10} done    {summaries[agent.name](r.data)}")
        else:
            print(f"  {agent.name:<10} FAILED  {r.error}")
    ok = all(r.ok for r in results.values())
    print(f"\n{'All agents completed.' if ok else 'Some agents failed.'}")
    return 0 if ok else 1
```

Add to `_build_parser()` after the `refcheck` subparser block, before `return p`:

```python
    prv = sub.add_parser("review",
                         help="Run the agent team over a paper (ingest, citations, prior art)")
    prv.add_argument("paper_id", help="ID of a paper already built (see `papergraph list`)")
    prv.add_argument("--json", action="store_true", help="JSON output")
    prv.set_defaults(func=_cmd_review)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_cli_review.py -q`
Expected: `3 passed`

- [ ] **Step 5: Run the whole suite + lint**

Run: `python -m pytest -q && python -m ruff check papergraph/agents papergraph/cli.py tests/test_agents_*.py tests/test_cli_review.py`
Expected: all tests pass (135 total: 112 pre-existing + 23 new), `All checks passed!`
If ruff flags import sorting (I001), run `python -m ruff check --fix <paths>` and re-run tests.

- [ ] **Step 6: Commit**

```bash
git add papergraph/cli.py tests/test_cli_review.py
git commit -m "feat(cli): papergraph review runs the agent team end-to-end"
```

---

## Verification (whole plan)

1. `python -m pytest -q` — 135 passing, zero regressions.
2. `python -m ruff check papergraph tests` — clean (3 pre-existing F541 in `_cmd_discover` are known and out of scope).
3. Live smoke (offline): seed a paper as in `tests/test_cli_review.py::_seed`, then `papergraph review local:review00001` → three lanes print, exit 0.
4. Event-log audit: after the smoke run, `ctx.bus.history` behavior is covered by tests; the JSONL file wiring lands with the dashboard plan (Plan 4), which subscribes `EventLog` to the Bus at CLI level.

## What later plans consume from this one

- Plan 2 (Novelty/Confidence/Benchmark): `Agent`/`AgentContext`/`AgentResult`, `run_agents`, `ctx.data["_graph"]`, `ctx.data["_extraction"]`, `results["priorart"].data["papers"]`.
- Plan 3 (Rebuttal): same base types; `ctx.data["_extraction"]`; `Finding` events.
- Plan 4 (Dashboard/Report): `Bus.subscribe()`, `EventLog`, `event_to_dict`, lane names/roles.
- Plan 5 (Tier-2/eval/packaging): the `review` command registration pattern; `REVIEW_CONTEXT_OVERRIDES` seam for offline evaluation harnesses.
