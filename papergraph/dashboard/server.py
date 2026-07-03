"""Live dashboard: serves the page, a state snapshot, and an SSE event stream."""
from __future__ import annotations

import asyncio
import json
import sys
import time

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse

from papergraph.agents.bus import Bus
from papergraph.agents.events import event_to_dict
from papergraph.dashboard.page import PAGE_HTML

# Cross-loop contract: the SSE generator and Bus.publish may run on different
# thread event loops.  Delivery relies on the 0.2 s poll timeout in gen();
# put_nowait in Bus.publish is best-effort (see bus.py for the suppress guard).


def _run_uvicorn_in_thread(app, port: int) -> None:
    """Start uvicorn in a daemon background thread; poll until started (~2 s)."""
    import threading

    import uvicorn

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)

    t = threading.Thread(target=server.run, daemon=True)
    t.start()

    # Minor 8: surface startup failure (e.g. port already in use).
    for _ in range(20):
        if server.started:
            return
        time.sleep(0.1)
    print(
        "papergraph: warning: dashboard failed to start (port in use?)",
        file=sys.stderr,
    )


def create_app(bus: Bus, state: dict) -> FastAPI:
    app = FastAPI(title="papergraph dashboard")

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return PAGE_HTML

    @app.get("/state")
    async def get_state() -> dict:
        # Minor 6: atomic C-level copy to avoid cross-thread races.
        return {"lanes": dict(state.get("lanes", {})), "done": state.get("done", False)}

    @app.get("/events")
    async def events_stream() -> StreamingResponse:
        async def gen():
            # SSE gap fix: subscribe FIRST, snapshot history AFTER, then replay
            # history; skip any live queue events already in the snapshot to avoid
            # duplicates.
            q = bus.subscribe()
            snapshot = list(bus.history)
            seen = {id(e) for e in snapshot}
            try:
                for e in snapshot:
                    yield f"data: {json.dumps(event_to_dict(e))}\n\n"
                while not (state.get("done") and q.empty()):
                    try:
                        e = await asyncio.wait_for(q.get(), timeout=0.2)
                    except asyncio.TimeoutError:
                        continue
                    if id(e) in seen:
                        seen.discard(id(e))
                        continue
                    yield f"data: {json.dumps(event_to_dict(e))}\n\n"
            finally:
                bus.unsubscribe(q)

        return StreamingResponse(gen(), media_type="text/event-stream")

    return app
