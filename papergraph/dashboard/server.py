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
