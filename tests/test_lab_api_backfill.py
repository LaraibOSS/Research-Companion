"""Tests for the one-shot weak-metadata backfill pass in lab_api.

Existing library papers uploaded before Task 1 have year=None. Task 1 changed
the extraction prompt sha, so their extraction.json is stale. A one-shot
background pass per active workspace re-runs extraction for such papers (that
still have text) so their year/authors backfill automatically.

These tests never call a real LLM: they set app.state.backfill_override to a
fake that records the enqueued paper ids, and drive the trigger seam
(app.state._trigger_backfill) on an event loop.
"""
from __future__ import annotations

import asyncio

import pytest

fastapi = pytest.importorskip("fastapi")

from research_companion.agents.bus import Bus  # noqa: E402
from research_companion.lab_api import create_lab_app  # noqa: E402


def _make_paper(paper_id: str, *, year: int | None, text: str,
                write_current_extraction: bool = False) -> None:
    """Create a paper in the store with the given year/text.

    write_current_extraction=True writes an extraction keyed on the CURRENT
    prompt sha (so load_extraction returns non-None → not stale).
    """
    from research_companion import store
    from research_companion.prompts import extraction_prompt_sha256

    meta = store.PaperMetadata(
        paper_id=paper_id,
        title=paper_id,
        authors=[],
        year=year,
        added_at="2024-01-01T00:00:00Z",
    )
    meta.save()
    store.save_text(paper_id, text)

    if write_current_extraction:
        store.save_extraction(
            paper_id,
            {"concepts": [], "methods": [], "datasets": [],
             "claims": [], "results": [], "related_work": []},
            prompt_sha=extraction_prompt_sha256(),
        )


def _run_backfill(app, *, times: int = 1) -> None:
    """Drive the backfill trigger `times` and let enqueued jobs run."""
    async def _scenario():
        for _ in range(times):
            await app.state._trigger_backfill()
        # let the per-paper _run tasks (and their override coros) complete
        await asyncio.sleep(0.05)

    asyncio.run(_scenario())


class TestBackfillSelection:
    def test_yearless_with_text_and_stale_extraction_is_enqueued(
            self, isolated_papergraph_dir):
        _make_paper("local:weak", year=None, text="Full text here.")

        recorded: list[str] = []

        async def fake_backfill(meta, bus):
            recorded.append(meta.paper_id)

        app = create_lab_app(Bus())
        app.state.backfill_override = fake_backfill

        _run_backfill(app)

        assert recorded == ["local:weak"]

    def test_current_prompt_extraction_not_selected(self, isolated_papergraph_dir):
        # year still None, but extraction already matches the current prompt sha
        _make_paper("local:done", year=None, text="Full text here.",
                    write_current_extraction=True)

        recorded: list[str] = []

        async def fake_backfill(meta, bus):
            recorded.append(meta.paper_id)

        app = create_lab_app(Bus())
        app.state.backfill_override = fake_backfill

        _run_backfill(app)

        assert recorded == []

    def test_empty_text_paper_is_skipped(self, isolated_papergraph_dir):
        _make_paper("local:scanned", year=None, text="")

        recorded: list[str] = []

        async def fake_backfill(meta, bus):
            recorded.append(meta.paper_id)

        app = create_lab_app(Bus())
        app.state.backfill_override = fake_backfill

        _run_backfill(app)

        assert recorded == []

    def test_paper_with_year_is_skipped(self, isolated_papergraph_dir):
        _make_paper("local:strong", year=2021, text="Full text here.")

        recorded: list[str] = []

        async def fake_backfill(meta, bus):
            recorded.append(meta.paper_id)

        app = create_lab_app(Bus())
        app.state.backfill_override = fake_backfill

        _run_backfill(app)

        assert recorded == []

    def test_reinvoking_same_workspace_is_idempotent(self, isolated_papergraph_dir):
        _make_paper("local:weak", year=None, text="Full text here.")

        recorded: list[str] = []

        async def fake_backfill(meta, bus):
            recorded.append(meta.paper_id)

        app = create_lab_app(Bus())
        app.state.backfill_override = fake_backfill

        # Two triggers in the same session for the same workspace → one enqueue
        _run_backfill(app, times=2)

        assert recorded == ["local:weak"]

    def test_running_paper_is_skipped(self, isolated_papergraph_dir):
        _make_paper("local:weak", year=None, text="Full text here.")

        recorded: list[str] = []

        async def fake_backfill(meta, bus):
            recorded.append(meta.paper_id)

        app = create_lab_app(Bus())
        app.state.backfill_override = fake_backfill
        # A job already processing this paper → do not double-enqueue
        app.state.jobs["job-x"] = {"status": "running", "kind": "add",
                                   "label": "x", "target": "local:weak"}

        _run_backfill(app)

        assert recorded == []


class TestBackfillStartupTrigger:
    def test_startup_triggers_backfill(self, isolated_papergraph_dir):
        from fastapi.testclient import TestClient

        _make_paper("local:weak", year=None, text="Full text here.")

        recorded: list[str] = []

        async def fake_backfill(meta, bus):
            recorded.append(meta.paper_id)

        app = create_lab_app(Bus())
        app.state.backfill_override = fake_backfill

        import time
        with TestClient(app):
            for _ in range(50):
                if recorded:
                    break
                time.sleep(0.02)

        assert recorded == ["local:weak"]
