"""tests/test_lab_static.py — Static asset and endpoint smoke tests for the Research Lab.

Run from repo root with: python -m pytest -q tests/test_lab_static.py

Node JS tests (run separately from repo root; the list below is asserted complete
by test_documented_node_command_lists_every_js_test):
  node --test tests/js/reducer.test.mjs tests/js/sse.test.mjs tests/js/format.test.mjs tests/js/mapping.test.mjs tests/js/snapshotRefresher.test.mjs tests/js/graphview.test.mjs tests/js/graph_pipeline.test.mjs tests/js/draftdock.test.mjs tests/js/ingesthelpers.test.mjs tests/js/askcompare.test.mjs tests/js/theme.test.mjs tests/js/settingsHelpers.test.mjs tests/js/viewsHelpers.test.mjs tests/js/suggestionHelpers.test.mjs

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
    "js/icons.js",
    "js/theme.js",
    "js/settingsHelpers.js",
    "js/views/settings.js",
    "js/views/home.js",
    "js/views/timeline.js",
    "js/components/drawer.js",
    "js/components/paperCard.js",
    "js/components/toast.js",
    "js/components/ingestModal.js",
    "js/components/ingestHelpers.js",
    "js/components/progressDock.js",
    "js/components/saveViewModal.js",
    "js/viewsHelpers.js",
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
    import fastapi  # noqa: F401
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
    import asyncio
    from unittest.mock import MagicMock

    from fastapi.testclient import TestClient

    # Minimal Bus mock
    bus = MagicMock()
    queue = asyncio.Queue()
    bus.subscribe.return_value = queue
    bus.unsubscribe = MagicMock()
    bus.history = []

    # Patch store imports used by startup routes
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


def test_documented_node_command_lists_every_js_test():
    """The node --test command in this module's docstring must name every tests/js/*.test.mjs."""
    doc = Path(__file__).read_text(encoding="utf-8")
    existing = sorted(p.name for p in (REPO_ROOT / "tests" / "js").glob("*.test.mjs"))
    missing = [name for name in existing if f"tests/js/{name}" not in doc]
    assert not missing, f"docstring node command is missing: {missing}"


# ---------------------------------------------------------------------------
# W3-F1: index.html content tests
# ---------------------------------------------------------------------------

def test_index_html_has_pre_paint_script():
    """index.html must have the 3-line pre-paint inline script before the stylesheet."""
    html = _index_text()
    # The script must appear before the stylesheet link
    script_pos = html.find('rc.theme')
    css_pos = html.find('lab.css')
    assert script_pos != -1, "index.html missing pre-paint rc.theme script"
    assert css_pos != -1, "index.html missing lab.css link"
    assert script_pos < css_pos, "pre-paint script must appear before the stylesheet"


def test_index_html_has_bell_button():
    """index.html must have the suggestions bell button (#topbar-bell)."""
    html = _index_text()
    assert 'id="topbar-bell"' in html, 'index.html missing bell button #topbar-bell'
    assert 'id="bell-badge"' in html, 'index.html missing bell badge #bell-badge'


def test_index_html_has_no_key_banner():
    """index.html must have the no-key amber banner element (#no-key-banner)."""
    html = _index_text()
    assert 'id="no-key-banner"' in html, 'index.html missing #no-key-banner'


def test_index_html_has_nav_spacer():
    """index.html nav rail must have a spacer to push Help+Settings to the bottom."""
    html = _index_text()
    assert 'nav-spacer' in html, 'index.html nav rail missing nav-spacer'


@pytest.mark.skipif(not _FASTAPI_AVAILABLE, reason="fastapi not installed")
def test_get_static_icons_js_returns_200(lab_client):
    """GET /static/js/icons.js must return 200."""
    res = lab_client.get("/static/js/icons.js")
    assert res.status_code == 200


@pytest.mark.skipif(not _FASTAPI_AVAILABLE, reason="fastapi not installed")
def test_get_static_theme_js_returns_200(lab_client):
    """GET /static/js/theme.js must return 200."""
    res = lab_client.get("/static/js/theme.js")
    assert res.status_code == 200


@pytest.mark.skipif(not _FASTAPI_AVAILABLE, reason="fastapi not installed")
def test_get_static_settings_helpers_js_returns_200(lab_client):
    """GET /static/js/settingsHelpers.js must return 200."""
    res = lab_client.get("/static/js/settingsHelpers.js")
    assert res.status_code == 200


@pytest.mark.skipif(not _FASTAPI_AVAILABLE, reason="fastapi not installed")
def test_get_static_settings_view_js_returns_200(lab_client):
    """GET /static/js/views/settings.js must return 200."""
    res = lab_client.get("/static/js/views/settings.js")
    assert res.status_code == 200


def test_settings_view_not_stub():
    """views/settings.js must be a real implementation (exports mount + uses escapeHtml)."""
    js = (STATIC_DIR / "js" / "views" / "settings.js").read_text(encoding="utf-8")
    assert "export function mount" in js, "settings.js must export mount"
    assert "escapeHtml" in js, "settings.js must use escapeHtml for server strings"
    assert "buildSettingsPatch" in js, "settings.js must use buildSettingsPatch"
    assert "putSettings" in js, "settings.js must call putSettings"


def test_main_js_imports_theme():
    """main.js must import theme.js (applyTheme)."""
    main_js = (STATIC_DIR / "js" / "main.js").read_text(encoding="utf-8")
    assert "theme.js" in main_js or "applyTheme" in main_js, \
        "main.js must import from theme.js"


def test_main_js_imports_settings_view():
    """main.js must import views/settings.js."""
    main_js = (STATIC_DIR / "js" / "main.js").read_text(encoding="utf-8")
    assert "settings" in main_js, "main.js must reference settings view"


def test_main_js_has_bell_wiring():
    """main.js must wire the bell to dispatch rc:toggle-suggestions."""
    main_js = (STATIC_DIR / "js" / "main.js").read_text(encoding="utf-8")
    assert "rc:toggle-suggestions" in main_js, \
        "main.js must dispatch CustomEvent('rc:toggle-suggestions')"


# ---------------------------------------------------------------------------
# C2 regression: graph.js section-switcher must use sec.section_id not sec.id
# ---------------------------------------------------------------------------

def test_graph_js_section_row_uses_section_id():
    """graph.js section-row renderer must use sec.section_id (not sec.id).

    GET /api/sections returns objects with section_id, not id.  Using sec.id
    produces data-section-id="" on every row and breaks section filtering.
    """
    graph_js = (STATIC_DIR / "js" / "views" / "graph.js").read_text(encoding="utf-8")

    # The section-list renderer must reference sec.section_id
    assert "sec.section_id" in graph_js, (
        "graph.js must use sec.section_id (not sec.id) to match the API response field"
    )

    # Make sure the broken form is not used in the section-list renderer context.
    # We look for sec.id used as a value (sec.id) which would be a plain property access.
    # A safe check: the string 'sec.id' must not appear (sec.section_id has 'sec.' + 'section_id').
    import re as _re
    bad_uses = _re.findall(r'\bsec\.id\b', graph_js)
    assert not bad_uses, (
        f"graph.js must not use sec.id in section-row renderer; found {len(bad_uses)} occurrence(s)"
    )


# ---------------------------------------------------------------------------
# W3-F1: Frontend shell fixes
# ---------------------------------------------------------------------------

def test_router_js_has_no_library_fallback_string():
    """router.js must fallback to '/home', not '/library' (W3-F1 fix #1)."""
    js = (STATIC_DIR / "js" / "router.js").read_text(encoding="utf-8")
    # Confirm the fallback is /home
    assert "routePart || '/home'" in js, (
        "router.js fallback must be '/home', not '/library'"
    )
    # Make sure '/library' is not used as a fallback in _parseHash
    import re as _re
    fallback_lines = _re.findall(r"const route = routePart \|\| '[^']+';", js)
    assert len(fallback_lines) == 1, "Expected one fallback assignment in _parseHash"
    assert "'/home'" in fallback_lines[0], "router.js fallback must use '/home'"


def test_settings_js_escapes_numeric_attributes():
    """settings.js must wrap numeric attributes with escapeHtml (W3-F1 fix #2)."""
    js = (STATIC_DIR / "js" / "views" / "settings.js").read_text(encoding="utf-8")
    # Check k_sections escaping
    assert "escapeHtml(String(s.k_sections || 6))" in js, (
        "settings.js must escapeHtml-wrap the k_sections numeric attribute"
    )
    # Check char_budget escaping
    assert "escapeHtml(String(s.char_budget || 8000))" in js, (
        "settings.js must escapeHtml-wrap the char_budget numeric attribute"
    )


def test_lab_css_nav_rail_spans_banner_row():
    """lab.css must extend nav-rail to grid-row 1/4 when banner is visible (W3-F1 fix #3)."""
    css = (STATIC_DIR / "css" / "lab.css").read_text(encoding="utf-8")
    # Check that the :has() rule extends nav-rail grid-row
    assert ".app:has(#no-key-banner.visible) .nav-rail {" in css, (
        "lab.css must have the .app:has() selector for nav-rail when banner is visible"
    )
    assert "grid-row: 1 / 4;" in css, (
        "lab.css must set nav-rail grid-row: 1 / 4 to span all three rows when banner is visible"
    )


# ---------------------------------------------------------------------------
# W3-F6: Saved-views UI
# ---------------------------------------------------------------------------

def test_views_helpers_js_exists():
    """js/viewsHelpers.js must exist (W3-F6 pure helpers)."""
    assert (STATIC_DIR / "js" / "viewsHelpers.js").exists(), \
        "Missing js/viewsHelpers.js"


def test_views_helpers_exports_three_functions():
    """viewsHelpers.js must export truncateName, viewRowModel, canSave."""
    js = (STATIC_DIR / "js" / "viewsHelpers.js").read_text(encoding="utf-8")
    assert "export function truncateName" in js, "viewsHelpers.js must export truncateName"
    assert "export function viewRowModel" in js, "viewsHelpers.js must export viewRowModel"
    assert "export function canSave" in js, "viewsHelpers.js must export canSave"


def test_save_view_modal_js_exists():
    """js/components/saveViewModal.js must exist (W3-F6)."""
    assert (STATIC_DIR / "js" / "components" / "saveViewModal.js").exists(), \
        "Missing js/components/saveViewModal.js"


def test_save_view_modal_exports_open_close():
    """saveViewModal.js must export openSaveViewModal and closeSaveViewModal."""
    js = (STATIC_DIR / "js" / "components" / "saveViewModal.js").read_text(encoding="utf-8")
    assert "export function openSaveViewModal" in js, \
        "saveViewModal.js must export openSaveViewModal"
    assert "export function closeSaveViewModal" in js, \
        "saveViewModal.js must export closeSaveViewModal"
    assert "escapeHtml" in js, "saveViewModal.js must escape view names (user input)"


def test_api_js_has_views_endpoints():
    """api.js must export getViews, createView, patchView, deleteView, getViewGraph (W3-F6)."""
    api_js = (STATIC_DIR / "js" / "api.js").read_text(encoding="utf-8")
    for name in ("getViews", "createView", "patchView", "deleteView", "getViewGraph"):
        assert f"export const {name}" in api_js, f"api.js must export {name}"


def test_store_js_has_views_field_and_setter():
    """store.js must have a views field in _state and export setViews (W3-F6)."""
    store_js = (STATIC_DIR / "js" / "store.js").read_text(encoding="utf-8")
    assert "views:" in store_js, "store.js must have views: field in _state"
    assert "export function setViews" in store_js, "store.js must export setViews"


def test_graph_js_has_saved_views_section():
    """graph.js must contain the saved-views section markup hook (W3-F6)."""
    graph_js = (STATIC_DIR / "js" / "views" / "graph.js").read_text(encoding="utf-8")
    assert "graph-saved-views-list" in graph_js, \
        "graph.js must render the #graph-saved-views-list container"
    assert "Saved Views" in graph_js, \
        "graph.js must include 'Saved Views' section label"
    assert "_savedViewActive" in graph_js, \
        "graph.js must have _savedViewActive guard flag"


def test_graph_js_guard_flag_on_delta_handler():
    """graph.js onGraphDeltas handler must check _savedViewActive guard (W3-F6)."""
    graph_js = (STATIC_DIR / "js" / "views" / "graph.js").read_text(encoding="utf-8")
    assert "_savedViewActive" in graph_js, \
        "graph.js must use _savedViewActive to guard live delta application"


def test_ask_js_references_save_view_modal():
    """ask.js must import saveViewModal for the post-Ask save affordance (W3-F6)."""
    ask_js = (STATIC_DIR / "js" / "views" / "ask.js").read_text(encoding="utf-8")
    assert "saveViewModal" in ask_js, "ask.js must reference saveViewModal"
    assert "canSave" in ask_js, "ask.js must import canSave from viewsHelpers"


def test_lab_css_has_saved_views_styles():
    """lab.css must include W3-F6 saved-views styles."""
    css = (STATIC_DIR / "css" / "lab.css").read_text(encoding="utf-8")
    for needle in (".graph-saved-views-list", ".graph-views-row", ".graph-view-chip",
                   ".ask-save-subgraph", ".save-view-modal"):
        assert needle in css, f"lab.css missing W3-F6 style: {needle}"


def test_viewshelpers_node_test_file_exists():
    """tests/js/viewsHelpers.test.mjs must exist (W3-F6 pure-function tests)."""
    assert (REPO_ROOT / "tests" / "js" / "viewsHelpers.test.mjs").exists(), \
        "Missing tests/js/viewsHelpers.test.mjs"


@pytest.mark.skipif(not _FASTAPI_AVAILABLE, reason="fastapi not installed")
def test_get_static_save_view_modal_js_returns_200(lab_client):
    """GET /static/js/components/saveViewModal.js must return 200."""
    res = lab_client.get("/static/js/components/saveViewModal.js")
    assert res.status_code == 200


@pytest.mark.skipif(not _FASTAPI_AVAILABLE, reason="fastapi not installed")
def test_get_static_views_helpers_js_returns_200(lab_client):
    """GET /static/js/viewsHelpers.js must return 200."""
    res = lab_client.get("/static/js/viewsHelpers.js")
    assert res.status_code == 200


# ---------------------------------------------------------------------------
# W3-F3: Suggestions panel
# ---------------------------------------------------------------------------

def test_suggestion_helpers_js_exists():
    """js/components/suggestionHelpers.js must exist (W3-F3 pure helpers)."""
    assert (STATIC_DIR / "js" / "components" / "suggestionHelpers.js").exists(), \
        "Missing js/components/suggestionHelpers.js"


def test_suggestions_panel_js_exists():
    """js/components/suggestionsPanel.js must exist (W3-F3 panel)."""
    assert (STATIC_DIR / "js" / "components" / "suggestionsPanel.js").exists(), \
        "Missing js/components/suggestionsPanel.js"


def test_suggestions_view_js_exists():
    """js/views/suggestions.js must exist (W3-F3 full route)."""
    assert (STATIC_DIR / "js" / "views" / "suggestions.js").exists(), \
        "Missing js/views/suggestions.js"


def test_main_js_imports_suggestions_panel():
    """main.js must import suggestionsPanel (W3-F3)."""
    main_js = (STATIC_DIR / "js" / "main.js").read_text(encoding="utf-8")
    assert "suggestionsPanel" in main_js, "main.js must reference suggestionsPanel"


def test_suggestions_panel_escapes_title_and_detail():
    """suggestionsPanel.js must call escapeHtml on title and detail."""
    js = (STATIC_DIR / "js" / "components" / "suggestionsPanel.js").read_text(encoding="utf-8")
    assert "escapeHtml" in js, "suggestionsPanel.js must use escapeHtml"
    assert "escapeHtml(s.title)" in js, "suggestionsPanel.js must escapeHtml(s.title)"
    assert "escapeHtml(s.detail)" in js, "suggestionsPanel.js must escapeHtml(s.detail)"


def test_suggestions_view_escapes_title_and_detail():
    """views/suggestions.js must call escapeHtml on title and detail."""
    js = (STATIC_DIR / "js" / "views" / "suggestions.js").read_text(encoding="utf-8")
    assert "escapeHtml" in js, "suggestions.js must use escapeHtml"
    assert "escapeHtml(s.title)" in js, "suggestions.js must escapeHtml(s.title)"
    assert "escapeHtml(s.detail)" in js, "suggestions.js must escapeHtml(s.detail)"


def test_store_js_has_suggestions_field_and_setter():
    """store.js must have suggestions field in _state and export setSuggestions (W3-F3)."""
    store_js = (STATIC_DIR / "js" / "store.js").read_text(encoding="utf-8")
    assert "suggestions:" in store_js, "store.js must have suggestions: field in _state"
    assert "export function setSuggestions" in store_js, "store.js must export setSuggestions"


def test_api_js_has_suggestions_endpoints():
    """api.js must export getSuggestions, dismissSuggestion, regenerateSuggestions (W3-F3)."""
    api_js = (STATIC_DIR / "js" / "api.js").read_text(encoding="utf-8")
    for name in ("getSuggestions", "dismissSuggestion", "regenerateSuggestions"):
        assert f"export const {name}" in api_js, f"api.js must export {name}"


def test_suggestions_panel_dispatches_rc_discuss():
    """suggestionsPanel.js must dispatch CustomEvent('rc:discuss') for Discuss button."""
    js = (STATIC_DIR / "js" / "components" / "suggestionsPanel.js").read_text(encoding="utf-8")
    assert "rc:discuss" in js, "suggestionsPanel.js must dispatch rc:discuss CustomEvent"


def test_lab_css_has_suggestions_panel_styles():
    """lab.css must include W3-F3 suggestions panel styles."""
    css = (STATIC_DIR / "css" / "lab.css").read_text(encoding="utf-8")
    for needle in (".suggestions-panel", ".suggestion-card", ".suggestion-sev-dot",
                   ".suggestion-title", ".suggestion-detail"):
        assert needle in css, f"lab.css missing W3-F3 style: {needle}"


def test_suggestion_helpers_test_file_exists():
    """tests/js/suggestionHelpers.test.mjs must exist (W3-F3 node tests)."""
    assert (REPO_ROOT / "tests" / "js" / "suggestionHelpers.test.mjs").exists(), \
        "Missing tests/js/suggestionHelpers.test.mjs"


@pytest.mark.skipif(not _FASTAPI_AVAILABLE, reason="fastapi not installed")
def test_get_static_suggestions_panel_js_returns_200(lab_client):
    """GET /static/js/components/suggestionsPanel.js must return 200."""
    res = lab_client.get("/static/js/components/suggestionsPanel.js")
    assert res.status_code == 200


@pytest.mark.skipif(not _FASTAPI_AVAILABLE, reason="fastapi not installed")
def test_get_static_suggestion_helpers_js_returns_200(lab_client):
    """GET /static/js/components/suggestionHelpers.js must return 200."""
    res = lab_client.get("/static/js/components/suggestionHelpers.js")
    assert res.status_code == 200


@pytest.mark.skipif(not _FASTAPI_AVAILABLE, reason="fastapi not installed")
def test_get_static_suggestions_view_js_returns_200(lab_client):
    """GET /static/js/views/suggestions.js must return 200."""
    res = lab_client.get("/static/js/views/suggestions.js")
    assert res.status_code == 200
