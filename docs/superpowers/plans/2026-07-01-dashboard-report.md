# Dashboard + Report Implementation Plan (Plan 4 of 5)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans. Checkbox steps.

**Goal:** The demo's visual layer: a self-contained HTML/JSON report of every agent's verdicts, a live browser dashboard (FastAPI + SSE) streaming the Bus, `--serve`/`--report` on `papergraph review`, per-run JSONL event logs, plus two carried runtime fixes (Bus.unsubscribe, citation_report payload enrichment).

**Architecture — one documented deviation from spec §3:** the spec lists a ReportAgent depending on all lanes; implemented instead as a **pure post-run builder** (`papergraph/report.py`) called by the CLI after `run_agents` returns — because an agent whose dependency failed gets *skipped*, and the report must exist precisely when lanes fail. Rationale recorded here and in the ledger.

**Tech Stack:** fastapi + uvicorn (new optional deps, extras `[demo]`; already pip-installed in the dev env), `fastapi.testclient` for socketless route tests (httpx already a core dep), vanilla-JS single-page dashboard (no build step), stdlib elsewhere.

## Global Constraints
- Python ≥ 3.10, ruff `E,F,I,B,UP,SIM` line 110, `zip(strict=)`. TDD per task (fail → watch → pass); RED/GREEN in report.
- No network sockets in tests (TestClient only); no LLM in tests.
- All new user-facing CLI strings ASCII-safe (Windows cp1252/cp437 consoles).
- Commit ONLY named files per task; NEVER `git add -A`/`.`/`-a`.
- Baseline at plan start: **183 passed** (+ any Plan-3 final-review fix deltas — use the observed count).
- Report/dashboard must render correctly when some lanes failed or were skipped (`--fast`).

---

### Task 1: Runtime carry-overs — Bus.unsubscribe, run event-logs, citation_report enrichment

**Files:** Modify `papergraph/agents/bus.py`, `papergraph/agents/citation.py`, `papergraph/cli.py` · Tests: extend `tests/test_agents_bus.py`, `tests/test_agents_citation.py`, `tests/test_cli_review.py`

**Interfaces:**
- `Bus.unsubscribe(q: asyncio.Queue) -> None` (idempotent; unknown queue is a no-op).
- CitationAgent's `citation_report` Finding `data` gains `"references"`: the same per-ref list as the result (capped at 50 entries).
- `_cmd_review` constructs `Bus(log=EventLog(path))` where path = `store.papergraph_dir()/"runs"/f"{paper_id.replace(':','_')}-{int(time.time())}.jsonl"` (mkdir parents). `time` already imported in cli.py.

- [ ] **Step 1: failing tests** — append:

```python
# tests/test_agents_bus.py
@pytest.mark.asyncio
async def test_unsubscribe_stops_delivery_and_is_idempotent():
    bus = Bus()
    q = bus.subscribe()
    bus.unsubscribe(q)
    bus.unsubscribe(q)  # no-op, must not raise
    await bus.publish(events.AgentStarted(agent="a"))
    assert q.empty() and len(bus.history) == 1
```

```python
# tests/test_agents_citation.py
@pytest.mark.asyncio
async def test_citation_report_finding_carries_references():
    ctx = _ctx_with_extraction(["Attention Is All You Need"],
                               _known_title_lookup("Attention Is All You Need"))
    await CitationAgent().run(ctx)
    report = next(e for e in ctx.bus.history
                  if isinstance(e, events.Finding) and e.kind == "citation_report")
    assert report.data["references"][0]["status"] == "verified"
```

```python
# tests/test_cli_review.py
def test_review_writes_run_event_log(monkeypatch: pytest.MonkeyPatch, capsys):
    paper_id = _seed()
    monkeypatch.setattr(cli, "REVIEW_CONTEXT_OVERRIDES", _overrides())
    rc = cli.main(["review", paper_id, "--fast"])
    assert rc == 0
    runs = list((store.papergraph_dir() / "runs").glob("*.jsonl"))
    assert runs, "expected a run event log"
    first = json.loads(runs[0].read_text(encoding="utf-8").splitlines()[0])
    assert first["event"] in ("agent_started", "finding")
```

- [ ] **Step 2: run, watch fail** — unsubscribe: AttributeError; references: KeyError; run-log: empty glob.
- [ ] **Step 3: implement**
  - bus.py: `def unsubscribe(self, q): 
        try: self._queues.remove(q)
        except ValueError: pass`
  - citation.py: `data={"counts": counts, "references": ref_list[:50]}` where `ref_list` is the same list built for the result (build it once, before the Finding publish).
  - cli.py `_cmd_review`: before constructing the Bus —

```python
    from papergraph.agents.events import EventLog
    from papergraph.store import papergraph_dir

    runs_dir = papergraph_dir() / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    log_path = runs_dir / f"{args.paper_id.replace(':', '_')}-{int(time.time())}.jsonl"
    ctx = AgentContext(paper_id=args.paper_id, bus=Bus(log=EventLog(log_path)),
                       data=dict(REVIEW_CONTEXT_OVERRIDES))
```

- [ ] **Step 4: run, watch pass** — the three test files green.
- [ ] **Step 5: full suite; commit** — `git add papergraph/agents/bus.py papergraph/agents/citation.py papergraph/cli.py tests/test_agents_bus.py tests/test_agents_citation.py tests/test_cli_review.py` · msg `feat(agents): bus unsubscribe, run event logs, enriched citation_report`

---

### Task 2: Report builder

**Files:** Create `papergraph/report.py` · Test `tests/test_report.py`

**Interfaces:** `build_report_json(paper_id: str, title: str, results: dict[str, "AgentResult"]) -> dict` — `{"paper_id","title","lanes":{name:{"ok","error","data"}},"generated_by":"papergraph"}` (every lane present, failed ones carry error). `render_report_html(report: dict) -> str` — self-contained HTML (inline CSS, no external assets): header with title/paper_id; a lane card per agent (green OK / red FAILED); if present: citation counts + non-verified refs list, novelty claims table (verdict/confidence/evidence_verified), confidence cards (score ± band), benchmark suggestions, rebuttal drafts (verified badge + reply). Escape all dynamic text with `html.escape`. Must render fine with only 3 lanes (--fast) or failed lanes.

- [ ] **Step 1: failing test**

```python
# tests/test_report.py
"""Tests for the post-run report builder."""
from __future__ import annotations

import json

from papergraph.agents.base import AgentResult
from papergraph.report import build_report_json, render_report_html


def _results():
    return {
        "ingest": AgentResult(agent="ingest", ok=True, data={"graph_nodes": 3, "graph_edges": 2}),
        "citation": AgentResult(agent="citation", ok=True, data={
            "counts": {"verified": 1, "suspect": 0, "unverified": 1},
            "references": [{"title": "Real Paper", "status": "verified", "reasons": []},
                            {"title": "Fake <Paper>", "status": "unverified",
                             "reasons": ["No matching record found in authoritative sources"]}]}),
        "novelty": AgentResult(agent="novelty", ok=False, error="LLM unavailable"),
    }


def test_build_report_json_includes_failed_lanes():
    r = build_report_json("local:x", "My Paper", _results())
    assert r["lanes"]["novelty"]["ok"] is False
    assert "LLM unavailable" in r["lanes"]["novelty"]["error"]
    assert r["lanes"]["citation"]["data"]["counts"]["verified"] == 1
    json.dumps(r)


def test_render_report_html_escapes_and_marks_failures():
    html_out = render_report_html(build_report_json("local:x", "My <Paper>", _results()))
    assert "&lt;Paper&gt;" in html_out and "<Paper>" not in html_out.replace("&lt;Paper&gt;", "")
    assert "FAILED" in html_out and "LLM unavailable" in html_out
    assert "Fake &lt;Paper&gt;" in html_out
    assert html_out.lstrip().lower().startswith("<!doctype html")
```

- [ ] **Step 2: run, watch fail** — `ModuleNotFoundError: papergraph.report`
- [ ] **Step 3: implement** (`papergraph/report.py`) — build the dict exactly as specced; HTML via a module-level template string + small `_section` helpers; every dynamic value through `html.escape(str(...))`; lane cards iterate `report["lanes"]` in a fixed preferred order (`ingest, citation, priorart, novelty, confidence, benchmark, rebuttal`, then any others); include per-section renderers only when that lane's data has the expected keys. Keep it ~150 lines, inline CSS, ASCII only.
- [ ] **Step 4: run, watch pass** — `2 passed`
- [ ] **Step 5: commit** — `git add papergraph/report.py tests/test_report.py` · msg `feat(report): self-contained HTML/JSON report builder tolerant of failed lanes`

---

### Task 3: `--report` on review

**Files:** Modify `papergraph/cli.py` · Test: extend `tests/test_cli_review.py`

**Interfaces:** `papergraph review <id> [--report DIR]` — after `run_agents`, when `--report` given: write `DIR/report.json` + `DIR/report.html` (mkdir parents) using Task-2 builder (title from `PaperMetadata.load`), print both paths on the human path (and include `"report_dir"` in the JSON payload when combined with `--json`). Exit code unchanged semantics.

- [ ] **Step 1: failing test**

```python
def test_review_report_flag_writes_html_and_json(monkeypatch: pytest.MonkeyPatch, tmp_path, capsys):
    paper_id = _seed()
    monkeypatch.setattr(cli, "REVIEW_CONTEXT_OVERRIDES", _overrides())
    out_dir = tmp_path / "rep"
    rc = cli.main(["review", paper_id, "--fast", "--report", str(out_dir)])
    assert rc == 0
    assert (out_dir / "report.html").exists() and (out_dir / "report.json").exists()
    payload = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))
    assert payload["lanes"]["citation"]["ok"] is True
    assert "report.html" in capsys.readouterr().out
```

- [ ] **Step 2: run, watch fail** — SystemExit 2 (unknown `--report`).
- [ ] **Step 3: implement** — add `prv.add_argument("--report", help="Write report.html + report.json to this directory")`; in `_cmd_review` after results:

```python
    if args.report:
        from papergraph.report import build_report_json, render_report_html
        from papergraph.store import PaperMetadata

        meta = PaperMetadata.load(args.paper_id)
        rep = build_report_json(args.paper_id, meta.title if meta else "", results)
        out_dir = Path(args.report)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "report.json").write_text(
            json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8")
        (out_dir / "report.html").write_text(render_report_html(rep), encoding="utf-8")
        if not args.json:
            print(f"\nReport: {out_dir / 'report.html'}")
            print(f"        {out_dir / 'report.json'}")
```

(Place before the `--json` payload print so JSON mode can add `"report_dir": str(out_dir)` to its payload when set.)

- [ ] **Step 4: run, watch pass**; **Step 5: full suite; commit** — `git add papergraph/cli.py tests/test_cli_review.py` · msg `feat(cli): --report writes html/json report after review`

---

### Task 4: Dashboard package (FastAPI + SSE)

**Files:** Create `papergraph/dashboard/__init__.py`, `papergraph/dashboard/server.py`, `papergraph/dashboard/page.py` · Test `tests/test_dashboard.py` · Modify `pyproject.toml` (add `[project.optional-dependencies] demo = ["fastapi>=0.110", "uvicorn>=0.29"]`; add both to the dev extra too)

**Interfaces:** `create_app(bus: Bus, state: dict) -> FastAPI` with routes: `GET /` → the single-page HTML (from `page.py::PAGE_HTML`); `GET /state` → JSON `{"lanes": state.get("lanes", {}), "done": state.get("done", False)}`; `GET /events` → `text/event-stream`, first replays `bus.history` then streams new events via a subscription queue (each SSE line `data: <event_to_dict json>\n\n`), closing when `state["done"]` and queue drained. `PAGE_HTML`: vanilla JS EventSource client rendering agent lanes (name, status, latest finding summary) + a scrolling findings feed; ASCII-only source.

- [ ] **Step 1: failing test**

```python
# tests/test_dashboard.py
"""Socketless tests for the live dashboard (FastAPI TestClient)."""
from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from papergraph.agents import events  # noqa: E402
from papergraph.agents.bus import Bus  # noqa: E402
from papergraph.dashboard.server import create_app  # noqa: E402


def _client(bus, state):
    return TestClient(create_app(bus, state))


def test_index_serves_page():
    resp = _client(Bus(), {}).get("/")
    assert resp.status_code == 200
    assert "papergraph" in resp.text.lower()
    assert "EventSource" in resp.text


def test_state_endpoint():
    resp = _client(Bus(), {"lanes": {"ingest": "done"}, "done": True}).get("/state")
    assert resp.json() == {"lanes": {"ingest": "done"}, "done": True}


@pytest.mark.asyncio
async def test_events_replays_history_and_closes_when_done():
    bus = Bus()
    await bus.publish(events.AgentStarted(agent="ingest"))
    await bus.publish(events.AgentDone(agent="ingest", summary="ok"))
    state = {"done": True}
    with _client(bus, state).stream("GET", "/events") as resp:
        body = "".join(resp.iter_text())
    assert '"event": "agent_started"' in body or '"event":"agent_started"' in body
    assert "agent_done" in body
```

- [ ] **Step 2: run, watch fail** — `ModuleNotFoundError: papergraph.dashboard`
- [ ] **Step 3: implement** — `server.py`:

```python
# papergraph/dashboard/server.py
"""Live dashboard: serves the page, a state snapshot, and an SSE event stream."""
from __future__ import annotations

import asyncio
import json

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse

from papergraph.agents.bus import Bus
from papergraph.agents.events import event_to_dict
from papergraph.dashboard.page import PAGE_HTML


def create_app(bus: Bus, state: dict) -> FastAPI:
    app = FastAPI(title="papergraph dashboard")

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return PAGE_HTML

    @app.get("/state")
    async def get_state() -> dict:
        return {"lanes": state.get("lanes", {}), "done": state.get("done", False)}

    @app.get("/events")
    async def events_stream() -> StreamingResponse:
        async def gen():
            for e in list(bus.history):
                yield f"data: {json.dumps(event_to_dict(e))}\n\n"
            q = bus.subscribe()
            try:
                while not (state.get("done") and q.empty()):
                    try:
                        e = await asyncio.wait_for(q.get(), timeout=0.2)
                    except asyncio.TimeoutError:
                        continue
                    yield f"data: {json.dumps(event_to_dict(e))}\n\n"
            finally:
                bus.unsubscribe(q)

        return StreamingResponse(gen(), media_type="text/event-stream")

    return app
```

`page.py`: `PAGE_HTML` — one HTML string: `<!doctype html>`, inline CSS (dark, lane cards grid, feed list), JS: `new EventSource('/events')`; on message parse JSON; `agent_started` → lane "running"; `agent_done` → "done" + summary; `agent_error` → "FAILED" + error; `finding` → prepend to feed (kind + summary) and update lane's latest line; poll `/state` every 2s to flip a DONE banner. Keep under ~120 lines, ASCII.
`__init__.py`: one-line docstring.
`pyproject.toml`: add the `demo` extra; append fastapi/uvicorn to the existing dev extra list.

- [ ] **Step 4: run, watch pass** — `3 passed`
- [ ] **Step 5: full suite + ruff on new files; commit** — `git add papergraph/dashboard/__init__.py papergraph/dashboard/server.py papergraph/dashboard/page.py tests/test_dashboard.py pyproject.toml` · msg `feat(dashboard): FastAPI+SSE live agent dashboard`

---

### Task 5: `--serve` wiring

**Files:** Modify `papergraph/cli.py` · Test: extend `tests/test_cli_review.py`

**Interfaces:** `papergraph review <id> --serve [--port 8501]` — builds `state = {"lanes": {}, "done": False}`; a bus subscriber task updates `state["lanes"]` from events; starts uvicorn (`uvicorn.Server` with `config.host="127.0.0.1"`, given port, `log_level="warning"`) in a background thread BEFORE `run_agents`; prints `Dashboard: http://127.0.0.1:<port>` ; runs agents; sets `state["done"]=True`; prints "Press Ctrl+C to stop the dashboard." and `server.should_exit = True` only on KeyboardInterrupt — for testability, factor the whole branch into `_serve_review(agents, ctx, port) -> dict[str, AgentResult]` and let tests replace the server-runner: seam `REVIEW_CONTEXT_OVERRIDES["_server_runner"]` (callable `(app, port) -> None` default `_run_uvicorn_in_thread`). If fastapi/uvicorn missing: print friendly install hint (`pip install 'papergraph[demo]'` style message with the actual package name `papergraphy`? — use `pip install fastapi uvicorn`) to stderr, return 1.

- [ ] **Step 1: failing test**

```python
def test_review_serve_uses_injected_server_and_completes(monkeypatch, capsys):
    paper_id = _seed()
    launched = {}

    def fake_runner(app, port):
        launched["port"] = port

    ov = _overrides()
    ov["_server_runner"] = fake_runner
    monkeypatch.setattr(cli, "REVIEW_CONTEXT_OVERRIDES", ov)
    rc = cli.main(["review", paper_id, "--fast", "--serve", "--port", "9999"])
    out = capsys.readouterr().out
    assert rc == 0
    assert launched["port"] == 9999
    assert "127.0.0.1:9999" in out
```

- [ ] **Step 2: run, watch fail** — SystemExit 2 (unknown `--serve`).
- [ ] **Step 3: implement** — add args `--serve` (store_true) + `--port` (int, default 8501). In `_cmd_review`, when `args.serve`: import guard for fastapi/uvicorn (except ImportError → stderr hint, return 1); build app via `create_app(ctx.bus, state)`; runner = `ctx.data.get("_server_runner")` or a `_run_uvicorn_in_thread(app, port)` helper (daemon thread, `uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")).run`); print URL; also attach a lane-tracking subscriber: simplest is updating `state["lanes"]` inside the existing results loop after `run_agents` returns AND passing `state` into... (state must update live: attach `q = ctx.bus.subscribe()` + `asyncio` task inside the same event loop as run_agents — factor `async def _run_with_state(agents, ctx, state)` that starts the tracker task, runs run_agents, cancels tracker, sets done) — implement exactly that in cli.py; keep the human lane printing identical after completion.
- [ ] **Step 4: run, watch pass**; **Step 5: full suite + ruff; commit** — `git add papergraph/cli.py tests/test_cli_review.py` · msg `feat(cli): --serve live dashboard for review`

---

### Task 6: Plan gates + docs touch

**Files:** Modify `README.md` (add "Agentic review" section: review/--fast/--report/--serve, rebuttal quickstart — ~30 lines, ASCII) · no other code.

- [ ] Step 1: full suite `python -m pytest -q` — green (baseline + ~9 new across plan).
- [ ] Step 2: `python -m ruff check papergraph tests` — clean (or only pre-approved deferrals).
- [ ] Step 3: offline smoke: seeded paper, `review --fast --report <tmp>` → report.html/json exist and html contains lane names; dashboard TestClient smoke already covered by tests.
- [ ] Step 4: commit README — `git add README.md` · msg `docs: agentic review, report, dashboard, rebuttal quickstart`

## What Plan 5 consumes
- `report.build_report_json` for eval outputs; run event logs for the demo video; `[demo]` extra in packaging.
