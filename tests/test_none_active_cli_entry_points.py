"""FINAL-REVIEW fix: non-HTTP entry points that read papergraph_dir() directly
must degrade gracefully (friendly message + exit 1) instead of raising
``TypeError: unsupported operand type(s) for /: 'NoneType' and 'str'`` when no
research is active (fresh install / registry active: null).

Covers:
  - `research-companion review` (_cmd_review)
  - `research-companion lab ingest` (_cmd_lab_ingest)
  - the guarded Bus(log=...) expression used by serve_lab() (uvicorn.run is
    blocking, so serve_lab() itself is not invoked here — see the class
    docstring below for why).
"""
from __future__ import annotations

import pytest

from research_companion import cli, store


@pytest.fixture
def no_active_workspace(isolated_papergraph_dir):
    """Flip the autouse-seeded 'main' workspace's registry to active: None,
    keeping the workspace record itself (and its data) on disk untouched.

    Mirrors tests/test_none_active_workspace.py's fixture of the same name
    (duplicated here rather than imported across test modules, since pytest
    fixtures are file-scoped unless promoted to conftest.py).
    """
    reg = store.load_registry()
    reg["active"] = None
    store.save_registry(reg)
    store._reset_workspace_caches()
    return reg


class TestReviewNoneActive:
    def test_review_returns_1_with_friendly_message_when_none_active(
        self, no_active_workspace, capsys
    ):
        rc = cli.main(["review", "arxiv:whatever"])
        assert rc == 1
        err = capsys.readouterr().err
        assert "no active research" in err.lower()
        assert "workspace create" in err


class TestLabIngestNoneActive:
    def test_lab_ingest_returns_1_with_friendly_message_when_none_active(
        self, no_active_workspace, tmp_path, capsys
    ):
        folder = tmp_path / "pdfs"
        folder.mkdir()
        rc = cli.main(["lab", "ingest", str(folder)])
        assert rc == 1
        err = capsys.readouterr().err
        assert "no active research" in err.lower()
        assert "workspace create" in err


class TestServeLabBusLogGuard:
    """serve_lab() calls the blocking ``uvicorn.run`` at the end of the
    function, so it cannot be invoked directly in a unit test. Instead this
    exercises the exact guarded expression added to serve_lab() — mirroring
    the None-guard already proven at lab_api.py's delete_workspace_ep — to
    confirm constructing the Bus with a None papergraph_dir() does not raise
    and yields a Bus with log=None (matching what Bus/EventLog already
    support, per agents/bus.py)."""

    def test_bus_log_is_none_when_papergraph_dir_is_none(self, no_active_workspace):
        from research_companion.agents.bus import Bus
        from research_companion.agents.events import EventLog
        from research_companion.store import papergraph_dir

        pg = papergraph_dir()
        assert pg is None

        # The exact expression used in serve_lab().
        bus = Bus(log=EventLog(pg / "lab_events.jsonl") if pg is not None else None)

        assert bus._log is None

    def test_bus_log_is_set_when_papergraph_dir_is_active(self, isolated_papergraph_dir):
        from research_companion.agents.bus import Bus
        from research_companion.agents.events import EventLog
        from research_companion.store import papergraph_dir

        pg = papergraph_dir()
        assert pg is not None

        bus = Bus(log=EventLog(pg / "lab_events.jsonl") if pg is not None else None)

        assert bus._log is not None
        assert bus._log.path == pg / "lab_events.jsonl"
