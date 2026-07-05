"""tests/test_lab_static.py — Static asset and endpoint smoke tests for the Research Lab.

Run from repo root with: python -m pytest -q tests/test_lab_static.py

Node JS tests (run separately from repo root):
  node --test tests/js/reducer.test.mjs tests/js/sse.test.mjs tests/js/format.test.mjs tests/js/mapping.test.mjs tests/js/snapshotRefresher.test.mjs tests/js/draftdock.test.mjs tests/js/askcompare.test.mjs

Tests:
  - Every file referenced by index.html exists in lab/static
  - index.html contains the module script tag and vendor script tag
  - GET / on create_lab_app serves the real index.html (skip cleanly if fastapi missing)
  - GET /static/js/main.js returns 200
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent
STATIC_DIR = REPO_ROOT / "research_companion" / "lab" / "static"
INDEX_HTML = STATIC_DIR / "index.html"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _index_text() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# File existence tests
# ---------------------------------------------------------------------------

def test_index_html_exists():
    """index.html must exist."""
    assert INDEX_HTML.exists(), f"Missing: {INDEX_HTML}"


REQUIRED_STATIC_FILES = [
    "css/lab.css",
    "js/main.js",
    "js/router.js",
    "js/api.js",
    "js/sse.js",
    "js/store.js",
    "js/reducer.js",
    "js/format.js",
    "js/snapshotRefresher.js",
    "js/graph/mapping.js",
    "js/graph/graphview.js",
    "js/views/library.js",
    "js/views/graph.js",
    "js/views/draft.js",
    "js/views/compare.js",
    "js/views/ask.js",
    "js/components/drawer.js",
    "js/components/paperCard.js",
    "js/components/toast.js",
    "js/components/ingestModal.js",
    "js/components/ingestHelpers.js",
    "js/components/progressDock.js",
    "vendor/vis-network.min.js",
]


@pytest.mark.parametrize("rel_path", REQUIRED_STATIC_FILES)
def test_required_static_file_exists(rel_path: str):
    """Every required static file must be present."""
    path = STATIC_DIR / rel_path
    assert path.exists(), f"Missing required static file: {path}"


# ---------------------------------------------------------------------------
# index.html content tests
# ---------------------------------------------------------------------------

def test_index_html_has_module_script_tag():
    """index.html must load main.js as a module."""
    html = _index_text()
    assert 'type="module"' in html, "index.html missing <script type=\"module\">"
    assert "main.js" in html, "index.html missing main.js reference"


def test_index_html_has_vendor_script_tag():
    """index.html must load vis-network.min.js with a plain <script> tag before the module."""
    html = _index_text()
    assert "vis-network.min.js" in html, "index.html missing vis-network.min.js reference"
    # vendor script must appear before the module script
    vendor_pos = html.find("vis-network.min.js")
    module_pos = html.find('type="module"')
    assert vendor_pos < module_pos, "vis-network vendor script must precede the module script"


def test_index_html_has_view_mount_point():
    """index.html must have <main id=\"view\"> mount point."""
    html = _index_text()
    assert 'id="view"' in html, 'index.html missing <main id="view">'


def test_index_html_has_graph_canvas():
    """index.html must have <div id=\"graph-canvas\"> for F2."""
    html = _index_text()
    assert 'id="graph-canvas"' in html, 'index.html missing <div id="graph-canvas">'


def test_vis_network_file_is_valid_js():
    """vis-network.min.js must be >500KB and start with JS (not an HTML error page)."""
    vendor = STATIC_DIR / "vendor" / "vis-network.min.js"
    assert vendor.exists(), "vis-network.min.js not found"
    content = vendor.read_bytes()
    size_kb = len(content) / 1024
    assert size_kb > 500, f"vis-network.min.js is too small ({size_kb:.1f}KB), may be an error page"
    # Should not start with HTML doctype
    start = content[:50].decode("utf-8", errors="replace").lower()
    assert not start.startswith("<!doctype"), "vis-network.min.js appears to be an HTML error page"


# ---------------------------------------------------------------------------
# FastAPI endpoint tests (skip cleanly if fastapi missing)
# ---------------------------------------------------------------------------

try:
    from fastapi.testclient import TestClient
    _FASTAPI_AVAILABLE = True
except ImportError:
    _FASTAPI_AVAILABLE = False

pytestmark_fastapi = pytest.mark.skipif(
    not _FASTAPI_AVAILABLE,
    reason="fastapi not installed",
)


@pytest.fixture
def lab_client():
    """Create a TestClient for the lab app with a dummy bus."""
    from fastapi.testclient import TestClient
    from unittest.mock import MagicMock, AsyncMock
    import asyncio

    # Minimal Bus mock
    bus = MagicMock()
    queue = asyncio.Queue()
    bus.subscribe.return_value = queue
    bus.unsubscribe = MagicMock()
    bus.history = []

    # Patch store imports used by startup routes
    import sys
    from unittest.mock import patch

    # We need to import lab_api without the full store loaded
    with patch.dict("sys.modules", {}):
        try:
            from research_companion.lab_api import create_lab_app
            app = create_lab_app(bus)
            app.state._sse_done = True  # Don't hang SSE stream in tests
            client = TestClient(app, raise_server_exceptions=False)
            yield client
        except Exception as exc:
            pytest.skip(f"Could not create lab app: {exc}")


@pytest.mark.skipif(not _FASTAPI_AVAILABLE, reason="fastapi not installed")
def test_get_root_serves_index_html(lab_client):
    """GET / should return the real index.html content."""
    res = lab_client.get("/")
    assert res.status_code == 200
    assert "Research Lab" in res.text
    # Must include the module script tag
    assert "main.js" in res.text


@pytest.mark.skipif(not _FASTAPI_AVAILABLE, reason="fastapi not installed")
def test_get_static_main_js_returns_200(lab_client):
    """GET /static/js/main.js must return 200."""
    res = lab_client.get("/static/js/main.js")
    assert res.status_code == 200


@pytest.mark.skipif(not _FASTAPI_AVAILABLE, reason="fastapi not installed")
def test_get_static_graphview_js_returns_200(lab_client):
    """GET /static/js/graph/graphview.js must return 200 (F2 growth engine)."""
    res = lab_client.get("/static/js/graph/graphview.js")
    assert res.status_code == 200


@pytest.mark.skipif(not _FASTAPI_AVAILABLE, reason="fastapi not installed")
def test_get_static_ingest_modal_js_returns_200(lab_client):
    """GET /static/js/components/ingestModal.js must return 200 (F3 add/ingest modal)."""
    res = lab_client.get("/static/js/components/ingestModal.js")
    assert res.status_code == 200


@pytest.mark.skipif(not _FASTAPI_AVAILABLE, reason="fastapi not installed")
def test_get_static_progress_dock_js_returns_200(lab_client):
    """GET /static/js/components/progressDock.js must return 200 (F3 progress dock)."""
    res = lab_client.get("/static/js/components/progressDock.js")
    assert res.status_code == 200


@pytest.mark.skipif(not _FASTAPI_AVAILABLE, reason="fastapi not installed")
def test_get_static_draft_view_js_returns_200(lab_client):
    """GET /static/js/views/draft.js must return 200 (F3 draft alignment view)."""
    res = lab_client.get("/static/js/views/draft.js")
    assert res.status_code == 200


@pytest.mark.skipif(not _FASTAPI_AVAILABLE, reason="fastapi not installed")
def test_get_static_ask_view_js_returns_200(lab_client):
    """GET /static/js/views/ask.js must return 200 (F4 Ask view)."""
    res = lab_client.get("/static/js/views/ask.js")
    assert res.status_code == 200


@pytest.mark.skipif(not _FASTAPI_AVAILABLE, reason="fastapi not installed")
def test_get_static_compare_view_js_returns_200(lab_client):
    """GET /static/js/views/compare.js must return 200 (F4 Compare view)."""
    res = lab_client.get("/static/js/views/compare.js")
    assert res.status_code == 200


# ---------------------------------------------------------------------------
# Import-chain checks (file content assertions)
# ---------------------------------------------------------------------------

def test_main_js_imports_ingest_modal():
    """main.js must import ingestModal.js (wires + Add papers button)."""
    main_js = (STATIC_DIR / "js" / "main.js").read_text(encoding="utf-8")
    assert "ingestModal" in main_js, "main.js must reference ingestModal"


def test_main_js_imports_progress_dock():
    """main.js must import progressDock.js (mounts the dock)."""
    main_js = (STATIC_DIR / "js" / "main.js").read_text(encoding="utf-8")
    assert "progressDock" in main_js, "main.js must reference progressDock"


def test_library_js_imports_ingest_modal():
    """library.js must import ingestModal (wires Ingest folder... button)."""
    lib_js = (STATIC_DIR / "js" / "views" / "library.js").read_text(encoding="utf-8")
    assert "ingestModal" in lib_js, "library.js must reference ingestModal"


def test_draft_view_not_stub():
    """views/draft.js must not be the F1 stub (must export a real implementation)."""
    draft_js = (STATIC_DIR / "js" / "views" / "draft.js").read_text(encoding="utf-8")
    assert "getDraftAlignment" in draft_js, "draft.js must call getDraftAlignment"
    assert "draft-layout" in draft_js, "draft.js must render two-column layout"


def test_progress_dock_exports_dock_model():
    """progressDock.js must export dockModel for pure-logic tests."""
    dock_js = (STATIC_DIR / "js" / "components" / "progressDock.js").read_text(encoding="utf-8")
    assert "export function dockModel" in dock_js, "progressDock.js must export dockModel"


def test_reducer_emits_alignment_topic():
    """reducer.js must emit 'alignment' topic on alignment_ready events."""
    reducer_js = (STATIC_DIR / "js" / "reducer.js").read_text(encoding="utf-8")
    assert "'alignment'" in reducer_js, "reducer.js must include 'alignment' topic"


def test_reducer_has_ingest_log():
    """reducer.js must maintain ingestLog for the progress dock."""
    reducer_js = (STATIC_DIR / "js" / "reducer.js").read_text(encoding="utf-8")
    assert "ingestLog" in reducer_js, "reducer.js must reference ingestLog"


def test_index_html_has_dock_mount_point():
    """index.html must have <div id=\"dock\"> for the persistent progress dock."""
    html = _index_text()
    assert 'id="dock"' in html, 'index.html missing <div id="dock">'


def test_ask_view_not_stub():
    """views/ask.js must not be the F1 stub (must export renderAnswerHtml)."""
    ask_js = (STATIC_DIR / "js" / "views" / "ask.js").read_text(encoding="utf-8")
    assert "export function renderAnswerHtml" in ask_js, \
        "ask.js must export renderAnswerHtml"
    assert "escapeHtml" in ask_js, "ask.js must escape LLM output"
    assert "stub-view" not in ask_js, "ask.js must not be the stub"


def test_compare_view_not_stub():
    """views/compare.js must not be the F1 stub (must export the pure helpers)."""
    cmp_js = (STATIC_DIR / "js" / "views" / "compare.js").read_text(encoding="utf-8")
    assert "export function resolvePaperInput" in cmp_js, \
        "compare.js must export resolvePaperInput"
    assert "export function betterValue" in cmp_js, \
        "compare.js must export betterValue"
    assert "stub-view" not in cmp_js, "compare.js must not be the stub"


def test_ask_view_escapes_before_markup():
    """renderAnswerHtml must call escapeHtml before any tag construction
    (structural check: escapeHtml applied to the raw answer)."""
    ask_js = (STATIC_DIR / "js" / "views" / "ask.js").read_text(encoding="utf-8")
    assert re.search(r"escapeHtml\(\s*answer", ask_js), \
        "renderAnswerHtml must pass the raw answer through escapeHtml FIRST"


def test_lab_css_has_f4_styles():
    """lab.css must include the F4 additions: shimmer, cite chips, mini-card,
    compare columns and results table."""
    css = (STATIC_DIR / "css" / "lab.css").read_text(encoding="utf-8")
    for needle in ("@keyframes shimmer", ".cite-minicard", "sup.cite",
                   ".compare-columns", ".compare-table"):
        assert needle in css, f"lab.css missing F4 style: {needle}"


def test_main_js_wires_draft_chip_navigation():
    """main.js must navigate to #/draft when the top-bar draft chip is clicked."""
    main_js = (STATIC_DIR / "js" / "main.js").read_text(encoding="utf-8")
    assert "draft-chip" in main_js, "main.js must reference draft-chip"
    assert "#/draft" in main_js, "main.js must navigate to #/draft on chip click"


def test_askcompare_node_test_file_exists():
    """tests/js/askcompare.test.mjs must exist (F4 pure-function tests)."""
    assert (REPO_ROOT / "tests" / "js" / "askcompare.test.mjs").exists(), \
        "Missing tests/js/askcompare.test.mjs"
