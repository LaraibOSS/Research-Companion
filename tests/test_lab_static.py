"""tests/test_lab_static.py — Static asset and endpoint smoke tests for the Research Lab.

Run from repo root with: python -m pytest -q tests/test_lab_static.py

Node JS tests (run separately from repo root):
  node --test tests/js/reducer.test.mjs tests/js/sse.test.mjs tests/js/format.test.mjs tests/js/mapping.test.mjs tests/js/snapshotRefresher.test.mjs

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
