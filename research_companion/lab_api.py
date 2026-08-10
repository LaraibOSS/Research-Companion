"""Research Companion REST + SSE server.

Single long-running server behind the Research Companion web UI.

Design rules (from the approved plan):
- SINGLE event loop: uvicorn runs foreground; POST handlers spawn asyncio.create_task;
  SSE subscribes to the same-loop Bus. No threads for the Bus.
- Lazy FastAPI imports: module import must not require fastapi. The ImportError is
  raised at serve time with a friendly message.
- SSE: subscribe-first -> replay history (with original seq) -> live stream (dedup).
  Heartbeat ': ping' every 15s while idle. Stream stays open.
- One ingest at a time: concurrent POST /api/ingest -> 409.
- CORS not needed (same origin).

Public API:
    create_lab_app(bus: Bus, *, llm=None) -> FastAPI
    serve_lab(port: int = 8765, *, open_browser: bool = True) -> None
"""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any

from research_companion.agents.bus import Bus
from research_companion.agents.events import event_to_dict


def _pipeline_provider_model() -> tuple[str, str | None]:
    """Resolve (provider, model) for pipeline LLM calls.

    Uses the SAME resolution as /api/settings (saved settings <- env <-
    default) so the pipeline can never disagree with what the Settings page
    shows. Previously this read the raw env var and defaulted to anthropic,
    so a server started without the env var failed extraction auth while the
    UI displayed the correct provider.
    """
    try:
        from research_companion.settings import get_settings
        s = get_settings()
        return s.get("provider") or "anthropic", s.get("model")
    except Exception:  # noqa: BLE001 — never let settings issues kill a job
        import os
        return (os.environ.get("RESEARCH_COMPANION_PROVIDER", "anthropic"),
                os.environ.get("RESEARCH_COMPANION_MODEL"))


def _llm_provider_configured() -> bool:
    """True iff an API key is present for the RESOLVED pipeline provider.

    VERIFIED (Task 2 brief): _resolve_llm() below never fails at construction
    time for a missing key -- it only resolves (provider, model) and returns a
    closure; the SDK client (and the missing-key error) only appears inside
    _call_anthropic/_call_openai, which run when the closure is INVOKED. So
    `try: _resolve_llm(); except Exception: ...` would always report
    configured=True regardless of whether a key exists -- the wrong signal for
    GET /simplified, which must answer with no network call and without
    swallowing a genuine construction bug. Key PRESENCE via the settings
    module is the same source get_settings()["keys"] uses for the Settings
    page's masked key display, so this can never disagree with the UI.
    """
    from research_companion.settings import get_settings

    provider, _model = _pipeline_provider_model()
    keys = get_settings().get("keys", {})
    return bool(keys.get(f"{provider}_api_key", {}).get("set"))


def _simplify_char_budget() -> int:
    """Same settings["char_budget"] accessor qa.answer uses (research_companion/
    qa.py, near its k_sections/char_budget resolution) -- reused rather than a
    new constant so the reader's "Simplify further" job and Ask/QA agree on
    how much paper text an LLM call is allowed to see."""
    try:
        from research_companion.settings import get_settings
        return int(get_settings().get("char_budget", 8000))
    except Exception:  # noqa: BLE001 — never let settings issues kill a job
        return 8000


# Upload size cap for POST /api/papers/upload (module-level so tests can patch it)
_MAX_UPLOAD_BYTES = 50 * 1024 * 1024


class _FindPdfMiss(Exception):
    """Raised by _find_pdf_for_failure when locate_pdf found no downloadable
    PDF. Carries the candidate-link count so the job wrapper can record a
    distinct "done" (not "failed") outcome — a miss is a completed search,
    not an error."""

    def __init__(self, link_count: int) -> None:
        self.link_count = link_count
        super().__init__(f"no open-access PDF found ({link_count} links)")


def _is_missing_pdf_failure(reason: str | None) -> bool:
    """True when a failure's error text indicates the paper has no PDF on
    disk -- the only failure class POST /api/papers/{id}/find-pdf can
    actually fix. Mirrors research_companion/lab/static/js/libraryHelpers.js's
    isMissingPdfFailure: two wordings reach here -- "no PDF on disk"
    (extract.py, first ingest) and "PDF not found" (fetch.py's
    add_local_pdf, the retry path)."""
    if not reason:
        return False
    return reason.startswith("no PDF on disk") or reason.startswith("PDF not found")

# ---------------------------------------------------------------------------
# Request body models (module-level so annotations resolve correctly with
# `from __future__ import annotations` in effect).
# Pydantic is a fastapi dependency, so importing it here is safe if fastapi
# is installed; if not, the ImportError is deferred to create_lab_app / serve_lab.
# ---------------------------------------------------------------------------

try:
    from pydantic import BaseModel as _BaseModel

    # Module-level so the deferred (string) annotation on the upload endpoint
    # resolves against module globals; starlette ships with fastapi.
    from starlette.requests import Request

    class _DraftBody(_BaseModel):
        paper_id: str | None = None

    class _IngestBody(_BaseModel):
        folder: str = ""
        paths: list[str] | None = None

    class _AlignBody(_BaseModel):
        paper_id: str = ""
        against: str | None = None
        force: bool = False

    class _AskBody(_BaseModel):
        question: str = ""
        section_id: str | None = None

    class _CompareBody(_BaseModel):
        paper_a: str = ""
        paper_b: str = ""

    class _AddPaperBody(_BaseModel):
        target: str = ""

    class _SettingsPatchBody(_BaseModel):
        """Arbitrary subset of settings fields for PUT /api/settings."""
        provider: str | None = None
        model: str | None = None
        theme: str | None = None
        accent: str | None = None
        density: str | None = None
        k_sections: int | None = None
        char_budget: int | None = None
        embed_model: str | None = None
        keys: dict[str, str | None] | None = None

    class _RegenerateBody(_BaseModel):
        include_llm: bool = False

    class _CreateViewBody(_BaseModel):
        name: str = ""
        source: dict = {}
        node_ids: list[str] = []
        pinned: bool = False

    class _PatchViewBody(_BaseModel):
        name: str | None = None
        pinned: bool | None = None

    class _PatchPaperBody(_BaseModel):
        """Manual metadata edit for PATCH /api/papers/{id}. All optional; only
        explicitly-sent fields (model_fields_set) are applied."""
        title: str | None = None
        authors: list[str] | None = None
        year: int | None = None

    class _LinkCitationBody(_BaseModel):
        """Manual assertion "cited reference N IS library paper X" for
        POST /api/draft/citations/link."""
        index: int
        paper_id: str

    class _UnlinkCitationBody(_BaseModel):
        """Undo a manual link for POST /api/draft/citations/unlink."""
        index: int

    class _ConverseBody(_BaseModel):
        context: dict = {}
        message: str = ""
        conversation_id: str | None = None

    class _WorkspaceCreateBody(_BaseModel):
        name: str = ""

    class _WorkspacePatchBody(_BaseModel):
        name: str | None = None
        archived: bool | None = None

    class _DirectionsBody(_BaseModel):
        """POST /api/directions body -- Research Directions (Brainstorm 2b).
        year_min/year_max are accepted for parity with GET /api/discover but
        are not yet used to filter (deferred; see the 2b design spec)."""
        topic: str = ""
        year_min: int | None = None
        year_max: int | None = None
        seeds: list[dict] = []

    class _NoveltyBody(_BaseModel):
        """POST /api/novelty body -- Novelty Gate (Brainstorm 2c). Checks one
        direction's title+rationale against real, freshly-searched prior work."""
        title: str = ""
        rationale: str = ""
        year_min: int | None = None
        year_max: int | None = None

    class _ScaffoldBody(_BaseModel):
        """POST /api/directions/draft body -- "Draft this direction"
        (Brainstorm 2d). The one chosen direction's full shape (2b's
        title/rationale/direction_type/citations), MUTATING -- unlike
        _DirectionsBody/_NoveltyBody, this creates a real draft."""
        title: str
        rationale: str = ""
        direction_type: str = ""
        citations: list[dict] = []

except ImportError:
    # fastapi/pydantic not installed — placeholders (create_lab_app will fail
    # with a friendly message before any endpoint tries to use these classes).
    _DraftBody = None  # type: ignore[assignment,misc]
    _IngestBody = None  # type: ignore[assignment,misc]
    _AlignBody = None  # type: ignore[assignment,misc]
    _AskBody = None  # type: ignore[assignment,misc]
    _CompareBody = None  # type: ignore[assignment,misc]
    _AddPaperBody = None  # type: ignore[assignment,misc]
    _SettingsPatchBody = None  # type: ignore[assignment,misc]
    _RegenerateBody = None  # type: ignore[assignment,misc]
    _CreateViewBody = None  # type: ignore[assignment,misc]
    _PatchViewBody = None  # type: ignore[assignment,misc]
    _PatchPaperBody = None  # type: ignore[assignment,misc]
    _LinkCitationBody = None  # type: ignore[assignment,misc]
    _UnlinkCitationBody = None  # type: ignore[assignment,misc]
    _ConverseBody = None  # type: ignore[assignment,misc]
    _WorkspaceCreateBody = None  # type: ignore[assignment,misc]
    _WorkspacePatchBody = None  # type: ignore[assignment,misc]
    _DirectionsBody = None  # type: ignore[assignment,misc]
    _NoveltyBody = None  # type: ignore[assignment,misc]
    _ScaffoldBody = None  # type: ignore[assignment,misc]

# ---------------------------------------------------------------------------
# Static directory (always relative to this file)
# ---------------------------------------------------------------------------

_STATIC_DIR = Path(__file__).parent / "lab" / "static"
_INDEX_HTML = _STATIC_DIR / "index.html"

_PLACEHOLDER_HTML = """\
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Research Companion</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body>
  <h1>Research Companion</h1>
  <p>The Research Companion frontend is not yet installed.
     Run the Task F1 build to generate the static assets.</p>
  <script>
    // Placeholder EventSource for health check
    if (typeof EventSource !== 'undefined') {
      const es = new EventSource('/api/events');
      es.onerror = function() { es.close(); };
    }
  </script>
</body>
</html>
"""

# ---------------------------------------------------------------------------
# "Simplify further" (reader tab) prompt
# ---------------------------------------------------------------------------

_SIMPLIFY_PROMPT = """You are helping a non-expert understand a research paper.
Rewrite the paper's important points as short, simple-English bullet points.
Rules:
- Use ONLY facts stated in the paper text below. Never add outside knowledge.
- No jargon; explain any unavoidable technical term in plain words.
- Group bullets under EXACTLY these four headings (omit a heading only if the
  paper truly has nothing for it): "What this paper is about", "Key claims",
  "How they did it", "What they found".
- Where a bullet comes from a specific section, include that section's id.
Return JSON only: {"groups": [{"title": "...", "bullets": [{"text": "...",
"section_id": "s1" or null}]}]}

Paper title: {title}

Sections:
{sections_block}
"""


# ---------------------------------------------------------------------------
# Seq-recorder: wraps Bus with monotonic seq assignment
# ---------------------------------------------------------------------------

class _SeqRecorder:
    """Subscribes to a Bus at creation time and assigns monotonic seq numbers.

    Maintains a list of (seq, event) so SSE can replay them to reconnecting clients.
    Seq starts at 1.

    On construction, pre-assigns seq numbers to any events already in bus.history
    so reconnecting clients can replay pre-connect events.

    NOTE: _records grows unbounded for the lifetime of the server. In practice this
    is acceptable because event volume is bounded by the number of papers ingested
    per session. A production deployment with very long uptimes may want to cap this
    (e.g. keep only the last N records or flush after a JobDone).
    """

    def __init__(self, bus: Bus) -> None:
        self._bus = bus
        self._records: list[tuple[int, Any]] = []
        self._seq = 0
        self._stopping = False
        # Condition used to notify waiting SSE consumers when new events arrive.
        # Must be created lazily (inside the running event loop) — see _get_condition().
        self._condition: asyncio.Condition | None = None
        # Pre-assign seq for events already in history (before this recorder was created)
        pre_history = list(bus.history)
        self._seen_ids: set[int] = set()
        for event in pre_history:
            self._assign(event)
            self._seen_ids.add(id(event))
        # Subscribe AFTER snapshotting history to avoid duplicates
        self._q = bus.subscribe()

    def _get_condition(self) -> asyncio.Condition:
        """Return (lazily creating) the asyncio.Condition for this recorder.

        Creating the Condition inside __init__ would bind it to whatever event loop
        is current at import time.  Lazy creation ensures it is bound to the
        server's event loop.
        """
        if self._condition is None:
            self._condition = asyncio.Condition()
        return self._condition

    def _assign(self, event) -> int:
        self._seq += 1
        self._records.append((self._seq, event))
        return self._seq

    def reset(self) -> None:
        """Drop all recorded events and restart seq at 1 (workspace activation).

        The SSE replay must not leak the previous workspace's events to the
        client that reloads after switching researches.
        """
        self._records.clear()
        self._seen_ids.clear()
        self._seq = 0

    def stop(self) -> None:
        """Request drain() to exit at its next iteration.

        Cancellation alone is NOT reliable: Python 3.10's asyncio.wait_for can
        swallow a cancellation that races a ready queue item (bpo-42130),
        leaving drain alive after cancel() and wedging the lifespan shutdown
        forever on `await drain_task` — surfaced when job-lifecycle events are
        published right at shutdown time.
        """
        self._stopping = True

    async def drain(self) -> None:
        """Continuously drain the Bus queue, assigning seq numbers (skipping pre-history).

        Notifies all waiting SSE consumers (via the Condition) after each new event
        so that generators can serve the authoritative (seq, event) pair.
        """
        condition = self._get_condition()
        while not self._stopping:
            try:
                event = await asyncio.wait_for(self._q.get(), timeout=1.0)
                if id(event) not in self._seen_ids:
                    self._assign(event)
                    self._seen_ids.add(id(event))
                    async with condition:
                        condition.notify_all()
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    def snapshot(self) -> list[tuple[int, Any]]:
        """Return a copy of all (seq, event) pairs recorded so far."""
        return list(self._records)

    def current_max_seq(self) -> int:
        return self._seq


def _build_paper_summary(meta, *, failures: dict, draft_id, prompt_sha: str) -> dict:
    """Build the per-paper dict served by GET /api/papers (and returned by
    PATCH /api/papers/{id}). Factored so the two stay identical in shape."""
    from research_companion import store

    paper_id = meta.paper_id
    status = "pending"
    failure_reason = None
    oa_links: list[dict] = []
    for key, info in failures.items():
        if key == paper_id or info.get("paper_id") == paper_id:
            status = "failed"
            failure_reason = info.get("error")
            oa_links = info.get("oa_links") or []
            break

    if status != "failed" and store.load_extraction(
            paper_id, prompt_sha=prompt_sha) is not None:
        status = "done"

    strength_payload = store.load_strength(paper_id)
    if strength_payload is not None:
        strength = {
            "score": strength_payload.get("score"),
            "band": strength_payload.get("band", ""),
            "color": strength_payload.get("color", ""),
        }
    else:
        strength = None

    stance_counts = {"strengthens": 0, "challenges": 0, "alternative": 0}
    if draft_id is not None:
        alignment = store.load_alignment(paper_id, draft_paper_id=draft_id)
        if alignment is not None:
            for sec in alignment.get("sections", []):
                rel = sec.get("relation", "")
                if rel in stance_counts:
                    stance_counts[rel] += 1

    return {
        "paper_id": paper_id,
        "title": meta.title,
        "authors": meta.authors,
        "year": meta.year,
        "status": status,
        "failure_reason": failure_reason,
        "strength": strength,
        "is_draft": paper_id == draft_id,
        "stance_counts": stance_counts,
        "added_at": meta.added_at,
        "parse_source": getattr(meta, "parse_source", "") or "",
        "ocr_used": bool(getattr(meta, "ocr_used", False)),
        "oa_links": oa_links,
    }


# ---------------------------------------------------------------------------
# GET /api/discover helpers (feat/brainstorm-discover)
# ---------------------------------------------------------------------------

def _library_identity_ids() -> set[str]:
    """alt_ids-style identity strings for every paper currently in the store.

    Used to mark GET /api/discover results in_library. discover.py's own
    search_topic/search_topic_openalex already filter results against the
    local store, but search_topic_with_fallback's opt-in domain-connector
    merge is only deduped against the S2/OpenAlex batch, not against the
    local store — so a connector-only hit can still legitimately need
    in_library=True. Re-checking here (rather than trusting upstream
    filtering) keeps that flag honest regardless of which path a result
    came from.
    """
    from research_companion import store
    from research_companion.connectors.identity import alt_ids

    ids: set[str] = set()
    for meta in store.list_papers():
        doi = meta.paper_id.removeprefix("doi:") if meta.paper_id.startswith("doi:") else None
        arxiv_id = meta.paper_id.removeprefix("arxiv:") if meta.paper_id.startswith("arxiv:") else None
        rec = {"doi": doi, "arxiv_id": arxiv_id, "pmid": meta.pmid, "pmcid": meta.pmcid}
        ids |= alt_ids(rec)
    return ids


def _dedup_discovered(papers: list) -> list:
    """Merge discovery results across multiple expanded queries.

    Dedups by identity (connectors.identity.alt_ids over doi/arxiv_id/pmid/
    pmcid), falling back to a lowercased-title token for papers with no
    namespaced id. When two results share an identity, keeps whichever has
    the higher citation_count (the more complete/informative record).
    Order-preserving over first occurrence.
    """
    from research_companion.connectors.identity import alt_ids

    id_to_token: dict[str, str] = {}
    chosen: dict[str, object] = {}
    order: list[str] = []

    for p in papers:
        rec = {"doi": p.doi, "arxiv_id": p.arxiv_id, "pmid": p.pmid, "pmcid": p.pmcid}
        ids = alt_ids(rec)
        token = None
        for i in ids:
            if i in id_to_token:
                token = id_to_token[i]
                break
        if token is None:
            token = next(iter(ids)) if ids else f"title:{p.title.lower().strip()}"
        for i in ids:
            id_to_token[i] = token

        if token not in chosen:
            chosen[token] = p
            order.append(token)
        elif p.citation_count > chosen[token].citation_count:
            chosen[token] = p

    return [chosen[t] for t in order]


# ---------------------------------------------------------------------------
# create_lab_app
# ---------------------------------------------------------------------------

class NoActiveWorkspaceError(Exception):
    """Raised by require_active_workspace() when no research is active.

    A dedicated exception (rather than HTTPException) so the registered
    handler controls the exact response body — {"error": "no_active_workspace"}
    at the top level, not nested under FastAPI's default {"detail": ...}.
    """


def require_active_workspace() -> None:
    """FastAPI dependency: 409s mutating endpoints when no research is active.

    Read endpoints must NEVER depend on this — they degrade to an empty
    response instead (see store.py's None-tolerant read helpers, Task 1).
    """
    from research_companion import store
    if store.active_workspace_id() is None:
        raise NoActiveWorkspaceError()


def create_lab_app(bus: Bus, *, llm=None):  # -> FastAPI
    """Create and return the Lab FastAPI application.

    Args:
        bus:  Event bus (shared with background tasks).
        llm:  Optional LLM callable(prompt: str) -> str. When None, real provider
              is wired lazily per request.

    Returns:
        A FastAPI application instance.
    """
    try:
        from fastapi import Depends, FastAPI, HTTPException
        from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
        from fastapi.staticfiles import StaticFiles
    except ImportError as exc:
        raise ImportError(
            "research-companion lab server requires fastapi and uvicorn. "
            "Install with: pip install 'research-companion[server]'"
        ) from exc

    recorder = _SeqRecorder(bus)

    @asynccontextmanager
    async def lifespan(app):  # type: ignore[type-arg]
        # Start the recorder drain task so seq numbers are assigned centrally.
        drain_task = asyncio.create_task(recorder.drain())
        # One-shot: backfill weak metadata for the active workspace's existing
        # papers (non-fatal — must never block/crash startup).
        with suppress(Exception):
            asyncio.create_task(app.state._trigger_backfill())
        try:
            yield
        finally:
            recorder.stop()   # flag first — cancel alone can be swallowed (bpo-42130)
            drain_task.cancel()
            with suppress(asyncio.CancelledError):
                await drain_task

    app = FastAPI(title="Research Companion", lifespan=lifespan)

    @app.exception_handler(NoActiveWorkspaceError)
    async def _no_active_workspace_handler(request, exc):
        return JSONResponse(status_code=409, content={"error": "no_active_workspace"})

    # DNS-rebinding defense: the Lab is a local-only server (binds 127.0.0.1), but
    # without a Host allowlist a remote page could rebind a hostname to 127.0.0.1
    # and then issue same-origin requests to read/tamper the corpus. Reject any
    # Host that is not loopback. ("testserver" is the Starlette TestClient host.)
    from starlette.middleware.trustedhost import TrustedHostMiddleware
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["127.0.0.1", "localhost", "testserver"],
    )

    app.state.recorder = recorder
    app.state.bus = bus
    app.state.llm = llm
    app.state.jobs: dict[str, dict] = {}
    app.state.job_counter = 0

    # Allow test overrides for the full task coroutine
    app.state.ingest_override = None
    app.state.add_paper_override = None
    app.state.upload_override = None
    app.state.citations_resolver_override = None
    # Serializes coverage compute/resolve read-modify-write cycles (prevents
    # a recompute racing the resolve job's save and re-triggering auto-resolve)
    app.state._coverage_lock = asyncio.Lock()
    # Session-scoped dedupe for citation auto-downloads (prevents retry storms)
    app.state.auto_added_targets: set = set()
    app.state.retry_override = None
    # find-pdf (OA locator) seams: find_pdf_override mirrors retry_override for
    # tests; find_pdf_sweep_running guards the batch endpoint against overlapping
    # sweeps (single flag, reset in the sweep job's `finally`).
    app.state.find_pdf_override = None
    app.state.find_pdf_sweep_running = False
    # One-shot weak-metadata backfill (Task 5): test seam + per-session guard so
    # each workspace is scanned at most once. backfill_override lets tests inject
    # a fake in place of the real re-extraction pipeline.
    app.state.backfill_override = None
    app.state._backfilled_workspaces: set = set()
    # "Simplify further" (reader tab) job seam -- mirrors retry_override: a
    # full coroutine(paper_id) replacement so tests never hit a real LLM.
    app.state.simplify_override = None

    # Pipeline-stage seams for add/retry tasks — mirrors LAB_INGEST_OVERRIDES style.
    # Tests inject counting/spying fakes here; production code leaves these None
    # (real defaults are resolved inside _add_paper_task / _retry_paper_task).
    app.state.pipeline_overrides: dict = {}

    # Test hook: when set to True, SSE stream terminates after replaying history
    # (mirrors dashboard's done-state pattern; production code leaves this False).
    app.state._sse_done = False

    # -----------------------------------------------------------------
    # Mount static files (tolerates sparse/absent directory)
    # -----------------------------------------------------------------
    # Python's mimetypes DB is platform-dependent (on Windows it reads the
    # registry) and often lacks .mjs — StaticFiles then serves ES modules as
    # text/plain, which browsers refuse to execute, so the PDF.js viewer
    # never boots. Register the JavaScript types explicitly; .js included
    # because registry entries have been seen to override it too.
    import mimetypes

    mimetypes.add_type("text/javascript", ".mjs")
    mimetypes.add_type("text/javascript", ".js")

    _STATIC_DIR.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    # StaticFiles already sets ETag/Last-Modified, but neither header alone
    # stops a browser from heuristically caching JS/CSS with no explicit
    # freshness policy — that's exactly why users see a stale UI after an
    # upgrade. "no-cache" (NOT "no-store") forces revalidation on every
    # request; the existing ETag makes that a cheap 304 rather than a full
    # re-download, so this costs a round trip, not the asset itself.
    @app.middleware("http")
    async def _static_no_cache(request, call_next):
        # PDF.js vendor assets must never answer 304: Chromium does not apply
        # a 304's updated Content-Type to its module-script MIME check, so a
        # browser cache that stored .mjs as text/plain (from a server run
        # before the mimetypes registration above) is only repaired by a full
        # 200 replacing the entry. Stripping the conditional headers makes
        # StaticFiles serve the complete file every time (localhost-sized
        # cost; the viewer is ~3 MB and loads lazily).
        if request.url.path.startswith("/static/vendor/pdfjs/"):
            request.scope["headers"] = [
                (k, v)
                for (k, v) in request.scope["headers"]
                if k.lower() not in (b"if-none-match", b"if-modified-since")
            ]
        response = await call_next(request)
        if request.url.path.startswith("/static"):
            response.headers["Cache-Control"] = "no-cache"
            # StaticFiles omits Content-Type on 304s, but browsers update a
            # stored response's headers from the 304 (RFC 9111 §4.3.4) — so a
            # cache that stored a wrong MIME type (e.g. .mjs as text/plain
            # from a server run before the mimetypes registration above) can
            # only heal if the 304 restates the correct type.
            if response.status_code == 304 and "content-type" not in response.headers:
                guessed, _ = mimetypes.guess_type(request.url.path)
                if guessed:
                    response.headers["Content-Type"] = guessed
        return response

    # -----------------------------------------------------------------
    # GET /
    # -----------------------------------------------------------------
    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        if _INDEX_HTML.exists():
            return _INDEX_HTML.read_text(encoding="utf-8")
        return _PLACEHOLDER_HTML

    # -----------------------------------------------------------------
    # GET /api/lab
    # -----------------------------------------------------------------
    @app.get("/api/lab")
    async def get_lab() -> dict:
        from research_companion import store
        from research_companion.graph import load_graph

        papers = store.list_papers()
        G = load_graph()
        active_jobs = [
            jid for jid, info in app.state.jobs.items()
            if info.get("status") == "running"
        ]
        return {
            "draft_id": store.get_draft_paper_id(),
            "paper_count": len(papers),
            "node_count": G.number_of_nodes(),
            "edge_count": G.number_of_edges(),
            "active_jobs": active_jobs,
        }

    # -----------------------------------------------------------------
    # GET /api/papers
    # -----------------------------------------------------------------
    @app.get("/api/papers")
    async def get_papers() -> list:
        from research_companion import store
        from research_companion.prompts import extraction_prompt_sha256

        papers = store.list_papers()
        failures = store.list_failures()
        draft_id = store.get_draft_paper_id()
        prompt_sha = extraction_prompt_sha256()

        return [
            _build_paper_summary(
                meta, failures=failures, draft_id=draft_id, prompt_sha=prompt_sha)
            for meta in papers
        ]

    # -----------------------------------------------------------------
    # GET /api/discover  (read-only topic search — feat/brainstorm-discover)
    # -----------------------------------------------------------------
    @app.get("/api/discover")
    async def get_discover(
        q: str = "",
        year_min: int | None = None,
        year_max: int | None = None,
        limit: int = 20,
        expand: int = 0,
    ) -> dict:
        from research_companion import discover
        from research_companion.connectors.identity import alt_ids

        query = (q or "").strip()
        limit = max(1, min(limit, 50))
        expand_requested = bool(expand)

        if not query:
            return {"results": [], "queries_used": [], "expanded": expand_requested}

        # `queries` is seeded before the try so the except handler can report
        # queries_used even if a failure happens before/during expansion.
        queries = [query]
        try:
            if expand_requested:
                resolved_llm = app.state.llm
                if resolved_llm is None:
                    resolved_llm = _resolve_llm(json_mode=True)
                queries = await asyncio.to_thread(discover.expand_query, query, llm=resolved_llm)

            all_results: list = []
            for one_query in queries:
                found = await asyncio.to_thread(
                    discover.search_topic_with_fallback,
                    one_query, limit=limit, year_min=year_min, year_max=year_max,
                )
                all_results.extend(found)

            # Dedup, the in-library check, and result-building all touch
            # fields (title/doi/arxiv_id/paper_id/...) coming straight from
            # third-party search results or on-disk metadata that was never
            # type-checked -- keep them inside the same never-500 guard as
            # the search/expand calls above.
            deduped = _dedup_discovered(all_results)
            library_ids = await asyncio.to_thread(_library_identity_ids)

            results = []
            for p in deduped[:limit]:
                rec = {"doi": p.doi, "arxiv_id": p.arxiv_id, "pmid": p.pmid, "pmcid": p.pmcid}
                ids = alt_ids(rec)
                item = p.to_dict()
                item["in_library"] = bool(ids & library_ids)
                results.append(item)
        except Exception as exc:
            return {
                "results": [], "queries_used": queries, "expanded": expand_requested,
                "error": f"Discovery search failed: {exc}",
            }

        return {"results": results, "queries_used": queries, "expanded": expand_requested}

    # -----------------------------------------------------------------
    # POST /api/directions  (Research Directions -- Brainstorm 2b.
    # Synchronous/ephemeral like GET /api/discover, NOT a persisted job:
    # directions are a function of a free-text topic + transient 2a seeds,
    # which change every search, so there is no corpus-SHA cache to key on.)
    # -----------------------------------------------------------------
    @app.post("/api/directions")
    async def post_directions(body: _DirectionsBody) -> dict:
        from research_companion import directions as directions_mod
        from research_companion import store
        from research_companion.graph import load_graph
        from research_companion.prompts import extraction_prompt_sha256

        topic = (body.topic or "").strip()
        seeds = body.seeds if isinstance(body.seeds, list) else []

        def _library_papers() -> list:
            prompt_sha = extraction_prompt_sha256()
            out = []
            for meta in store.list_papers():
                ext = store.load_extraction(meta.paper_id, prompt_sha=prompt_sha)
                concepts = [c.get("name", "") for c in (ext or {}).get("concepts", []) if c.get("name")]
                out.append({
                    "paper_id": meta.paper_id, "title": meta.title, "year": meta.year,
                    "abstract": meta.abstract, "concepts": concepts,
                })
            return out

        try:
            resolved_llm = app.state.llm
            if resolved_llm is None:
                resolved_llm = _resolve_llm(json_mode=True)

            library_papers = await asyncio.to_thread(_library_papers)
            loaded_graph = await asyncio.to_thread(load_graph)
            gap_synthesis = await asyncio.to_thread(store.load_gap_synthesis)

            result = await asyncio.to_thread(
                directions_mod.synthesize_directions,
                topic, seeds,
                library_papers=library_papers,
                graph=loaded_graph,
                gap_synthesis=gap_synthesis,
                llm=resolved_llm,
            )
        except Exception as exc:
            return {"directions": [], "topic": topic, "error": f"Directions generation failed: {exc}"}

        # An LLM call/parse failure is swallowed inside synthesize_directions
        # (it never raises); surface it here as the same never-500 error shape
        # so a transient outage shows a retry banner, not a false "no ideas".
        llm_error = result.get("llm_error")
        if llm_error:
            return {"directions": [], "topic": result.get("topic", topic),
                    "error": f"Directions generation failed: {llm_error}"}

        return {"directions": result.get("directions", []), "topic": result.get("topic", topic)}

    # -----------------------------------------------------------------
    # POST /api/novelty  (Novelty Gate -- Brainstorm 2c. Synchronous/ephemeral
    # like GET /api/discover and POST /api/directions: a novelty check is a
    # function of one direction's title+rationale, not a persisted job.)
    # -----------------------------------------------------------------
    @app.post("/api/novelty")
    async def post_novelty(body: _NoveltyBody) -> dict:
        from research_companion import novelty_check

        title = body.title or ""
        rationale = body.rationale or ""

        try:
            resolved_llm = app.state.llm
            if resolved_llm is None:
                resolved_llm = _resolve_llm(json_mode=True)

            result = await asyncio.to_thread(
                novelty_check.check_novelty,
                title, rationale,
                year_min=body.year_min, year_max=body.year_max,
                llm=resolved_llm,
            )
        except Exception as exc:
            return {"verdict": None, "prior_works": [], "error": f"Novelty check failed: {exc}"}

        # An LLM call/parse failure is swallowed inside check_novelty (it
        # never raises); surface it here as the same never-500 error shape
        # so a transient outage shows a retry banner, not a false verdict.
        llm_error = result.get("llm_error")
        if llm_error:
            return {"verdict": None, "prior_works": [], "error": f"Novelty check failed: {llm_error}"}

        return {
            "verdict": result.get("verdict"),
            "confidence": result.get("confidence", 0.0),
            "rationale": result.get("rationale", ""),
            "closest_prior": result.get("closest_prior", []),
            "prior_works": result.get("prior_works", []),
            "query": result.get("query", ""),
        }

    # -----------------------------------------------------------------
    # POST /api/directions/draft  ("Draft this direction" -- Brainstorm 2d.
    # MUTATING + guarded, unlike POST /api/directions/POST /api/novelty:
    # this creates a real draft in the active research. Atomic-on-success:
    # the draft is created ONLY after scaffold.generate_outline succeeds --
    # an LLM/parse failure returns a friendly 200 {"ok": False, "error"} and
    # creates NOTHING (never a raw 500, never a half-made draft).
    # -----------------------------------------------------------------
    @app.post("/api/directions/draft", dependencies=[Depends(require_active_workspace)])
    async def post_directions_draft(body: _ScaffoldBody) -> dict:
        from research_companion import scaffold, store

        direction = {
            "title": body.title or "",
            "rationale": body.rationale or "",
            "direction_type": body.direction_type or "",
            "citations": body.citations if isinstance(body.citations, list) else [],
        }

        try:
            resolved_llm = app.state.llm
            if resolved_llm is None:
                resolved_llm = _resolve_llm(json_mode=True)

            outline = await asyncio.to_thread(
                scaffold.generate_outline, direction, llm=resolved_llm,
            )

            if outline.get("llm_error") or not outline.get("sections"):
                error = outline.get("llm_error") or "The model returned an empty outline."
                return {"ok": False, "error": f"Draft scaffold failed: {error}"}

            paper_id = await asyncio.to_thread(
                scaffold.create_draft_from_direction, direction, outline,
            )

            replaced = store.get_draft_paper_id() not in (None, paper_id)
            await _apply_draft(paper_id)
        except Exception as exc:
            return {"ok": False, "error": f"Draft scaffold failed: {exc}"}

        return {
            "ok": True,
            "paper_id": paper_id,
            "draft_paper_id": paper_id,
            "section_count": len(outline.get("sections", [])),
            "replaced_draft": replaced,
        }

    # -----------------------------------------------------------------
    # POST /api/papers  (add a paper)
    # -----------------------------------------------------------------
    async def _announce_start(job_id: str, kind: str, label: str, target: str = "") -> None:
        from research_companion.agents.events import JobStarted
        with suppress(Exception):
            await bus.publish(JobStarted(job_id=job_id, kind=kind, label=label, target=target))

    async def _announce_finish(job_id: str, kind: str) -> None:
        from research_companion.agents.events import JobFinished
        with suppress(Exception):
            status = app.state.jobs.get(job_id, {}).get("status", "done")
            await bus.publish(JobFinished(job_id=job_id, kind=kind, status=status))

    def _queue_add_paper(target: str) -> str:
        """Create an add-paper job — shared by the endpoint and citation auto-add."""
        app.state.job_counter += 1
        job_id = f"job-{app.state.job_counter}"
        label = f"Downloading {target}"
        app.state.jobs[job_id] = {"status": "running", "detail": None, "kind": "add",
                                  "label": label, "target": target}

        if app.state.add_paper_override is not None:
            coro = app.state.add_paper_override(target, bus)
        else:
            coro = _add_paper_task(
                target,
                bus,
                pipeline_overrides=app.state.pipeline_overrides,
            )

        async def _run():
            await _announce_start(job_id, "add", label, target)
            try:
                await coro
                app.state.jobs[job_id] = {"status": "done", "detail": None, "kind": "add",
                                          "label": label, "target": target}
            except Exception as exc:
                app.state.jobs[job_id] = {"status": "failed", "detail": str(exc), "kind": "add",
                                          "label": label, "target": target}
            finally:
                await _announce_finish(job_id, "add")
                # add_paper stores metadata BEFORE the pipeline runs, so even a
                # failed pipeline can have changed the library — always refresh.
                _schedule_coverage_refresh()

        asyncio.create_task(_run())
        return job_id

    @app.post("/api/papers", status_code=202, dependencies=[Depends(require_active_workspace)])
    async def add_paper(body: _AddPaperBody) -> dict:
        target = body.target.strip() if body.target else ""
        if not target:
            raise HTTPException(status_code=400, detail="target is required and must not be empty")
        return {"job_id": _queue_add_paper(target)}

    # -----------------------------------------------------------------
    # POST /api/papers/upload  (raw PDF body — the browser file-picker path)
    # Registered before the {paper_id:path} routes so "upload" is never
    # captured as a paper id.
    # -----------------------------------------------------------------
    @app.post("/api/papers/upload", status_code=202, dependencies=[Depends(require_active_workspace)])
    async def upload_paper(request: Request, filename: str = "",
                           set_draft: bool = False) -> Any:
        from research_companion import fetch, store

        # CSRF defense: require a non-"simple" content type so a cross-origin POST
        # is forced through a CORS preflight (which this server does not answer),
        # blocking silent uploads from an arbitrary web page the user visits.
        ctype = request.headers.get("content-type", "").split(";")[0].strip().lower()
        if ctype not in ("application/pdf", "application/octet-stream"):
            raise HTTPException(status_code=415,
                                detail="upload must be application/pdf")

        # Cheap pre-check before buffering the body
        try:
            declared = int(request.headers.get("content-length", "0"))
        except ValueError:
            declared = 0
        if declared > _MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413,
                                detail="PDF exceeds the 50 MB upload limit")

        body = await request.body()
        if not body:
            raise HTTPException(status_code=400, detail="upload body is empty")
        if len(body) > _MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413,
                                detail="PDF exceeds the 50 MB upload limit")
        if not body.startswith(b"%PDF-"):
            raise HTTPException(
                status_code=400,
                detail="file does not look like a PDF (missing %PDF- header)")

        # Title from the (sanitized) client filename; never trust directories
        safe = Path(filename).name if filename else ""
        stem = safe[:-4] if safe.lower().endswith(".pdf") else safe
        title = (stem.strip() or "Uploaded PDF")[:120]

        # Duplicate: same content OR same arXiv id/DOI already in the library
        # (across id namespaces — e.g. this PDF is a copy of an arXiv paper).
        existing_id = store.find_existing_paper_for(body, filename=safe)
        if existing_id is not None:
            if set_draft:
                await _apply_draft(existing_id)
            return JSONResponse(status_code=200, content={
                "job_id": None, "paper_id": existing_id,
                "duplicate": True, "draft_set": set_draft,
            })

        meta = await asyncio.to_thread(
            fetch.add_local_pdf_bytes, body,
            source=f"upload://{safe or store.make_local_id(body)}", title=title,
        )
        # Metadata exists on disk now, so the draft can be set before the
        # background pipeline runs — no race by construction.
        if set_draft:
            await _apply_draft(meta.paper_id)

        app.state.job_counter += 1
        job_id = f"job-{app.state.job_counter}"
        up_label = f"Ingesting {safe or meta.paper_id}"
        app.state.jobs[job_id] = {"status": "running", "detail": None, "kind": "add",
                                  "label": up_label, "target": ""}

        if app.state.upload_override is not None:
            coro = app.state.upload_override(meta, bus)
        else:
            coro = _upload_paper_task(
                meta,
                bus,
                pipeline_overrides=app.state.pipeline_overrides,
            )

        async def _run_upload():
            await _announce_start(job_id, "add", up_label)
            try:
                await coro
                app.state.jobs[job_id] = {"status": "done", "detail": None, "kind": "add",
                                          "label": up_label, "target": ""}
                _schedule_coverage_refresh()
            except Exception as exc:
                app.state.jobs[job_id] = {"status": "failed", "detail": str(exc), "kind": "add",
                                          "label": up_label, "target": ""}
            finally:
                await _announce_finish(job_id, "add")

        asyncio.create_task(_run_upload())
        return {"job_id": job_id, "paper_id": meta.paper_id,
                "duplicate": False, "draft_set": set_draft}

    # -----------------------------------------------------------------
    # POST /api/papers/{id}/retry
    # -----------------------------------------------------------------
    @app.post("/api/papers/{paper_id:path}/retry", status_code=202, dependencies=[Depends(require_active_workspace)])
    async def retry_paper(paper_id: str) -> dict:
        from research_companion import store

        failures = store.list_failures()
        # Find a failure matching this paper_id
        matched_key = None
        for key, info in failures.items():
            if key == paper_id or info.get("paper_id") == paper_id:
                matched_key = key
                break

        if matched_key is None:
            raise HTTPException(status_code=404, detail=f"No failure record for {paper_id!r}")

        app.state.job_counter += 1
        job_id = f"job-{app.state.job_counter}"
        retry_label = f"Retrying {paper_id}"
        app.state.jobs[job_id] = {"status": "running", "detail": None, "kind": "retry",
                                  "label": retry_label, "target": ""}

        if app.state.retry_override is not None:
            coro = app.state.retry_override(matched_key, paper_id, bus)
        else:
            coro = _retry_paper_task(
                matched_key,
                paper_id,
                bus,
                pipeline_overrides=app.state.pipeline_overrides,
            )

        async def _run():
            await _announce_start(job_id, "retry", retry_label)
            try:
                await coro
                # clear_failure only on success — failure entry kept/updated on error.
                # Pass paper_id so stale entries recorded under a different key
                # (e.g. an earlier folder-path attempt) are cleared too.
                store.clear_failure(matched_key, paper_id=paper_id)
                app.state.jobs[job_id] = {"status": "done", "detail": None, "kind": "retry",
                                          "label": retry_label, "target": ""}
                _schedule_coverage_refresh()
            except Exception as exc:
                # Do NOT clear_failure — keep the failure record so the user can see it
                app.state.jobs[job_id] = {"status": "failed", "detail": str(exc), "kind": "retry",
                                          "label": retry_label, "target": ""}
            finally:
                await _announce_finish(job_id, "retry")

        asyncio.create_task(_run())
        return {"job_id": job_id}

    # -----------------------------------------------------------------
    # find-pdf: locate an open-access PDF for a paper whose ingest failed
    # because no PDF was available (the OA locator wired in Task 1/2).
    #
    # A "miss" (locate_pdf/download found nothing usable) is a COMPLETED
    # search, not a failed job -- the located candidate links (if any) are
    # persisted onto the failure record via store.record_failure (a
    # read-modify-write that preserves the original error/stage/paper_id)
    # and an IngestFailed event is published so the Library card re-renders
    # with them. A hit downloads the PDF, saves it, and re-runs the SAME
    # retry-flow job (_retry_paper_task) the /retry endpoint uses -- no
    # separate ingest pipeline is implemented here.
    # -----------------------------------------------------------------
    async def _find_pdf_for_failure(matched_key: str, paper_id: str) -> None:
        """Locate an OA PDF for one failed paper; on success save it and re-run
        the ingest pipeline (the retry task expects the PDF on disk); on miss
        persist the located links into the failure record and publish the
        failure event so the library card re-renders with them."""
        from research_companion import store
        from research_companion.agents.events import IngestFailed
        from research_companion.fetch import _try_download_pdf
        from research_companion.oa_locator import locate_pdf

        meta = store.PaperMetadata.load(paper_id)
        if meta is None:
            raise RuntimeError(f"no metadata for {paper_id!r}")

        loc = await asyncio.to_thread(locate_pdf, meta)
        pdf_bytes = None
        if loc.pdf_url:
            pdf_bytes = await asyncio.to_thread(_try_download_pdf, loc.pdf_url)

        if pdf_bytes is None:
            failures = store.list_failures()
            info = dict(failures.get(matched_key) or {})
            info["oa_links"] = loc.links
            info.setdefault("paper_id", paper_id)
            store.record_failure(matched_key, info)
            await bus.publish(IngestFailed(
                path=matched_key, stage="find-pdf",
                error=info.get("error") or "no open-access PDF found",
                paper_id=paper_id,
            ))
            raise _FindPdfMiss(len(loc.links))

        # _retry_paper_task's first arg is passed straight to
        # fetch.add_local_pdf, which requires an EXISTING filesystem path --
        # matched_key is the failure-record key (often a DOI/target string or
        # a stale path, exactly why the paper failed in the first place) and
        # must NOT be used here. Mirror upload_paper_pdf (~line 1015): save
        # the bytes first and pass the resulting on-disk path.
        pdf_path = await asyncio.to_thread(store.save_pdf, paper_id, pdf_bytes)
        await _retry_paper_task(str(pdf_path), paper_id, bus,
                                pipeline_overrides=app.state.pipeline_overrides)

    # -----------------------------------------------------------------
    # POST /api/papers/find-pdfs  (batch sweep — registered before the
    # {paper_id:path} routes so "find-pdfs" is never captured as a paper id,
    # mirroring how POST /api/papers/upload is registered before them)
    # -----------------------------------------------------------------
    @app.post("/api/papers/find-pdfs", status_code=202, dependencies=[Depends(require_active_workspace)])
    async def find_all_pdfs() -> Any:
        from research_companion import store

        if app.state.find_pdf_sweep_running:
            raise HTTPException(status_code=409,
                                detail="a find-pdfs sweep is already running")

        failures = store.list_failures()
        targets: list[tuple[str, str]] = []
        for key, info in failures.items():
            if not _is_missing_pdf_failure(info.get("error")):
                continue
            targets.append((key, info.get("paper_id") or key))

        if not targets:
            return JSONResponse(status_code=200, content={"count": 0})

        app.state.job_counter += 1
        job_id = f"job-{app.state.job_counter}"
        label = f"Finding PDFs for {len(targets)} papers"
        app.state.jobs[job_id] = {"status": "running", "detail": None, "kind": "find-pdf",
                                  "label": label, "target": ""}
        # Set synchronously (before the background task starts) so an
        # immediate second POST is guaranteed to see it and 409.
        app.state.find_pdf_sweep_running = True

        async def _run() -> None:
            try:
                # Inside the try (unlike the pre-existing add/retry/upload
                # endpoints) so a raise here can't wedge the job at "running"
                # forever -- the finally below always clears
                # find_pdf_sweep_running and announces the finish either way.
                await _announce_start(job_id, "find-pdf", label)
                for idx, (key, pid) in enumerate(targets):
                    try:
                        if app.state.find_pdf_override is not None:
                            await app.state.find_pdf_override(key, pid, bus)
                        else:
                            await _find_pdf_for_failure(key, pid)
                        # Success (a PDF was found and re-ingested) -- clear
                        # the failure the same way the single-paper endpoint
                        # does. A miss raises (handled below) so this line
                        # only runs on an actual hit.
                        store.clear_failure(key, paper_id=pid)
                    except Exception:
                        # One paper's miss/error must not stop the sweep --
                        # _find_pdf_for_failure already persisted whatever
                        # there was to persist (oa_links on miss, or nothing
                        # further to do on a genuine error).
                        pass
                    if idx < len(targets) - 1:
                        await asyncio.sleep(1.0)
                app.state.jobs[job_id] = {"status": "done", "detail": None, "kind": "find-pdf",
                                          "label": label, "target": ""}
                _schedule_coverage_refresh()
            finally:
                # MUST run even if something above raises unexpectedly --
                # otherwise the sweep flag is stuck True forever and every
                # future batch request 409s.
                app.state.find_pdf_sweep_running = False
                await _announce_finish(job_id, "find-pdf")

        asyncio.create_task(_run())
        return {"job_id": job_id, "count": len(targets)}

    # -----------------------------------------------------------------
    # POST /api/papers/{id}/find-pdf
    # -----------------------------------------------------------------
    @app.post("/api/papers/{paper_id:path}/find-pdf", status_code=202, dependencies=[Depends(require_active_workspace)])
    async def find_pdf(paper_id: str) -> dict:
        from research_companion import store

        failures = store.list_failures()
        matched_key = None
        matched_info: dict = {}
        for key, info in failures.items():
            if key == paper_id or info.get("paper_id") == paper_id:
                matched_key = key
                matched_info = info
                break

        if matched_key is None:
            raise HTTPException(status_code=404, detail=f"No failure record for {paper_id!r}")

        if not _is_missing_pdf_failure(matched_info.get("error")):
            raise HTTPException(status_code=409,
                                detail="failure is not a missing-PDF failure")

        app.state.job_counter += 1
        job_id = f"job-{app.state.job_counter}"
        label = f"Finding PDF for {paper_id}"
        app.state.jobs[job_id] = {"status": "running", "detail": None, "kind": "find-pdf",
                                  "label": label, "target": ""}

        if app.state.find_pdf_override is not None:
            coro = app.state.find_pdf_override(matched_key, paper_id, bus)
        else:
            coro = _find_pdf_for_failure(matched_key, paper_id)

        async def _run() -> None:
            try:
                # Inside the try (unlike the pre-existing add/retry/upload
                # endpoints) so a raise here can't wedge the job at "running"
                # forever -- it now falls through to the "except Exception"
                # below, which marks the job "failed", and the finally still
                # announces the finish either way.
                await _announce_start(job_id, "find-pdf", label)
                await coro
                # Success (a downloadable PDF was found and re-ingested) --
                # clear the failure the same way /retry does.
                store.clear_failure(matched_key, paper_id=paper_id)
                app.state.jobs[job_id] = {"status": "done", "detail": None, "kind": "find-pdf",
                                          "label": label, "target": ""}
                _schedule_coverage_refresh()
            except _FindPdfMiss as miss:
                # A miss is a completed search, not a failed job -- the
                # failure record (with oa_links) was already persisted by
                # _find_pdf_for_failure; do NOT clear it.
                app.state.jobs[job_id] = {
                    "status": "done",
                    "detail": f"no open-access PDF found ({miss.link_count} links)",
                    "kind": "find-pdf", "label": label, "target": "",
                }
            except Exception as exc:
                app.state.jobs[job_id] = {"status": "failed", "detail": str(exc), "kind": "find-pdf",
                                          "label": label, "target": ""}
            finally:
                await _announce_finish(job_id, "find-pdf")

        asyncio.create_task(_run())
        return {"job_id": job_id}

    # -----------------------------------------------------------------
    # POST /api/papers/{id}/pdf
    # Upload a replacement PDF for an EXISTING paper (the "no PDF on disk" /
    # "PDF not found" Library hint) and kick the SAME retry-flow re-ingest as
    # POST /api/papers/{id}/retry — no separate pipeline is implemented here.
    #
    # Invariant enforced server-side (not just by the client UI): this only
    # ever replaces a PDF the paper NEEDS — i.e. it has no PDF on disk yet,
    # OR it has a failure record (a failed re-ingest, possibly from a corrupt
    # PDF, is always re-uploadable). A healthy paper that already has a PDF
    # and no failure record is rejected with 409 so a stray/careless request
    # can't silently overwrite good text/analysis.
    #
    # Raw-body upload, same CSRF/size/magic-byte checks as
    # POST /api/papers/upload (see there for the full rationale): a "simple"
    # cross-origin content type is rejected so a hostile page cannot silently
    # POST bytes to this endpoint without a CORS preflight this server never
    # answers.
    # -----------------------------------------------------------------
    @app.post("/api/papers/{paper_id:path}/pdf", status_code=202, dependencies=[Depends(require_active_workspace)])
    async def upload_paper_pdf(paper_id: str, request: Request) -> dict:
        from research_companion import store

        meta = await asyncio.to_thread(store.PaperMetadata.load, paper_id)
        if meta is None:
            raise HTTPException(status_code=404, detail=f"Paper not found: {paper_id!r}")

        existing_pdf = await asyncio.to_thread(store.pdf_path, paper_id)
        if existing_pdf is not None:
            failures = await asyncio.to_thread(store.list_failures)
            has_failure = any(
                key == paper_id or info.get("paper_id") == paper_id
                for key, info in failures.items()
            )
            if not has_failure:
                raise HTTPException(
                    status_code=409,
                    detail="paper already has a PDF — remove it first or use retry")

        ctype = request.headers.get("content-type", "").split(";")[0].strip().lower()
        if ctype not in ("application/pdf", "application/octet-stream"):
            raise HTTPException(status_code=415,
                                detail="upload must be application/pdf")

        try:
            declared = int(request.headers.get("content-length", "0"))
        except ValueError:
            declared = 0
        if declared > _MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413,
                                detail="PDF exceeds the 50 MB upload limit")

        body = await request.body()
        if not body:
            raise HTTPException(status_code=400, detail="upload body is empty")
        if len(body) > _MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413,
                                detail="PDF exceeds the 50 MB upload limit")
        if not body.startswith(b"%PDF-"):
            raise HTTPException(
                status_code=400,
                detail="file does not look like a PDF (missing %PDF- header)")

        pdf_path = await asyncio.to_thread(store.save_pdf, paper_id, body)
        path_str = str(pdf_path)

        app.state.job_counter += 1
        job_id = f"job-{app.state.job_counter}"
        retry_label = f"Retrying {paper_id}"
        app.state.jobs[job_id] = {"status": "running", "detail": None, "kind": "retry",
                                  "label": retry_label, "target": ""}

        if app.state.retry_override is not None:
            coro = app.state.retry_override(path_str, paper_id, bus)
        else:
            coro = _retry_paper_task(
                path_str,
                paper_id,
                bus,
                pipeline_overrides=app.state.pipeline_overrides,
            )

        async def _run():
            await _announce_start(job_id, "retry", retry_label)
            try:
                await coro
                # Same clear_failure semantics as /retry: drop the entry keyed
                # by the just-saved pdf path AND any stale entry recorded
                # under a different key for this paper_id (e.g. the original
                # "no PDF on disk" record from the first ingest attempt).
                store.clear_failure(path_str, paper_id=paper_id)
                app.state.jobs[job_id] = {"status": "done", "detail": None, "kind": "retry",
                                          "label": retry_label, "target": ""}
                _schedule_coverage_refresh()
            except Exception as exc:
                app.state.jobs[job_id] = {"status": "failed", "detail": str(exc), "kind": "retry",
                                          "label": retry_label, "target": ""}
            finally:
                await _announce_finish(job_id, "retry")

        asyncio.create_task(_run())
        return {"job_id": job_id, "paper_id": paper_id}

    # -----------------------------------------------------------------
    # DELETE /api/papers/{id}
    # -----------------------------------------------------------------
    @app.delete("/api/papers/{paper_id:path}", dependencies=[Depends(require_active_workspace)])
    async def delete_paper(paper_id: str) -> dict:
        from research_companion import store
        from research_companion.graph import build_graph, save_graph

        removed = await asyncio.to_thread(store.remove_paper, paper_id)
        if not removed:
            raise HTTPException(status_code=404, detail=f"Paper not found: {paper_id!r}")

        # Clear a stale draft pointer before the coverage refresh reads it
        draft_cleared = False
        if store.get_draft_paper_id() == paper_id:
            await asyncio.to_thread(store.set_draft_paper_id, None)
            draft_cleared = True

        # Rebuild and save graph
        try:
            G = await asyncio.to_thread(build_graph)
            await asyncio.to_thread(save_graph, G)
        except Exception:
            pass  # Non-fatal; graph rebuild failure doesn't undo removal

        _schedule_coverage_refresh()
        return {"removed": True, "draft_cleared": draft_cleared}

    # -----------------------------------------------------------------
    # PATCH /api/papers/{id}  (manual title/authors/year edit)
    # -----------------------------------------------------------------
    @app.patch("/api/papers/{paper_id:path}", dependencies=[Depends(require_active_workspace)])
    async def patch_paper(paper_id: str, body: _PatchPaperBody) -> dict:
        from research_companion import store
        from research_companion.prompts import extraction_prompt_sha256

        # Load first so unknown ids 404 (mirrors DELETE + the view PATCH).
        existing = await asyncio.to_thread(store.PaperMetadata.load, paper_id)
        if existing is None:
            raise HTTPException(status_code=404, detail=f"Paper not found: {paper_id!r}")

        # Forward only fields the client actually sent (pydantic v2/v1 compat),
        # passing None through so a sent-but-null field clears (year). The store
        # sentinel distinguishes "omitted" from "explicit None".
        try:
            provided = body.model_fields_set
        except AttributeError:
            provided = body.__fields_set__  # type: ignore[attr-defined]

        kwargs: dict = {}
        if "title" in provided:
            kwargs["title"] = body.title
        if "authors" in provided:
            kwargs["authors"] = body.authors
        if "year" in provided:
            year = body.year
            if year is not None and not (1900 <= year <= 2100):
                raise HTTPException(
                    status_code=422, detail="year must be between 1900 and 2100")
            kwargs["year"] = year

        meta = await asyncio.to_thread(store.update_paper_metadata, paper_id, **kwargs)
        if meta is None:  # concurrent delete between the load and the write
            raise HTTPException(status_code=404, detail=f"Paper not found: {paper_id!r}")

        # Edited authors/year can flip citation-coverage matches; also nudges
        # clients to refresh the library (DELETE relies on the same refetch).
        _schedule_coverage_refresh()

        return _build_paper_summary(
            meta,
            failures=store.list_failures(),
            draft_id=store.get_draft_paper_id(),
            prompt_sha=extraction_prompt_sha256(),
        )

    # -----------------------------------------------------------------
    # GET /api/draft
    # -----------------------------------------------------------------
    @app.get("/api/draft")
    async def get_draft() -> dict:
        from research_companion import store
        return {"draft_paper_id": store.get_draft_paper_id()}

    # -----------------------------------------------------------------
    # POST /api/draft
    # -----------------------------------------------------------------
    async def _recompute_coverage_bg() -> None:
        """Refresh citation coverage after library/draft changes (non-fatal).

        With auto_add_citations on (the default), missing cited papers with a
        downloadable id are queued automatically, and title-only refs get one
        automatic resolution pass — what remains "unresolved" is exactly what
        the panel presents as not downloadable.
        """
        with suppress(Exception):
            from research_companion import store
            from research_companion.agents.events import CitationCoverageUpdated
            from research_companion.citations_coverage import (
                _recount,
                compute_coverage,
                find_library_duplicate,
                save_coverage,
            )
            from research_companion.refcheck.validate import Reference
            from research_companion.settings import get_settings

            draft_id = store.get_draft_paper_id()
            if draft_id is None:
                return
            auto_add = get_settings().get("auto_add_citations", True)
            async with app.state._coverage_lock:
                payload = await asyncio.to_thread(compute_coverage, draft_id)
                # Dedup-before-add: an "available" ref whose work is already in
                # the library (e.g. an uploaded local: PDF, or a resolved id we
                # already hold) is marked in_library instead of being downloaded
                # again. Mutation + persist stay inside the coverage lock so the
                # published counts reflect the dedup without a second race.
                if payload.get("source") != "none" and auto_add:
                    papers = await asyncio.to_thread(store.list_papers)
                    deduped = False
                    for rec in payload.get("references", []):
                        if rec.get("status") != "available" or not rec.get("add_target"):
                            continue
                        ref = Reference(
                            title=rec.get("title") or rec.get("raw") or "", authors=[],
                            year=rec.get("year"), doi=rec.get("doi"),
                            arxiv_id=rec.get("arxiv_id"), url=None, raw=rec.get("raw") or "")
                        dup = find_library_duplicate(ref, papers, resolved=rec)
                        if dup:
                            rec["status"] = "in_library"
                            rec["matched_paper_id"] = dup
                            rec["match_kind"] = "dedup"
                            rec["add_target"] = None
                            deduped = True
                    if deduped:
                        _recount(payload)
                        await asyncio.to_thread(save_coverage, payload)
            if payload.get("source") == "none":
                return
            await bus.publish(CitationCoverageUpdated(
                draft_paper_id=draft_id, **payload["counts"]))

            if not auto_add:
                return

            # Auto-queue downloads for available refs (session-deduped so a
            # failing add cannot retry-storm; the row keeps its manual button)
            for rec in payload.get("references", []):
                target = rec.get("add_target")
                if (rec.get("status") == "available" and target
                        and target not in app.state.auto_added_targets):
                    app.state.auto_added_targets.add(target)
                    _queue_add_paper(target)

            # One automatic resolution pass per draft text (resolved_at is the
            # marker); newly available refs auto-queue on the next refresh.
            if (payload["counts"].get("unchecked", 0) > 0
                    and payload.get("resolved_at") is None):
                _start_resolve_job(draft_id)

    def _schedule_coverage_refresh() -> None:
        with suppress(Exception):
            asyncio.get_running_loop()
            asyncio.create_task(_recompute_coverage_bg())

    # -----------------------------------------------------------------
    # One-shot weak-metadata backfill (Task 5)
    # -----------------------------------------------------------------
    def _queue_backfill(meta) -> str:
        """Enqueue a re-extraction job for an existing stored paper.

        Reuses the single-paper pipeline body (`_run_paper_pipeline`) so
        extraction/metadata-backfill, graph rebuild, alignment, activity
        announce and coverage refresh behave exactly like add/retry.
        """
        app.state.job_counter += 1
        job_id = f"job-{app.state.job_counter}"
        pid = meta.paper_id
        label = "Reading metadata…"
        app.state.jobs[job_id] = {"status": "running", "detail": None, "kind": "backfill",
                                  "label": label, "target": pid}

        if app.state.backfill_override is not None:
            coro = app.state.backfill_override(meta, bus)
        else:
            coro = _run_paper_pipeline(
                meta, meta.source_url or pid, bus,
                pipeline_overrides=app.state.pipeline_overrides,
            )

        async def _run():
            await _announce_start(job_id, "backfill", label, pid)
            try:
                await coro
                app.state.jobs[job_id] = {"status": "done", "detail": None, "kind": "backfill",
                                          "label": label, "target": pid}
                _schedule_coverage_refresh()
            except Exception as exc:
                app.state.jobs[job_id] = {"status": "failed", "detail": str(exc), "kind": "backfill",
                                          "label": label, "target": pid}
            finally:
                await _announce_finish(job_id, "backfill")

        asyncio.create_task(_run())
        return job_id

    async def _backfill_weak_metadata_bg() -> None:
        """Re-run extraction for existing papers with weak metadata (non-fatal).

        Select a paper iff ALL hold:
          - meta.year is None (weak — the timeline blocker),
          - it has non-empty text (scanned/empty-text papers can't be
            backfilled and must never spin),
          - its extraction is stale/absent for the current prompt
            (`load_extraction(pid, prompt_sha=...) is None`).
        The last guard is the idempotency key: once a paper re-extracts with the
        current prompt, load_extraction returns non-None → it is never selected
        again, even if year stays None. Papers currently being processed (a
        running job targets them) are skipped to avoid double work.
        """
        with suppress(Exception):
            from research_companion import store
            from research_companion.prompts import extraction_prompt_sha256

            prompt_sha = extraction_prompt_sha256()
            running_targets = {
                info.get("target")
                for info in app.state.jobs.values()
                if info.get("status") == "running"
            }
            for meta in await asyncio.to_thread(store.list_papers):
                pid = meta.paper_id
                if meta.year is not None:
                    continue
                if pid in running_targets:
                    continue
                text = await asyncio.to_thread(store.load_text, pid)
                if not text:
                    continue
                stale = await asyncio.to_thread(
                    store.load_extraction, pid, prompt_sha=prompt_sha)
                if stale is not None:
                    continue
                _queue_backfill(meta)

    async def _maybe_backfill_active_workspace() -> None:
        """Trigger the one-shot backfill for the active workspace, at most once
        per workspace per session. Non-fatal."""
        with suppress(Exception):
            from research_companion import store
            ws = store.active_workspace_id()
            if ws in app.state._backfilled_workspaces:
                return
            app.state._backfilled_workspaces.add(ws)
            await _backfill_weak_metadata_bg()

    app.state._trigger_backfill = _maybe_backfill_active_workspace

    async def _apply_draft(paper_id: str | None) -> None:
        """Set the draft + journey record + suggestion auto-match.

        Shared by POST /api/draft and POST /api/papers/upload so the journey
        version record (and its suggestions-store migration) is never duplicated.
        Caller is responsible for validating that the paper exists.
        """
        from research_companion import store

        await asyncio.to_thread(store.set_draft_paper_id, paper_id)

        # Journey: record new draft version; spawn background suggestion matching
        if paper_id is not None:
            try:
                from research_companion.agents.events import DraftVersionAdded
                from research_companion.journey import match_open_suggestions, record_draft_version

                ver = await asyncio.to_thread(record_draft_version, paper_id)
                if ver is not None:
                    await bus.publish(DraftVersionAdded(
                        paper_id=paper_id,
                        version=ver["version"],
                    ))

                    async def _bg_match():
                        with suppress(Exception):
                            await asyncio.to_thread(
                                match_open_suggestions,
                                paper_id,
                                llm=app.state.llm,
                            )

                    asyncio.create_task(_bg_match())
            except Exception:  # noqa: BLE001
                pass

        _schedule_coverage_refresh()

    @app.post("/api/draft", dependencies=[Depends(require_active_workspace)])
    async def set_draft(body: _DraftBody) -> dict:
        from research_companion import store

        paper_id = body.paper_id

        if paper_id is not None:
            meta = store.PaperMetadata.load(paper_id)
            if meta is None:
                raise HTTPException(status_code=404, detail=f"Paper not found: {paper_id!r}")

        await _apply_draft(paper_id)

        return {"draft_paper_id": paper_id}

    # -----------------------------------------------------------------
    # GET /api/sections
    # -----------------------------------------------------------------
    @app.get("/api/sections")
    async def get_sections() -> list:
        from research_companion import store
        from research_companion.graph import load_graph, section_subgraph

        draft_id = store.get_draft_paper_id()
        if draft_id is None:
            return []

        sections_payload = store.load_sections(draft_id)
        if sections_payload is None:
            return []

        G = load_graph()
        result = []
        for sec in sections_payload.get("sections", []):
            sec_id = sec["section_id"]
            sub = section_subgraph(G, draft_id, sec_id)
            # node_count = number of non-paper nodes in subgraph
            node_count = sum(
                1 for _, d in sub.nodes(data=True) if d.get("kind") != "paper"
            )
            result.append({
                "section_id": sec_id,
                "index": sec.get("index", 0),
                "title": sec.get("title", ""),
                "level": sec.get("level", 1),
                "node_count": node_count,
            })

        return result

    # -----------------------------------------------------------------
    # Citation coverage — the draft's bibliography vs the library (W5-C2)
    # -----------------------------------------------------------------
    @app.get("/api/draft/citations")
    async def get_draft_citations() -> dict:
        from research_companion import store
        from research_companion.citations_coverage import (
            compute_coverage,
            empty_coverage,
            is_stale,
            load_coverage,
        )

        draft_id = store.get_draft_paper_id()
        if draft_id is None:
            return empty_coverage(None)

        payload = await asyncio.to_thread(load_coverage)
        if await asyncio.to_thread(is_stale, payload, draft_id):
            payload = await asyncio.to_thread(compute_coverage, draft_id)
        return payload

    def _start_resolve_job(draft_id: str) -> str | None:
        """Start the citation resolve job; None when one is already running."""
        from research_companion.agents.events import CitationCoverageUpdated
        from research_companion.citations_coverage import (
            compute_coverage,
            is_stale,
            load_coverage,
            resolve_missing,
        )

        if any(j.get("status") == "running" and j.get("kind") == "citations"
               for j in app.state.jobs.values()):
            return None

        app.state.job_counter += 1
        job_id = f"job-{app.state.job_counter}"
        cite_label = "Checking references…"
        app.state.jobs[job_id] = {"status": "running", "detail": None, "kind": "citations",
                                  "label": cite_label, "target": ""}

        async def _run_resolve():
            await _announce_start(job_id, "citations", cite_label)
            try:
                async with app.state._coverage_lock:
                    payload = await asyncio.to_thread(load_coverage)
                    if await asyncio.to_thread(is_stale, payload, draft_id):
                        payload = await asyncio.to_thread(compute_coverage, draft_id)
                    resolver = app.state.citations_resolver_override
                    if resolver is not None:
                        payload = await asyncio.to_thread(
                            resolve_missing, payload, resolver=resolver)
                    else:
                        payload = await asyncio.to_thread(resolve_missing, payload)
                await bus.publish(CitationCoverageUpdated(
                    draft_paper_id=draft_id, **payload["counts"]))
                app.state.jobs[job_id] = {"status": "done", "detail": None, "kind": "citations",
                                          "label": cite_label, "target": ""}
                # Newly resolved refs become available — the refresh auto-queues
                # their downloads when auto_add_citations is on.
                _schedule_coverage_refresh()
            except Exception as exc:  # noqa: BLE001
                app.state.jobs[job_id] = {"status": "failed", "detail": str(exc), "kind": "citations",
                                          "label": cite_label, "target": ""}
            finally:
                await _announce_finish(job_id, "citations")

        asyncio.create_task(_run_resolve())
        return job_id

    @app.post("/api/draft/citations/resolve", status_code=202, dependencies=[Depends(require_active_workspace)])
    async def resolve_draft_citations() -> dict:
        from research_companion import store

        draft_id = store.get_draft_paper_id()
        if draft_id is None:
            raise HTTPException(status_code=400, detail="No draft configured.")
        job_id = _start_resolve_job(draft_id)
        if job_id is None:
            raise HTTPException(
                status_code=409,
                detail="A citation resolve job is already running")
        return {"job_id": job_id}

    @app.post("/api/draft/citations/link", dependencies=[Depends(require_active_workspace)])
    async def link_draft_citation(body: _LinkCitationBody) -> dict:
        """Assert that cited reference `index` IS library paper `paper_id`.

        Records a durable manual link (match_kind="manual") that survives
        coverage recompute and reverts if the paper is later deleted, and
        backfills the paper's YEAR (year-only) from the citation so it lands on
        the timeline. Returns the full updated coverage dict.
        """
        from research_companion import store
        from research_companion.agents.events import CitationCoverageUpdated
        from research_companion.citations_coverage import (
            _recount,
            compute_coverage,
            is_stale,
            load_coverage,
            save_coverage,
        )

        draft_id = store.get_draft_paper_id()
        if draft_id is None:
            raise HTTPException(status_code=400, detail="No draft set")

        meta = await asyncio.to_thread(store.PaperMetadata.load, body.paper_id)
        if meta is None:
            raise HTTPException(
                status_code=404, detail=f"Paper not found: {body.paper_id!r}")

        # Coverage read-modify-write stays inside the shared lock and persists
        # exactly once so concurrent refresh/resolve jobs cannot clobber it.
        async with app.state._coverage_lock:
            payload = await asyncio.to_thread(load_coverage)
            if await asyncio.to_thread(is_stale, payload, draft_id):
                payload = await asyncio.to_thread(compute_coverage, draft_id)
            refs = (payload or {}).get("references") or []
            if not refs:
                raise HTTPException(status_code=400, detail="No citations to link")
            if body.index < 0 or body.index >= len(refs):
                raise HTTPException(
                    status_code=400, detail="citation index out of range")
            rec = refs[body.index]
            ref_year = rec.get("year")
            rec["status"] = "in_library"
            rec["matched_paper_id"] = body.paper_id
            rec["match_kind"] = "manual"
            _recount(payload)
            await asyncio.to_thread(save_coverage, payload)

        # Year-only backfill: never touch title/authors, only fill a missing
        # year from a plausible citation year.
        if (meta.year is None and isinstance(ref_year, int)
                and 1900 <= ref_year <= 2100):
            await asyncio.to_thread(
                store.update_paper_metadata, body.paper_id, year=ref_year)

        await bus.publish(CitationCoverageUpdated(
            draft_paper_id=draft_id, **payload["counts"]))
        _schedule_coverage_refresh()
        return payload

    @app.post("/api/draft/citations/unlink", dependencies=[Depends(require_active_workspace)])
    async def unlink_draft_citation(body: _UnlinkCitationBody) -> dict:
        """Undo a manual link created by POST /api/draft/citations/link.

        Only a `match_kind == "manual"` ref can be unlinked (400 otherwise — a
        wrong manual link was previously permanent short of deleting the
        paper). Clears the manual mark and re-derives the natural status via
        `compute_coverage`: the carry-forward path in compute_coverage only
        resurrects a ref whose PERSISTED record still has match_kind=="manual"
        (or status=="in_library" for the dedup-carryover branch), so saving
        the cleared record first (match_kind=None, status="unchecked") before
        recomputing guarantees the link is not resurrected.
        """
        from research_companion import store
        from research_companion.agents.events import CitationCoverageUpdated
        from research_companion.citations_coverage import (
            compute_coverage,
            is_stale,
            load_coverage,
            save_coverage,
        )

        draft_id = store.get_draft_paper_id()
        if draft_id is None:
            raise HTTPException(status_code=400, detail="No draft set")

        # Coverage read-modify-write stays inside the shared lock and persists
        # exactly once so concurrent refresh/resolve jobs cannot clobber it.
        async with app.state._coverage_lock:
            payload = await asyncio.to_thread(load_coverage)
            if await asyncio.to_thread(is_stale, payload, draft_id):
                payload = await asyncio.to_thread(compute_coverage, draft_id)
            refs = (payload or {}).get("references") or []
            if not refs:
                raise HTTPException(status_code=400, detail="No citations to unlink")
            if body.index < 0 or body.index >= len(refs):
                raise HTTPException(
                    status_code=400, detail="citation index out of range")
            rec = refs[body.index]
            if rec.get("match_kind") != "manual":
                raise HTTPException(
                    status_code=400, detail="citation is not a manual link")
            rec["match_kind"] = None
            rec["matched_paper_id"] = None
            rec["status"] = "unchecked"
            await asyncio.to_thread(save_coverage, payload)
            # Re-derive the natural status now that the persisted record no
            # longer carries a manual mark for this raw entry.
            payload = await asyncio.to_thread(compute_coverage, draft_id)

        await bus.publish(CitationCoverageUpdated(
            draft_paper_id=draft_id, **payload["counts"]))
        _schedule_coverage_refresh()
        return payload

    # -----------------------------------------------------------------
    # GET /api/draft/alignment
    # -----------------------------------------------------------------
    @app.get("/api/draft/alignment")
    async def get_draft_alignment() -> dict:
        from research_companion import store

        draft_id = store.get_draft_paper_id()
        if draft_id is None:
            return {"draft_id": None, "sections": []}

        papers = store.list_papers()
        # Map section_id -> {title, alignments: [...]}
        sections_map: dict[str, dict] = {}

        for meta in papers:
            if meta.paper_id == draft_id:
                continue
            alignment = store.load_alignment(meta.paper_id, draft_paper_id=draft_id)
            if alignment is None:
                continue

            for sec in alignment.get("sections", []):
                sec_id = sec.get("section_id", "")
                sec_title = sec.get("section_title", sec_id)

                if sec_id not in sections_map:
                    sections_map[sec_id] = {
                        "section_id": sec_id,
                        "title": sec_title,
                        "alignments": [],
                    }

                sections_map[sec_id]["alignments"].append({
                    "paper_id": meta.paper_id,
                    "paper_title": meta.title,
                    "relation": sec.get("relation", ""),
                    "relevance": sec.get("relevance", 0.0),
                    "rationale": sec.get("rationale", ""),
                    "evidence": sec.get("evidence", []),
                    "score": alignment.get("score", 0.0),
                    "verdict": alignment.get("verdict", ""),
                })

        return {
            "draft_id": draft_id,
            "sections": list(sections_map.values()),
        }

    # -----------------------------------------------------------------
    # GET /api/draft/opportunities — uncited library papers that would
    # strengthen/challenge/offer alternatives to draft sections, assembled
    # strictly from stored analysis (no LLM, no network).
    # -----------------------------------------------------------------
    @app.get("/api/draft/opportunities")
    async def get_draft_opportunities() -> dict:
        from research_companion import store
        from research_companion.opportunities import build_opportunities

        draft_id = store.get_draft_paper_id()
        return await asyncio.to_thread(build_opportunities, draft_id)

    # -----------------------------------------------------------------
    # Citation placement — is each cited paper in the right section?
    # (draft-quality check; separate from strength scoring)
    # -----------------------------------------------------------------
    @app.get("/api/draft/placement")
    async def get_draft_placement() -> dict:
        from research_companion import store
        from research_companion.citation_placement import (
            compute_placement,
            empty_placement,
            is_stale,
            load_placement,
        )

        draft_id = store.get_draft_paper_id()
        if draft_id is None:
            return empty_placement(None)

        payload = await asyncio.to_thread(load_placement)
        if await asyncio.to_thread(is_stale, payload, draft_id):
            payload = await asyncio.to_thread(compute_placement, draft_id)
        return payload

    # -----------------------------------------------------------------
    # Revision notes — workspace-scoped notes captured from opportunity
    # suggestions (research_companion.notes_store, papergraph_dir()/notes.json).
    #
    # GET /api/notes/export is registered BEFORE /api/notes/{note_id} so
    # "export" is never captured as a note_id, mirroring how POST
    # /api/papers/find-pdfs is registered before /api/papers/{paper_id:path}.
    # -----------------------------------------------------------------
    @app.get("/api/notes")
    async def list_notes_endpoint() -> dict:
        from research_companion.notes_store import list_notes
        return {"notes": await asyncio.to_thread(list_notes)}

    @app.post("/api/notes", dependencies=[Depends(require_active_workspace)])
    async def create_note_endpoint(body: dict) -> dict:
        from research_companion.notes_store import save_note
        kind = body.get("kind") or "freeform"
        if kind not in ("opportunity", "alignment", "reader", "paper", "ask", "freeform"):
            raise HTTPException(status_code=400, detail="invalid note kind")
        if not (body.get("comment") or body.get("paper_id")
                or body.get("source_excerpt") or body.get("evidence_quote")):
            raise HTTPException(status_code=400, detail="note is empty")
        body["kind"] = kind
        return await asyncio.to_thread(save_note, body)

    @app.get("/api/notes/export")
    async def export_notes_endpoint(group_by: str = "section") -> dict:
        from research_companion.notes_store import list_notes, notes_to_markdown
        if group_by not in ("section", "paper"):
            group_by = "section"
        notes = await asyncio.to_thread(list_notes)
        return {"markdown": notes_to_markdown(notes, group_by=group_by)}

    @app.patch("/api/notes/{note_id}", dependencies=[Depends(require_active_workspace)])
    async def patch_note_endpoint(note_id: str, body: dict) -> dict:
        from research_companion.notes_store import update_note
        status = body.get("status")
        if status is not None and status not in ("open", "done", "dismissed"):
            raise HTTPException(status_code=400, detail="invalid status")
        note = await asyncio.to_thread(update_note, note_id,
                                       status=status, comment=body.get("comment"))
        if note is None:
            raise HTTPException(status_code=404, detail="note not found")
        return note

    @app.delete("/api/notes/{note_id}", dependencies=[Depends(require_active_workspace)])
    async def delete_note_endpoint(note_id: str) -> dict:
        from research_companion.notes_store import delete_note
        ok = await asyncio.to_thread(delete_note, note_id)
        if not ok:
            raise HTTPException(status_code=404, detail="note not found")
        return {"deleted": note_id}

    # -----------------------------------------------------------------
    # GET /api/papers/{id}/alignment
    # -----------------------------------------------------------------
    @app.get("/api/papers/{paper_id:path}/alignment")
    async def get_paper_alignment(paper_id: str) -> dict:
        from research_companion import store

        draft_id = store.get_draft_paper_id()
        alignment = store.load_alignment(paper_id, draft_paper_id=draft_id)
        if alignment is None:
            raise HTTPException(status_code=404,
                                detail=f"No alignment for {paper_id!r}")
        return alignment

    # -----------------------------------------------------------------
    # GET /api/papers/{id}/text — reader full text + section offsets
    # (distinct suffix, so no collision with the DELETE {id} route)
    # -----------------------------------------------------------------
    @app.get("/api/papers/{paper_id:path}/text")
    async def get_paper_text(paper_id: str, q: str | None = None) -> dict:
        from research_companion import store
        from research_companion.rebuttal.verify import locate_quote

        text = await asyncio.to_thread(store.load_text, paper_id)
        if text is None:
            raise HTTPException(status_code=404, detail=f"No text for paper: {paper_id!r}")

        meta = await asyncio.to_thread(store.PaperMetadata.load, paper_id)
        title = meta.title if meta else paper_id

        payload = await asyncio.to_thread(store.load_sections, paper_id)
        stored = payload.get("sections", []) if payload else []
        if stored:
            sections = [
                {
                    "section_id": s["section_id"],
                    "title": s["title"],
                    "level": s["level"],
                    "char_start": s["char_start"],
                    "char_end": s["char_end"],
                }
                for s in stored
            ]
        else:
            # Mirror qa.py's whole-paper fallback when no sections exist.
            sections = [{"section_id": "s1", "title": "Full text", "level": 1,
                         "char_start": 0, "char_end": len(text)}]

        has_pdf = await asyncio.to_thread(store.pdf_path, paper_id) is not None

        quote_range = None
        if q:
            r = locate_quote(q, text)
            quote_range = [r[0], r[1]] if r else None

        return {
            "paper_id": paper_id,
            "title": title,
            "full_text": text,
            "has_pdf": has_pdf,
            "sections": sections,
            "quote_range": quote_range,
        }

    # -----------------------------------------------------------------
    # GET /api/papers/{id}/pdf — stream the stored PDF inline
    # Path is mapped through store.pdf_path (_id_to_dirname), never built
    # from the raw id, so it is safe against traversal.
    # -----------------------------------------------------------------
    @app.get("/api/papers/{paper_id:path}/pdf")
    async def get_paper_pdf(paper_id: str):
        from research_companion import store

        p = await asyncio.to_thread(store.pdf_path, paper_id)
        if p is None:
            raise HTTPException(status_code=404, detail=f"No PDF for paper: {paper_id!r}")
        return FileResponse(
            p,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{paper_id}.pdf"'},
        )

    # -----------------------------------------------------------------
    # GET /api/papers/{id}/simplified — reader "Simplified" tab payload
    # (distinct suffix from /text and /pdf above; no route collision)
    # -----------------------------------------------------------------
    @app.get("/api/papers/{paper_id:path}/simplified")
    async def get_simplified(paper_id: str) -> dict:
        from research_companion import store
        from research_companion.prompts import extraction_prompt_sha256

        meta = await asyncio.to_thread(store.PaperMetadata.load, paper_id)
        if meta is None:
            raise HTTPException(status_code=404, detail=f"Paper not found: {paper_id!r}")
        extraction = await asyncio.to_thread(
            store.load_extraction, paper_id, prompt_sha=extraction_prompt_sha256())
        rewrite = await asyncio.to_thread(store.load_simplified, paper_id)
        return {
            "extraction": extraction,
            "rewrite": rewrite,
            "has_extraction": extraction is not None,
            "provider_configured": _llm_provider_configured(),
        }

    # -----------------------------------------------------------------
    # POST /api/papers/{id}/simplify — on-demand LLM "Simplify further" job
    # -----------------------------------------------------------------
    @app.post("/api/papers/{paper_id:path}/simplify", status_code=202, dependencies=[Depends(require_active_workspace)])
    async def simplify_paper(paper_id: str) -> dict:
        from datetime import datetime, timezone

        from research_companion import store

        text = await asyncio.to_thread(store.load_text, paper_id)
        if text is None:
            raise HTTPException(status_code=409,
                                detail="paper has no stored text to simplify")

        app.state.job_counter += 1
        job_id = f"job-{app.state.job_counter}"
        label = f"Simplifying {paper_id}"
        app.state.jobs[job_id] = {"status": "running", "detail": None,
                                  "kind": "simplify", "label": label, "target": ""}

        async def _do_simplify() -> None:
            sections_payload = await asyncio.to_thread(store.load_sections, paper_id)
            meta = await asyncio.to_thread(store.PaperMetadata.load, paper_id)
            stored = (sections_payload or {}).get("sections", [])
            # Section blocks: id + title + text, respecting the char budget
            # convention (same settings["char_budget"] accessor qa.answer
            # uses). Full-paper simplify intentionally ignores k_sections
            # (that knob scopes RETRIEVAL to the top-k matching sections;
            # simplify has no query, it walks every section in document
            # order until the budget is spent) and uses char_budget alone.
            blocks, budget = [], _simplify_char_budget()
            used = 0
            for s in stored:
                seg = f"[{s['section_id']}] {s.get('title') or ''}\n{s.get('text') or ''}\n"
                if used + len(seg) > budget:
                    seg = seg[: max(0, budget - used)]
                blocks.append(seg)
                used += len(seg)
                if used >= budget:
                    break
            prompt = _SIMPLIFY_PROMPT.replace("{title}", (meta.title if meta else paper_id)) \
                                     .replace("{sections_block}", "".join(blocks) or text[:budget])
            llm = _resolve_llm(json_mode=True)
            raw = await asyncio.to_thread(llm, prompt)
            if isinstance(raw, str):
                from research_companion.extract import _strip_code_fences
                data = json.loads(_strip_code_fences(raw))
            else:
                data = raw
            groups = data.get("groups") if isinstance(data, dict) else None
            if not isinstance(groups, list):
                raise RuntimeError("simplify: LLM returned no groups")
            provider, model = _pipeline_provider_model()
            await asyncio.to_thread(store.save_simplified, paper_id, {
                "provider": provider, "model": model,
                "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "groups": groups,
            })

        if app.state.simplify_override is not None:
            coro = app.state.simplify_override(paper_id)
        else:
            coro = _do_simplify()

        async def _run() -> None:
            try:
                await _announce_start(job_id, "simplify", label)
                await coro
                app.state.jobs[job_id] = {"status": "done", "detail": None,
                                          "kind": "simplify", "label": label, "target": ""}
            except Exception as exc:
                app.state.jobs[job_id] = {"status": "failed", "detail": str(exc),
                                          "kind": "simplify", "label": label, "target": ""}
            finally:
                await _announce_finish(job_id, "simplify")

        asyncio.create_task(_run())
        return {"job_id": job_id}

    # -----------------------------------------------------------------
    # GET /api/graph
    # -----------------------------------------------------------------
    @app.get("/api/graph")
    async def get_graph(section: str | None = None) -> dict:
        from research_companion import store
        from research_companion.graph import load_graph, section_subgraph, serialize_graph

        section_id = section
        G = load_graph()

        if section_id is not None:
            draft_id = store.get_draft_paper_id()
            if draft_id is None:
                raise HTTPException(status_code=400,
                                    detail="?section filter requires a configured draft paper")
            G = section_subgraph(G, draft_id, section_id)

        return serialize_graph(G, seq=recorder.current_max_seq())

    # -----------------------------------------------------------------
    # POST /api/ingest
    # -----------------------------------------------------------------
    @app.post("/api/ingest", status_code=202, dependencies=[Depends(require_active_workspace)])
    async def ingest(body: _IngestBody) -> dict:
        from research_companion.lab import scan_pdfs

        folder = body.folder.strip() if body.folder else ""
        if not folder:
            raise HTTPException(status_code=400, detail="folder is required")

        # Validate folder
        try:
            pdfs = await asyncio.to_thread(scan_pdfs, folder)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        # One ingest at a time — narrow to INGEST jobs only (add/retry are not blocked)
        running_ingest_jobs = [
            jid for jid, info in app.state.jobs.items()
            if info.get("status") == "running" and info.get("kind") == "ingest"
        ]
        if running_ingest_jobs:
            raise HTTPException(status_code=409, detail="An ingest job is already running")

        # Optional caller-selected subset of the scanned folder. Security: only
        # paths that scan_pdfs(folder) actually returned are ingestable — this
        # mirrors the existing folder-trust boundary, so arbitrary client
        # paths outside the folder are silently dropped.
        ingest_paths = None
        if body.paths is not None:
            allowed = {str(p) for p in pdfs}
            selected = [p for p in body.paths if p in allowed]
            if not selected:
                raise HTTPException(status_code=400, detail="no valid files selected")
            ingest_paths = selected
        count = len(ingest_paths) if ingest_paths is not None else len(pdfs)

        app.state.job_counter += 1
        job_id = f"job-{app.state.job_counter}"
        ingest_label = f"Ingesting folder ({count} PDFs)…"
        app.state.jobs[job_id] = {"status": "running", "detail": None, "kind": "ingest",
                                  "label": ingest_label, "target": ""}

        ingest_fn = app.state.ingest_override
        if ingest_fn is None:
            from research_companion.lab import ingest_folder as _real_ingest
            ingest_fn = _real_ingest

        async def _run_ingest():
            await _announce_start(job_id, "ingest", ingest_label)
            try:
                await ingest_fn(folder, bus=bus, paths=ingest_paths)
                app.state.jobs[job_id] = {"status": "done", "detail": None, "kind": "ingest",
                                          "label": ingest_label, "target": ""}
                _schedule_coverage_refresh()
            except Exception as exc:
                app.state.jobs[job_id] = {"status": "failed", "detail": str(exc), "kind": "ingest"}
            finally:
                await _announce_finish(job_id, "ingest")

        asyncio.create_task(_run_ingest())

        return {
            "job_id": job_id,
            "discovered": count,
            "files": [Path(p).name for p in ingest_paths] if ingest_paths is not None else [p.name for p in pdfs],
        }

    # -----------------------------------------------------------------
    # POST /api/ingest/scan — folder preview (no job started, no ingest)
    # -----------------------------------------------------------------
    @app.post("/api/ingest/scan", dependencies=[Depends(require_active_workspace)])
    async def ingest_scan(body: _IngestBody) -> dict:
        from research_companion import store
        from research_companion.lab import scan_pdfs

        folder_str = body.folder.strip() if body.folder else ""
        if not folder_str:
            raise HTTPException(status_code=400, detail="folder is required")
        folder = Path(folder_str)
        try:
            pdfs = await asyncio.to_thread(scan_pdfs, folder)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        def _scan() -> list[dict]:
            out = []
            for p in pdfs:
                already = False
                try:
                    # Cross-namespace dedup: also flags a file already held as an
                    # arXiv/DOI paper, not just a byte-identical local copy.
                    already = store.find_existing_paper_for(
                        p.read_bytes(), filename=p.name) is not None
                except Exception:
                    already = False
                try:
                    rel = str(p.relative_to(folder))
                except ValueError:
                    rel = p.name
                out.append({"name": p.name, "path": str(p), "rel_path": rel,
                            "already_in_library": already})
            return out

        files = await asyncio.to_thread(_scan)
        return {"discovered": len(files), "already": sum(1 for f in files if f["already_in_library"]),
                "files": files}

    # -----------------------------------------------------------------
    # GET /api/jobs — active (running) jobs, for boot hydration of the
    # activity indicator (registered before the /{job_id} route)
    # -----------------------------------------------------------------
    @app.get("/api/jobs")
    async def list_jobs() -> dict:
        return {"jobs": [
            {"job_id": jid, "kind": info.get("kind", ""),
             "label": info.get("label", ""), "target": info.get("target", ""),
             "status": info.get("status", "")}
            for jid, info in app.state.jobs.items()
            if info.get("status") == "running"
        ]}

    # -----------------------------------------------------------------
    # GET /api/jobs/{id}
    # -----------------------------------------------------------------
    @app.get("/api/jobs/{job_id}")
    async def get_job(job_id: str) -> dict:
        info = app.state.jobs.get(job_id)
        if info is None:
            raise HTTPException(status_code=404, detail=f"Job not found: {job_id!r}")
        return info

    # -----------------------------------------------------------------
    # GET /api/failures
    # -----------------------------------------------------------------
    @app.get("/api/failures")
    async def get_failures() -> dict:
        from research_companion import store
        return store.list_failures()

    # -----------------------------------------------------------------
    # POST /api/align
    # -----------------------------------------------------------------
    @app.post("/api/align", dependencies=[Depends(require_active_workspace)])
    async def align(body: _AlignBody) -> dict:
        from research_companion import store
        from research_companion.alignment import AlignmentError, align_papers

        paper_id = body.paper_id.strip() if body.paper_id else ""
        against = body.against
        force = body.force

        if not paper_id:
            raise HTTPException(status_code=400, detail="paper_id required")

        meta = store.PaperMetadata.load(paper_id)
        if meta is None:
            raise HTTPException(status_code=404, detail=f"Paper not found: {paper_id!r}")

        draft_id = against or store.get_draft_paper_id()
        if not draft_id:
            raise HTTPException(
                status_code=400,
                detail="No draft configured. Provide against or run set-draft first."
            )

        resolved_llm = app.state.llm
        if resolved_llm is None:
            resolved_llm = _resolve_llm()

        try:
            payload = await asyncio.to_thread(
                align_papers,
                draft_id,
                paper_id,
                llm=resolved_llm,
                force=force,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except AlignmentError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        try:
            from research_companion.agents.events import SuggestionsUpdated
            from research_companion.suggestions import generate_suggestions

            report = store.load_review_report(draft_id)
            if report is not None:
                papers = store.list_papers()
                alignments = []
                for meta in papers:
                    if meta.paper_id == draft_id:
                        continue
                    al = store.load_alignment(meta.paper_id, draft_paper_id=draft_id)
                    if al is not None:
                        alignments.append(al)

                updated_payload = await asyncio.to_thread(
                    generate_suggestions,
                    draft_id=draft_id,
                    report=report,
                    alignments=alignments,
                )
                sugs = updated_payload.get("suggestions", [])
                await bus.publish(SuggestionsUpdated(
                    draft_paper_id=draft_id,
                    open=sum(1 for s in sugs if s.get("status") == "open"),
                    addressed=sum(1 for s in sugs if s.get("status") == "addressed"),
                    dismissed=sum(1 for s in sugs if s.get("status") == "dismissed"),
                ))
        except Exception:
            pass

        # Journey: log alignment_run event (non-fatal)
        try:
            from research_companion.journey import log_event as _log_journey_event
            _verdict = payload.get("verdict", "")
            await asyncio.to_thread(
                _log_journey_event,
                "alignment_run",
                {"paper_id": paper_id, "verdict": _verdict},
            )
        except Exception:  # noqa: BLE001
            pass

        return payload

    # -----------------------------------------------------------------
    # POST /api/ask
    # -----------------------------------------------------------------
    @app.post("/api/ask", dependencies=[Depends(require_active_workspace)])
    async def ask(body: _AskBody) -> dict:
        from research_companion.qa import answer

        question = body.question.strip() if body.question else ""
        section_id = body.section_id

        if not question:
            raise HTTPException(status_code=400, detail="question required")

        resolved_llm = app.state.llm
        if resolved_llm is None:
            # Prose answer -> json_mode=False. Uses the settings-aware provider
            # (OpenAI/Anthropic per Settings) instead of qa.answer's env-only
            # fallback, which defaults to anthropic and 500s when only OpenAI
            # is configured.
            resolved_llm = _resolve_llm(json_mode=False)

        result = await asyncio.to_thread(
            answer,
            question,
            llm=resolved_llm,
            section_id=section_id,
        )

        # Build citations list with n = source tag number
        cited_ids = {(s.paper_id, s.section_id) for s in result.cited}
        citations = [
            {
                "n": i + 1,
                "paper_id": s.paper_id,
                "title": s.paper_title,
                "section_id": s.section_id,
                "section_title": s.section_title,
                "cited": (s.paper_id, s.section_id) in cited_ids,
                # Absolute source offsets so the citation chip can open the
                # reader at the exact evidence span (Phase 3 Task B).
                "char_start": s.char_start,
                "char_end": s.char_end,
                "chunk_index": s.chunk_index,
            }
            for i, s in enumerate(result.sources)
        ]

        grounding_paper_ids = list({s.paper_id for s in result.cited})

        return {
            "answer": result.answer,
            "citations": citations,
            "unverified_quotes": result.unverified_quotes,
            "grounding": {
                "paper_ids": grounding_paper_ids,
                "node_ids": result.grounding_node_ids,
            },
        }

    # -----------------------------------------------------------------
    # POST /api/compare
    # -----------------------------------------------------------------
    @app.post("/api/compare")
    async def compare(body: _CompareBody) -> dict:
        from research_companion import store
        from research_companion.compare import compare_papers

        paper_a = body.paper_a.strip() if body.paper_a else ""
        paper_b = body.paper_b.strip() if body.paper_b else ""

        if not paper_a or not paper_b:
            raise HTTPException(status_code=400, detail="paper_a and paper_b required")

        if paper_a == paper_b:
            raise HTTPException(status_code=400, detail="Cannot compare a paper to itself")

        # Check existence
        for pid in (paper_a, paper_b):
            if store.PaperMetadata.load(pid) is None:
                raise HTTPException(status_code=404, detail=f"Paper not found: {pid!r}")

        resolved_llm = app.state.llm
        if resolved_llm is None:
            # Narrative summary is prose — never force JSON mode.
            resolved_llm = _resolve_llm(json_mode=False)

        try:
            result = await asyncio.to_thread(
                compare_papers, paper_a, paper_b, llm=resolved_llm
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return result

    # -----------------------------------------------------------------
    # GET /api/settings
    # -----------------------------------------------------------------
    @app.get("/api/settings")
    async def get_settings_endpoint() -> dict:
        from research_companion.settings import get_settings
        return get_settings()

    # -----------------------------------------------------------------
    # PUT /api/settings
    # -----------------------------------------------------------------
    @app.put("/api/settings")
    async def put_settings_endpoint(body: _SettingsPatchBody) -> dict:
        from research_companion.settings import SettingsError, update_settings

        # Build a patch dict from only the explicitly provided (non-None) fields.
        # Note: model=None is a valid value (means "remove model override"), so we
        # use model_fields_set (pydantic v2) or __fields_set__ (pydantic v1) to
        # distinguish "not provided" from "set to None".
        try:
            # Pydantic v2
            provided = body.model_fields_set
        except AttributeError:
            # Pydantic v1
            provided = body.__fields_set__  # type: ignore[attr-defined]

        patch: dict = {}
        for field in provided:
            patch[field] = getattr(body, field)

        if not patch:
            # Nothing to update — return current settings
            from research_companion.settings import get_settings
            return get_settings()

        try:
            return update_settings(patch)
        except SettingsError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    # -----------------------------------------------------------------
    # GET /api/suggestions[?status=]
    # -----------------------------------------------------------------
    @app.get("/api/suggestions")
    async def get_suggestions(status: str | None = None) -> dict:
        from research_companion import store
        from research_companion.suggestions import load_suggestions

        _empty_counts = {"open": 0, "addressed": 0, "dismissed": 0}

        draft_id = store.get_draft_paper_id()
        if draft_id is None:
            return {"draft_paper_id": None, "suggestions": [], "counts": _empty_counts}

        payload = await asyncio.to_thread(load_suggestions, draft_id)
        if payload is None:
            return {"draft_paper_id": draft_id, "suggestions": [], "counts": _empty_counts}

        sugs_all = payload.get("suggestions", [])
        counts = {
            "open": sum(1 for s in sugs_all if s.get("status") == "open"),
            "addressed": sum(1 for s in sugs_all if s.get("status") == "addressed"),
            "dismissed": sum(1 for s in sugs_all if s.get("status") == "dismissed"),
        }

        sugs = [s for s in sugs_all if s.get("status") == status] if status is not None else sugs_all

        return {"draft_paper_id": draft_id, "suggestions": sugs, "counts": counts}

    # -----------------------------------------------------------------
    # POST /api/suggestions/regenerate
    # -----------------------------------------------------------------
    @app.post("/api/suggestions/regenerate", dependencies=[Depends(require_active_workspace)])
    async def regenerate_suggestions(body: _RegenerateBody) -> dict:
        from research_companion import store
        from research_companion.agents.events import SuggestionsUpdated
        from research_companion.suggestions import generate_suggestions

        draft_id = store.get_draft_paper_id()
        if not draft_id:
            raise HTTPException(status_code=400, detail="No draft configured.")

        # A missing review report is fine: alignment- and gap-derived suggestions
        # are still valid (generate_suggestions tolerates report=None).
        report = store.load_review_report(draft_id)

        papers = store.list_papers()
        alignments = []
        for meta in papers:
            if meta.paper_id == draft_id:
                continue
            al = store.load_alignment(meta.paper_id, draft_paper_id=draft_id)
            if al is not None:
                alignments.append(al)

        if body.include_llm:
            resolved_llm = app.state.llm
            if resolved_llm is None:
                try:
                    resolved_llm = _resolve_llm(json_mode=True)
                except Exception:
                    resolved_llm = None
        else:
            resolved_llm = None

        payload = await asyncio.to_thread(
            generate_suggestions,
            draft_id=draft_id,
            report=report,
            alignments=alignments,
            llm=resolved_llm,
            include_llm=body.include_llm,
        )

        sugs = payload.get("suggestions", [])
        counts = {
            "open": sum(1 for s in sugs if s.get("status") == "open"),
            "addressed": sum(1 for s in sugs if s.get("status") == "addressed"),
            "dismissed": sum(1 for s in sugs if s.get("status") == "dismissed"),
        }
        await bus.publish(SuggestionsUpdated(
            draft_paper_id=draft_id,
            open=counts["open"],
            addressed=counts["addressed"],
            dismissed=counts["dismissed"],
        ))

        # Same contract as GET /api/suggestions: payload + counts.
        return {**payload, "counts": counts}

    # -----------------------------------------------------------------
    # POST /api/suggestions/{sug_id}/dismiss
    # -----------------------------------------------------------------
    @app.post("/api/suggestions/{sug_id}/dismiss", dependencies=[Depends(require_active_workspace)])
    async def dismiss_suggestion_endpoint(sug_id: str) -> dict:
        from research_companion import store
        from research_companion.agents.events import SuggestionsUpdated
        from research_companion.suggestions import dismiss_suggestion, load_suggestions

        try:
            updated = await asyncio.to_thread(dismiss_suggestion, sug_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Suggestion not found: {sug_id!r}") from exc

        draft_id = store.get_draft_paper_id()
        if draft_id is not None:
            payload = await asyncio.to_thread(load_suggestions, draft_id)
            if payload is not None:
                sugs = payload.get("suggestions", [])
                await bus.publish(SuggestionsUpdated(
                    draft_paper_id=draft_id,
                    open=sum(1 for s in sugs if s.get("status") == "open"),
                    addressed=sum(1 for s in sugs if s.get("status") == "addressed"),
                    dismissed=sum(1 for s in sugs if s.get("status") == "dismissed"),
                ))

        # Journey: log suggestion_dismissed event (non-fatal)
        try:
            from research_companion.journey import log_event as _log_journey_event
            await asyncio.to_thread(
                _log_journey_event,
                "suggestion_dismissed",
                {
                    "suggestion_id": sug_id,
                    "suggestion_title": updated.get("title", ""),
                },
            )
        except Exception:  # noqa: BLE001
            pass

        return updated

    # -----------------------------------------------------------------
    # Workspaces — one isolated research per workspace (W4-B4)
    # -----------------------------------------------------------------
    def _ws_http(exc: Exception):
        status = getattr(exc, "status", 400)
        return HTTPException(status_code=status, detail=str(exc))

    @app.get("/api/workspaces")
    async def get_workspaces() -> dict:
        from research_companion import workspaces
        return await asyncio.to_thread(workspaces.list_workspaces)

    @app.post("/api/workspaces", status_code=201)
    async def create_workspace_ep(body: _WorkspaceCreateBody) -> dict:
        from research_companion import workspaces
        try:
            return await asyncio.to_thread(workspaces.create_workspace, body.name)
        except workspaces.WorkspaceError as exc:
            raise _ws_http(exc) from exc

    @app.patch("/api/workspaces/{ws_id}")
    async def patch_workspace_ep(ws_id: str, body: _WorkspacePatchBody) -> dict:
        from research_companion import workspaces
        try:
            return await asyncio.to_thread(
                workspaces.update_workspace, ws_id,
                name=body.name, archived=body.archived)
        except workspaces.WorkspaceError as exc:
            raise _ws_http(exc) from exc

    @app.post("/api/workspaces/{ws_id}/activate")
    async def activate_workspace_ep(ws_id: str) -> dict:
        from research_companion import store, workspaces
        from research_companion.agents.events import EventLog, WorkspaceChanged

        # Running pipelines write to the OLD workspace's paths — refuse to
        # switch under them.
        if any(j.get("status") == "running" for j in app.state.jobs.values()):
            raise HTTPException(
                status_code=409,
                detail="A job is still running — wait for it to finish "
                       "before switching research.")

        try:
            result = await asyncio.to_thread(workspaces.activate_workspace, ws_id)
        except workspaces.WorkspaceError as exc:
            raise _ws_http(exc) from exc

        # Repoint the persistent event log (skip for test buses without one)
        if bus._log is not None:
            bus.set_log(EventLog(store.papergraph_dir() / "lab_events.jsonl"))
        # The SSE stream must not replay the previous workspace's events
        bus.history.clear()
        app.state.recorder.reset()
        await bus.publish(WorkspaceChanged(workspace_id=ws_id))

        # Switching to a stale workspace backfills its weak-metadata papers
        # once (non-fatal — must never break activation).
        with suppress(Exception):
            asyncio.create_task(app.state._trigger_backfill())

        return {**result, "reload": True}

    @app.delete("/api/workspaces/{ws_id}")
    async def delete_workspace_ep(ws_id: str) -> dict:
        from research_companion import store, workspaces
        from research_companion.agents.events import EventLog, WorkspaceChanged

        # Running pipelines write to the OLD workspace's paths — refuse to
        # switch under them.
        if any(j.get("status") == "running" for j in app.state.jobs.values()):
            raise HTTPException(
                status_code=409,
                detail="A job is still running — wait for it to finish "
                       "before switching research.")

        try:
            result = await asyncio.to_thread(workspaces.delete_workspace, ws_id)
        except workspaces.WorkspaceError as exc:
            raise _ws_http(exc) from exc

        if result["switched"]:
            # Repoint the persistent event log (skip for test buses without one).
            # None active (last workspace just deleted) detaches the log entirely.
            if bus._log is not None:
                new_dir = store.papergraph_dir()
                bus.set_log(EventLog(new_dir / "lab_events.jsonl") if new_dir is not None else None)
            # The SSE stream must not replay the previous workspace's events
            bus.history.clear()
            app.state.recorder.reset()
            await bus.publish(WorkspaceChanged(workspace_id=result["active"]))

        return result

    # -----------------------------------------------------------------
    # GET /api/views
    # -----------------------------------------------------------------
    @app.get("/api/views")
    async def list_views_endpoint() -> dict:
        from research_companion.views import list_views

        return {"views": await asyncio.to_thread(list_views)}

    # -----------------------------------------------------------------
    # POST /api/views
    # -----------------------------------------------------------------
    @app.post("/api/views", status_code=201, dependencies=[Depends(require_active_workspace)])
    async def create_view_endpoint(body: _CreateViewBody) -> dict:
        from research_companion.views import ViewError, save_view

        try:
            return await asyncio.to_thread(
                save_view,
                body.name,
                source=body.source,
                node_ids=body.node_ids,
                pinned=body.pinned,
            )
        except ViewError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    # -----------------------------------------------------------------
    # PATCH /api/views/{view_id}
    # -----------------------------------------------------------------
    @app.patch("/api/views/{view_id}", dependencies=[Depends(require_active_workspace)])
    async def update_view_endpoint(view_id: str, body: _PatchViewBody) -> dict:
        from research_companion.views import ViewError, get_view, update_view

        # Distinguish 404 (unknown) from 400 (validation) by checking existence first.
        existing = await asyncio.to_thread(get_view, view_id)
        if existing is None:
            raise HTTPException(status_code=404, detail=f"No view found with id {view_id!r}")

        try:
            # Extract only the explicitly provided fields (pydantic v2 / v1 compat)
            try:
                provided = body.model_fields_set
            except AttributeError:
                provided = body.__fields_set__  # type: ignore[attr-defined]

            kwargs: dict = {}
            if "name" in provided:
                kwargs["name"] = body.name
            if "pinned" in provided:
                kwargs["pinned"] = body.pinned

            return await asyncio.to_thread(update_view, view_id, **kwargs)
        except ViewError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    # -----------------------------------------------------------------
    # DELETE /api/views/{view_id}
    # -----------------------------------------------------------------
    @app.delete("/api/views/{view_id}", dependencies=[Depends(require_active_workspace)])
    async def delete_view_endpoint(view_id: str) -> dict:
        from research_companion.views import delete_view, get_view

        existing = await asyncio.to_thread(get_view, view_id)
        if existing is None:
            raise HTTPException(status_code=404, detail=f"No view found with id {view_id!r}")

        removed = await asyncio.to_thread(delete_view, view_id)
        return {"removed": removed}

    # -----------------------------------------------------------------
    # GET /api/views/{view_id}/graph
    # -----------------------------------------------------------------
    @app.get("/api/views/{view_id}/graph")
    async def get_view_graph_endpoint(view_id: str) -> dict:
        from research_companion.views import ViewError, view_graph

        try:
            return await asyncio.to_thread(view_graph, view_id)
        except ViewError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    def _cached_gap_themes() -> list[dict]:
        """Return the cached gap-theme synthesis' themes list, or [] when there is
        no cache or it is stale against the current gap/resolution/papers/
        synthesis-prompt shas. Additive: GET /api/gaps must never fail over this
        — an empty/stale cache degrades to a clean [] rather than raising."""
        from research_companion import store
        from research_companion.gaps import _papers_sha
        from research_companion.prompts import (
            gap_prompt_sha256,
            gap_resolution_prompt_sha256,
            gap_synthesis_prompt_sha256,
        )

        cached = store.load_gap_synthesis()
        if cached is None:
            return []
        all_papers = store.list_papers()
        p_sha = _papers_sha([m.paper_id for m in all_papers])
        fresh = (
            cached.get("gap_prompt_sha256") == gap_prompt_sha256()
            and cached.get("resolution_prompt_sha256") == gap_resolution_prompt_sha256()
            and cached.get("papers_sha256") == p_sha
            and cached.get("synthesis_prompt_sha256") == gap_synthesis_prompt_sha256()
        )
        return cached.get("themes", []) if fresh else []

    # -----------------------------------------------------------------
    # GET /api/gaps
    # -----------------------------------------------------------------
    @app.get("/api/gaps")
    async def get_gaps() -> dict:
        from research_companion.gaps import gaps_overview

        overview = await asyncio.to_thread(gaps_overview)
        overview["themes"] = await asyncio.to_thread(_cached_gap_themes)
        return overview

    # -----------------------------------------------------------------
    # POST /api/gaps/refresh  -> 202 {"job_id"}
    # -----------------------------------------------------------------
    @app.post("/api/gaps/refresh", status_code=202, dependencies=[Depends(require_active_workspace)])
    async def refresh_gaps() -> dict:
        from research_companion.agents.events import GapsUpdated

        app.state.job_counter += 1
        job_id = f"job-{app.state.job_counter}"
        gaps_label = "Analyzing gaps…"
        app.state.jobs[job_id] = {"status": "running", "detail": None, "kind": "gaps",
                                  "label": gaps_label, "target": ""}

        async def _run_gaps():
            await _announce_start(job_id, "gaps", gaps_label)
            try:
                from datetime import datetime, timezone

                from research_companion import store
                from research_companion.gaps import (
                    _papers_sha,
                    extract_all_gaps,
                    gaps_overview,
                    resolve_gaps,
                    synthesize_gaps,
                )
                from research_companion.prompts import (
                    gap_prompt_sha256,
                    gap_resolution_prompt_sha256,
                    gap_synthesis_prompt_sha256,
                )

                resolved_llm = app.state.llm
                if resolved_llm is None:
                    resolved_llm = _resolve_llm(json_mode=True)

                await asyncio.to_thread(extract_all_gaps, llm=resolved_llm)
                await asyncio.to_thread(resolve_gaps, llm=resolved_llm)

                overview = await asyncio.to_thread(gaps_overview)
                n_gaps = sum(
                    len(p.get("gaps", [])) for p in overview.get("papers", [])
                )
                n_open = sum(
                    1
                    for p in overview.get("papers", [])
                    for g in p.get("gaps", [])
                    if g.get("resolution", {}).get("status") == "open"
                )

                synthesis = await asyncio.to_thread(synthesize_gaps, overview, llm=resolved_llm)
                all_papers = await asyncio.to_thread(store.list_papers)
                p_sha = _papers_sha([m.paper_id for m in all_papers])
                await asyncio.to_thread(store.save_gap_synthesis, {
                    "gap_prompt_sha256": gap_prompt_sha256(),
                    "resolution_prompt_sha256": gap_resolution_prompt_sha256(),
                    "papers_sha256": p_sha,
                    "synthesis_prompt_sha256": gap_synthesis_prompt_sha256(),
                    "computed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                    "themes": synthesis.get("themes", []),
                })
                n_themes = len(synthesis.get("themes", []))

                await bus.publish(GapsUpdated(n_gaps=n_gaps, n_open=n_open, n_themes=n_themes))
                app.state.jobs[job_id] = {"status": "done", "detail": None, "kind": "gaps",
                                          "label": gaps_label, "target": ""}
            except Exception as exc:  # noqa: BLE001
                app.state.jobs[job_id] = {
                    "status": "failed",
                    "detail": str(exc),
                    "kind": "gaps",
                    "label": gaps_label, "target": "",
                }
            finally:
                await _announce_finish(job_id, "gaps")

        asyncio.create_task(_run_gaps())
        return {"job_id": job_id}

    # -----------------------------------------------------------------
    # GET /api/temporal
    # -----------------------------------------------------------------
    @app.get("/api/temporal")
    async def get_temporal() -> dict:
        from research_companion.temporal import build_timeline

        return await asyncio.to_thread(build_timeline)

    # -----------------------------------------------------------------
    # GET /api/journey
    # -----------------------------------------------------------------
    @app.get("/api/journey")
    async def get_journey() -> dict:
        from research_companion.journey import journey_summary

        return await asyncio.to_thread(journey_summary)

    # -----------------------------------------------------------------
    # GET /api/search?q=...&k=6
    # -----------------------------------------------------------------
    @app.get("/api/search")
    async def get_search(q: str | None = None, k: int = 6) -> dict:
        from research_companion.qa import build_section_index
        from research_companion.rank import tokenize
        from research_companion.retrieve import rank_units

        if not q or not q.strip():
            raise HTTPException(status_code=400, detail="q is required and must not be empty")

        q = q.strip()
        units = await asyncio.to_thread(build_section_index)
        q_tokens = tokenize(q)
        ranked = await asyncio.to_thread(rank_units, q, q_tokens, units, k=k)

        mode = ranked[0]["mode"] if ranked else "bm25"
        results = [
            {
                "paper_id": r["unit"]["paper_id"],
                "paper_title": r["unit"]["paper_title"],
                "section_id": r["unit"]["section_id"],
                "section_title": r["unit"]["section_title"],
                "score": r["score"],
                "bm25": r["bm25"],
                "cosine": r["cosine"],
                "snippet": r["unit"]["text"][:200],
            }
            for r in ranked
        ]

        return {"query": q, "mode": mode, "results": results}

    # -----------------------------------------------------------------
    # POST /api/converse
    # -----------------------------------------------------------------
    @app.post("/api/converse", dependencies=[Depends(require_active_workspace)])
    async def converse_endpoint(body: _ConverseBody) -> dict:
        from research_companion.converse import ConverseError, converse

        message = body.message.strip() if body.message else ""
        context = body.context or {}
        conversation_id = body.conversation_id

        if not message:
            raise HTTPException(status_code=400, detail="message required")

        ctx_type = context.get("type", "")
        if not ctx_type:
            raise HTTPException(status_code=400, detail="context.type is required")

        resolved_llm = app.state.llm
        if resolved_llm is None:
            resolved_llm = _resolve_llm(json_mode=False)

        try:
            result = await asyncio.to_thread(
                converse,
                message,
                context=context,
                conversation_id=conversation_id,
                llm=resolved_llm,
            )
        except ConverseError as exc:
            raise HTTPException(status_code=exc.status, detail=str(exc)) from exc

        return {
            "answer": result.answer,
            "citations": result.citations,
            "unverified_quotes": result.unverified_quotes,
            "conversation_id": result.conversation_id,
        }

    # -----------------------------------------------------------------
    # GET /api/conversations/{id}
    # -----------------------------------------------------------------
    @app.get("/api/conversations/{conversation_id}")
    async def get_conversation(conversation_id: str) -> dict:
        from research_companion.converse import load_conversation

        data = await asyncio.to_thread(load_conversation, conversation_id)
        if data is None:
            raise HTTPException(
                status_code=404,
                detail=f"Conversation not found: {conversation_id!r}",
            )
        return data

    # -----------------------------------------------------------------
    # DELETE /api/conversations/{id}
    # -----------------------------------------------------------------
    @app.delete("/api/conversations/{conversation_id}", dependencies=[Depends(require_active_workspace)])
    async def delete_conversation_endpoint(conversation_id: str) -> dict:
        from research_companion.converse import delete_conversation

        removed = await asyncio.to_thread(delete_conversation, conversation_id)
        if not removed:
            raise HTTPException(
                status_code=404,
                detail=f"Conversation not found: {conversation_id!r}",
            )
        return {"removed": True}

    # -----------------------------------------------------------------
    # GET /api/events (SSE)
    # -----------------------------------------------------------------
    @app.get("/api/events")
    async def events_stream():
        from fastapi.responses import StreamingResponse

        # Capture done flag at connection time (for test mode)
        _done_flag = app.state._sse_done

        async def gen():
            # Subscribe FIRST so we don't miss events published after this point
            q = bus.subscribe()
            # Snapshot the already-recorded (seq, event) pairs for replay
            snapshot = recorder.snapshot()
            seen_event_ids = {id(e) for _, e in snapshot}
            # Cursor: the number of records we have already yielded (starts after replay)
            cursor = len(snapshot)
            try:
                # Replay pre-connect events with their original seq.
                # WorkspaceChanged is a transient live signal ("reload now"),
                # not state: replaying it to a fresh connection makes every
                # page load reload itself — an infinite flicker loop.
                for seq, event in snapshot:
                    if type(event).__name__ == "WorkspaceChanged":
                        continue
                    data = event_to_dict(event) | {"seq": seq}
                    yield f"data: {json.dumps(data)}\n\n"

                # If done flag is set (test mode), terminate after replaying history
                if _done_flag:
                    return

                # Live stream: serve (seq, event) pairs from the recorder's stream.
                # The recorder's drain() task is the sole seq authority; we wait on
                # its Condition to avoid busy-polling and to guarantee seq consistency
                # across concurrent connections.
                condition = recorder._get_condition()
                last_ping = asyncio.get_event_loop().time()
                while True:
                    # Wait for the recorder to notify us of new events (with timeout
                    # for heartbeat).
                    try:
                        async with condition:
                            await asyncio.wait_for(
                                condition.wait(),
                                timeout=1.0,
                            )
                    except asyncio.TimeoutError:
                        # Emit heartbeat if idle
                        now = asyncio.get_event_loop().time()
                        if now - last_ping >= 15.0:
                            yield ": ping\n\n"
                            last_ping = now
                        continue

                    # Drain any new records the recorder has added since our cursor
                    current_records = recorder.snapshot()
                    while cursor < len(current_records):
                        seq, event = current_records[cursor]
                        cursor += 1
                        if id(event) in seen_event_ids:
                            continue
                        seen_event_ids.add(id(event))
                        data = event_to_dict(event) | {"seq": seq}
                        yield f"data: {json.dumps(data)}\n\n"
                        last_ping = asyncio.get_event_loop().time()
            except asyncio.CancelledError:
                pass
            finally:
                bus.unsubscribe(q)

        return StreamingResponse(gen(), media_type="text/event-stream")

    return app


# ---------------------------------------------------------------------------
# Background task helpers
# ---------------------------------------------------------------------------

async def _run_paper_pipeline(meta, path_str: str, bus: Bus, *,
                              pipeline_overrides: dict | None = None) -> None:
    """Publish PaperAdded and run the full single-paper pipeline for a stored paper."""

    from research_companion.agents.events import JobDone, PaperAdded
    from research_companion.lab import _default_aligner, _default_strengther, ingest_one

    if pipeline_overrides is None:
        pipeline_overrides = {}

    await bus.publish(PaperAdded(
        paper_id=meta.paper_id,
        title=meta.title,
        source=meta.source_url,
    ))

    # Resolve pipeline seams — test overrides take priority
    extractor = pipeline_overrides.get("extractor")
    if extractor is None:
        from research_companion.extract import extract_paper
        extractor = extract_paper

    sectioner = pipeline_overrides.get("sectioner")
    if sectioner is None:
        from research_companion.sections import build_and_save_sections
        sectioner = build_and_save_sections

    aligner = pipeline_overrides.get("aligner", _default_aligner())
    strengther = pipeline_overrides.get("strengther", _default_strengther())

    provider, model = _pipeline_provider_model()

    await ingest_one(
        meta,
        path_str,
        bus=bus,
        provider=provider,
        model=model,
        align=True,
        aligner=aligner,
        strengther=strengther,
        extractor=extractor,
        sectioner=sectioner,
    )

    await bus.publish(JobDone(job="add"))


async def _add_paper_task(target: str, bus: Bus, *, pipeline_overrides: dict | None = None) -> None:
    """Add a paper to the store and run the full single-paper pipeline."""
    from research_companion.fetch import add_paper

    meta = await asyncio.to_thread(add_paper, target)
    # use the target URL/path as the failure key
    await _run_paper_pipeline(meta, target, bus, pipeline_overrides=pipeline_overrides)


async def _upload_paper_task(meta, bus: Bus, *, pipeline_overrides: dict | None = None) -> None:
    """Pipeline for a paper already stored by the upload endpoint."""
    path_str = meta.source_url or meta.paper_id  # upload://<filename> failure key
    await _run_paper_pipeline(meta, path_str, bus, pipeline_overrides=pipeline_overrides)


class _RetryFatalStageFailure(RuntimeError):
    """Raised by _retry_paper_task when ingest_one returns False (a fatal-stage
    failure: extract/sections/graph).

    ingest_one already called store.record_failure(...) and published its own
    IngestFailed for that stage before returning False, so this exception
    carries the already-recorded reason purely to propagate failure up to the
    /retry job wrapper (_run()) — it must NOT be treated as a new failure to
    record or announce again (no second record_failure, no second
    IngestFailed publish).
    """


async def _retry_paper_task(
    path: str,
    paper_id: str,
    bus: Bus,
    *,
    pipeline_overrides: dict | None = None,
) -> None:
    """Re-run the add + full pipeline for a failed paper.

    Raises on add failure so the caller's _run() records "failed" status and
    the failure entry is kept (not cleared). Also raises (as
    _RetryFatalStageFailure) when ingest_one signals a fatal-stage failure via
    its False return, so a fatal-stage retry failure doesn't get treated as
    success by _run() (which would otherwise clear_failure and erase the
    failure record ingest_one just wrote).
    """

    from research_companion import store
    from research_companion.agents.events import IngestFailed, JobDone, PaperAdded
    from research_companion.lab import _default_aligner, _default_strengther, ingest_one

    if pipeline_overrides is None:
        pipeline_overrides = {}

    # Re-attempt add_paper for the path — let errors propagate so the job is
    # recorded as "failed" and the failure entry is preserved.
    from research_companion.fetch import add_local_pdf
    try:
        meta = await asyncio.to_thread(add_local_pdf, path)
    except Exception as exc:
        # add_local_pdf failing again (e.g. "PDF not found: ...") raises before
        # ingest_one ever runs, so none of ingest_one's own IngestFailed
        # publishes fire. Without this, the SSE stream is silent on this path
        # and the Library row (which may show a transient "Retrying..." button
        # state) never re-renders — the failure is real but invisible. Publish
        # here so the frontend's 'papers' topic refreshes and the row reflects
        # the failed status again.
        #
        # Also persist the NEW error via record_failure: without this,
        # GET /api/papers (which reads store.list_failures()) would keep
        # showing whatever reason was recorded on the *previous* failed
        # attempt after a page reload, even though the live SSE event above
        # carries the current one.
        error_str = str(exc)
        store.record_failure(path, {"stage": "add", "error": error_str, "paper_id": paper_id})
        await bus.publish(IngestFailed(
            path=path, stage="add", error=error_str, paper_id=paper_id,
        ))
        raise

    await bus.publish(PaperAdded(
        paper_id=meta.paper_id,
        title=meta.title,
        source="",
    ))

    # Resolve pipeline seams
    extractor = pipeline_overrides.get("extractor")
    if extractor is None:
        from research_companion.extract import extract_paper
        extractor = extract_paper

    sectioner = pipeline_overrides.get("sectioner")
    if sectioner is None:
        from research_companion.sections import build_and_save_sections
        sectioner = build_and_save_sections

    aligner = pipeline_overrides.get("aligner", _default_aligner())
    strengther = pipeline_overrides.get("strengther", _default_strengther())

    provider, model = _pipeline_provider_model()

    ok = await ingest_one(
        meta,
        path,
        bus=bus,
        provider=provider,
        model=model,
        align=True,
        aligner=aligner,
        strengther=strengther,
        extractor=extractor,
        sectioner=sectioner,
    )

    if not ok:
        # Fatal stage (extract/sections/graph) failed. ingest_one already
        # recorded the failure and published its own IngestFailed for that
        # stage -- re-read the persisted reason (rather than fabricating a
        # new one) so the job's "detail" reflects the real cause, falling
        # back to a generic message if the record is somehow missing.
        failures = store.list_failures()
        info = failures.get(path)
        if info is None:
            info = next(
                (v for v in failures.values()
                 if isinstance(v, dict) and v.get("paper_id") == meta.paper_id),
                None,
            )
        reason = info.get("error") if isinstance(info, dict) else None
        raise _RetryFatalStageFailure(reason or "ingest failed")

    await bus.publish(JobDone(job="retry"))


# ---------------------------------------------------------------------------
# LLM resolver (mirrors cli.py / alignment.py pattern)
# ---------------------------------------------------------------------------

def _resolve_llm(*, json_mode: bool = True):
    """Return a real LLM callable using the default provider.

    json_mode=True for JSON-contract callers (alignment); prose callers
    (compare narrative) pass json_mode=False so OpenAI's forced JSON response
    format does not mangle free text.
    """

    from research_companion.extract import _call_anthropic, _call_openai, resolve_model

    provider, model = _pipeline_provider_model()
    resolved_model = resolve_model(provider, model)

    def _real_llm(prompt: str) -> str:
        if provider == "openai":
            text, _usage = _call_openai(prompt, model=resolved_model, json_mode=json_mode)
        else:
            text, _usage = _call_anthropic(prompt, model=resolved_model)
        return text

    return _real_llm


# ---------------------------------------------------------------------------
# serve_lab (foreground uvicorn)
# ---------------------------------------------------------------------------

def serve_lab(port: int = 8765, *, open_browser: bool = True) -> None:
    """Start the lab server on *port* and optionally open the browser.

    Imports fastapi/uvicorn lazily with a friendly error message.
    """
    try:
        import uvicorn
    except ImportError as exc:
        import sys
        print(
            "research-companion: lab server requires fastapi and uvicorn. "
            "Install with: pip install 'research-companion[server]'",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc

    # Load .env files before starting the server: cwd convention + store .env.
    # Exception-safe: missing files are fine. (stdlib import first per ruff I001)
    try:
        import pathlib as _pathlib

        from research_companion import settings as _settings
        _settings.load_env_file(_pathlib.Path.cwd() / ".env")
        _settings.load_env_file()
    except Exception:  # noqa: BLE001
        pass

    from research_companion.agents.bus import Bus
    from research_companion.agents.events import EventLog
    from research_companion.store import papergraph_dir

    pg = papergraph_dir()
    bus = Bus(log=EventLog(pg / "lab_events.jsonl") if pg is not None else None)
    app = create_lab_app(bus)

    if open_browser:
        async def _open_browser_task():
            import webbrowser
            await asyncio.sleep(1.0)
            webbrowser.open(f"http://127.0.0.1:{port}")

        async def _schedule_open():
            asyncio.create_task(_open_browser_task())

        # Starlette's router.on_startup is a plain list, not a decorator
        app.router.on_startup.append(_schedule_open)

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
