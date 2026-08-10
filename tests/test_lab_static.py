"""tests/test_lab_static.py — Static asset and endpoint smoke tests for the Research Companion.

Run from repo root with: python -m pytest -q tests/test_lab_static.py

Node JS tests (run separately from repo root; the list below is asserted complete
by test_documented_node_command_lists_every_js_test):
  node --test tests/js/reducer.test.mjs tests/js/sse.test.mjs tests/js/format.test.mjs tests/js/mapping.test.mjs tests/js/snapshotRefresher.test.mjs tests/js/graphview.test.mjs tests/js/graph_pipeline.test.mjs tests/js/draftdock.test.mjs tests/js/ingesthelpers.test.mjs tests/js/askcompare.test.mjs tests/js/theme.test.mjs tests/js/settingsHelpers.test.mjs tests/js/viewsHelpers.test.mjs tests/js/suggestionHelpers.test.mjs tests/js/home.test.mjs tests/js/timelineLayout.test.mjs tests/js/converse.test.mjs tests/js/glossary.test.mjs tests/js/libraryHelpers.test.mjs tests/js/draftLayout.test.mjs tests/js/workspaceHelpers.test.mjs tests/js/citationsHelpers.test.mjs tests/js/activityHelpers.test.mjs tests/js/placementHelpers.test.mjs tests/js/readerHelpers.test.mjs tests/js/readerPdfHelpers.test.mjs tests/js/readerSimplifiedHelpers.test.mjs tests/js/metadataForm.test.mjs tests/js/homehelpers.test.mjs tests/js/keyPromptHelpers.test.mjs tests/js/researchNudgeHelpers.test.mjs tests/js/citationPolarityColors.test.mjs tests/js/settings-connectors.test.mjs tests/js/oaLinkHelpers.test.mjs tests/js/opportunityHelpers.test.mjs tests/js/noteRecord.test.mjs tests/js/researchGuard.test.mjs tests/js/gapHelpers.test.mjs

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
    "js/theme.js",
    "js/settingsHelpers.js",
    "js/views/settings.js",
    "js/views/home.js",
    "js/views/timeline.js",
    "js/timeline/layout.js",
    "js/components/drawer.js",
    "js/components/paperCard.js",
    "js/components/toast.js",
    "js/components/ingestModal.js",
    "js/components/ingestHelpers.js",
    "js/components/progressDock.js",
    "js/components/saveViewModal.js",
    "js/viewsHelpers.js",
    "vendor/vis-network.min.js",
    # W3-F7 additions
    "js/glossary.js",
    "js/components/explainer.js",
    "js/components/helpPanel.js",
    # W4-F2 additions
    "js/libraryHelpers.js",
    # W4-F3 additions
    "js/graph/draftLayout.js",
    # W4-F1 additions
    "js/workspaceHelpers.js",
    "js/views/researches.js",
    "js/gapHelpers.js",
    "js/views/gaps.js",
    "js/components/workspaceSwitcher.js",
    # W5-C3 additions
    "js/citationsHelpers.js",
    "js/components/citationsPanel.js",
    # W5-ACT additions
    "js/activityHelpers.js",
    # feat/find-pdf-online additions
    "js/oaLinkHelpers.js",
    # feat/draft-opportunities (Task 3 + 4) additions
    "js/opportunityHelpers.js",
    "js/views/notes.js",
    # feat/no-research-selected additions
    "js/researchGuard.js",
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
    assert "Research Companion" in res.text
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
    """views/ask.js must not be the F1 stub (must export renderAnswerHtml — either
    as a definition or as a re-export from answerHtml.js after W3-F4 extraction)."""
    ask_js = (STATIC_DIR / "js" / "views" / "ask.js").read_text(encoding="utf-8")
    # Accept both the original definition form and the W3-F4 re-export form
    assert ("export function renderAnswerHtml" in ask_js or
            "export { renderAnswerHtml }" in ask_js or
            "export {renderAnswerHtml}" in ask_js), \
        "ask.js must export renderAnswerHtml (definition or re-export)"
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
    """renderAnswerHtml must call escapeHtml before any tag construction.
    After W3-F4 extraction the canonical location is answerHtml.js; ask.js
    may re-export, so we check either file."""
    ask_js = (STATIC_DIR / "js" / "views" / "ask.js").read_text(encoding="utf-8")
    answer_html_js_path = STATIC_DIR / "js" / "answerHtml.js"
    if answer_html_js_path.exists():
        combined = ask_js + answer_html_js_path.read_text(encoding="utf-8")
    else:
        combined = ask_js
    assert re.search(r"escapeHtml\(\s*answer", combined), \
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


def test_home_motion_layer_respects_reduced_motion():
    css = (STATIC_DIR / "css" / "lab.css").read_text(encoding="utf-8")
    # entrance + sparkline draw-in keyframes exist and are gated on the one-time class
    assert "@keyframes home-rise" in css
    assert "@keyframes home-draw" in css
    assert ".home-animate-in" in css
    # a reduced-motion block that neutralizes Home motion
    # (use rfind: lab.css already has earlier, unrelated reduced-motion
    # blocks for .activity-spin/.reader-spin; the Home one is appended last)
    idx = css.rfind("prefers-reduced-motion")
    assert idx != -1, "must have a prefers-reduced-motion block"
    tail = css[idx:idx + 600]
    assert "home-animate-in" in tail or "home-nav-card" in tail
    assert "animation: none" in tail and "transition: none" in tail


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


def test_graph_js_section_bullet_uses_plain_number():
    """graph.js section-bullet must render 'n.' not the '§' glyph."""
    graph_js = (STATIC_DIR / "js" / "views" / "graph.js").read_text(encoding="utf-8")
    assert "§" not in graph_js, "graph.js must not contain the § glyph"
    assert '"graph-section-bullet">${idx + 1}.</span>' in graph_js, (
        "graph.js section-bullet must render the plain 'n.' form"
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


# ---------------------------------------------------------------------------
# W3-F3 fix: rc:open-paper listener and pending-paper handoff
# ---------------------------------------------------------------------------

def test_library_js_listens_for_rc_open_paper():
    """library.js mount() must add a window listener for rc:open-paper (W3-F3 fix HIGH-1)."""
    lib_js = (STATIC_DIR / "js" / "views" / "library.js").read_text(encoding="utf-8")
    assert "rc:open-paper" in lib_js, (
        "library.js must listen for 'rc:open-paper' CustomEvent to open drawer"
    )
    assert "addEventListener('rc:open-paper'" in lib_js or 'addEventListener("rc:open-paper"' in lib_js, (
        "library.js must register a 'rc:open-paper' event listener"
    )


def test_library_js_removes_rc_open_paper_listener_on_unmount():
    """library.js unmount() must remove the rc:open-paper listener (no leak)."""
    lib_js = (STATIC_DIR / "js" / "views" / "library.js").read_text(encoding="utf-8")
    assert "removeEventListener('rc:open-paper'" in lib_js or 'removeEventListener("rc:open-paper"' in lib_js, (
        "library.js unmount must call removeEventListener for 'rc:open-paper'"
    )


def test_library_js_checks_pending_paper_on_mount():
    """library.js mount() must check window.__rcPendingPaper (arrive-before-mount race)."""
    lib_js = (STATIC_DIR / "js" / "views" / "library.js").read_text(encoding="utf-8")
    assert "__rcPendingPaper" in lib_js, (
        "library.js must handle window.__rcPendingPaper fallback for arrive-before-mount race"
    )


def test_suggestions_panel_sets_pending_paper():
    """suggestionsPanel.js must set window.__rcPendingPaper before dispatching rc:open-paper."""
    js = (STATIC_DIR / "js" / "components" / "suggestionsPanel.js").read_text(encoding="utf-8")
    assert "__rcPendingPaper" in js, (
        "suggestionsPanel.js must set window.__rcPendingPaper as fallback handoff"
    )


def test_suggestions_view_sets_pending_paper():
    """views/suggestions.js must set window.__rcPendingPaper before dispatching rc:open-paper."""
    js = (STATIC_DIR / "js" / "views" / "suggestions.js").read_text(encoding="utf-8")
    assert "__rcPendingPaper" in js, (
        "suggestions.js must set window.__rcPendingPaper as fallback handoff"
    )


def test_suggestions_panel_uses_injected_api():
    """suggestionsPanel.js _bindEvents must use apiRef (injected) not bare api module."""
    js = (STATIC_DIR / "js" / "components" / "suggestionsPanel.js").read_text(encoding="utf-8")
    assert "apiRef.regenerateSuggestions" in js, (
        "suggestionsPanel.js must call apiRef.regenerateSuggestions (injected)"
    )
    assert "apiRef.dismissSuggestion" in js, (
        "suggestionsPanel.js must call apiRef.dismissSuggestion (injected)"
    )
    assert "apiRef.getSuggestions" in js, (
        "suggestionsPanel.js must call apiRef.getSuggestions (injected)"
    )


def test_suggestions_view_uses_injected_api():
    """views/suggestions.js _bindEvents must use apiRef (injected) not bare api module."""
    js = (STATIC_DIR / "js" / "views" / "suggestions.js").read_text(encoding="utf-8")
    assert "apiRef.regenerateSuggestions" in js, (
        "suggestions.js must call apiRef.regenerateSuggestions (injected)"
    )
    assert "apiRef.dismissSuggestion" in js, (
        "suggestions.js must call apiRef.dismissSuggestion (injected)"
    )
    assert "apiRef.getSuggestions" in js, (
        "suggestions.js must call apiRef.getSuggestions (injected)"
    )


def test_suggestions_panel_imports_escape_from_format():
    """suggestionsPanel.js must import escapeHtml from format.js (no local duplicate)."""
    js = (STATIC_DIR / "js" / "components" / "suggestionsPanel.js").read_text(encoding="utf-8")
    assert "from '../format.js'" in js, (
        "suggestionsPanel.js must import from format.js instead of defining local escapeHtml"
    )
    # Ensure no local function definition of escapeHtml
    assert "function escapeHtml" not in js, (
        "suggestionsPanel.js must not define a local escapeHtml (use format.js export)"
    )


def test_suggestions_view_imports_escape_from_format():
    """views/suggestions.js must import escapeHtml from format.js (no local duplicate)."""
    js = (STATIC_DIR / "js" / "views" / "suggestions.js").read_text(encoding="utf-8")
    assert "from '../format.js'" in js, (
        "suggestions.js must import from format.js instead of defining local escapeHtml"
    )
    assert "function escapeHtml" not in js, (
        "suggestions.js must not define a local escapeHtml (use format.js export)"
    )


def test_suggestions_panel_no_dead_noop_subscription():
    """suggestionsPanel.js must not contain the dead no-op second subscription."""
    js = (STATIC_DIR / "js" / "components" / "suggestionsPanel.js").read_text(encoding="utf-8")
    # The old dead no-op had a comment about "If panel is open, re-render already handled"
    assert "re-render already handled; if closed, counts updated" not in js, (
        "suggestionsPanel.js must not contain the dead no-op subscription comment"
    )


def test_suggestions_panel_has_updating_guard():
    """suggestionsPanel.js must have _updating guard flag to prevent double-fetch loops."""
    js = (STATIC_DIR / "js" / "components" / "suggestionsPanel.js").read_text(encoding="utf-8")
    assert "_updating" in js, (
        "suggestionsPanel.js must use _updating flag to guard SSE-driven refetch"
    )


# ---------------------------------------------------------------------------
# W3-F2: Home view
# ---------------------------------------------------------------------------

def test_home_view_not_stub():
    """views/home.js must not be the F1 stub (must reference nextAction.js)."""
    home_js = (STATIC_DIR / "js" / "views" / "home.js").read_text(encoding="utf-8")
    assert "nextAction" in home_js, "home.js must reference nextAction.js"
    assert "stub-view" not in home_js, "home.js must not be the stub"


def test_next_action_js_exists():
    """js/nextAction.js must exist (W3-F2 pure helper)."""
    assert (STATIC_DIR / "js" / "nextAction.js").exists(), \
        "Missing js/nextAction.js"


def test_journey_helpers_js_exists():
    """js/journeyHelpers.js must exist (W3-F2 pure helper)."""
    assert (STATIC_DIR / "js" / "journeyHelpers.js").exists(), \
        "Missing js/journeyHelpers.js"


def test_onboarding_js_exists():
    """js/components/onboarding.js must exist (W3-F2 onboarding component)."""
    assert (STATIC_DIR / "js" / "components" / "onboarding.js").exists(), \
        "Missing js/components/onboarding.js"


def test_api_js_has_get_journey():
    """api.js must export getJourney (W3-F2)."""
    api_js = (STATIC_DIR / "js" / "api.js").read_text(encoding="utf-8")
    assert "getJourney" in api_js, "api.js must export getJourney"


def test_store_js_has_journey_field_and_setter():
    """store.js must have journey field in _state and export setJourney (W3-F2)."""
    store_js = (STATIC_DIR / "js" / "store.js").read_text(encoding="utf-8")
    assert "journey:" in store_js, "store.js must have journey: field in _state"
    assert "export function setJourney" in store_js, "store.js must export setJourney"


def test_reducer_handles_draft_version_added():
    """reducer.js must handle draft_version_added event -> ['journey'] (W3-F2)."""
    reducer_js = (STATIC_DIR / "js" / "reducer.js").read_text(encoding="utf-8")
    assert "draft_version_added" in reducer_js, \
        "reducer.js must handle draft_version_added event"


def test_home_test_file_exists():
    """tests/js/home.test.mjs must exist (W3-F2 node tests)."""
    assert (REPO_ROOT / "tests" / "js" / "home.test.mjs").exists(), \
        "Missing tests/js/home.test.mjs"


def test_lab_css_has_home_view_styles():
    """lab.css must include W3-F2 home view styles."""
    css = (STATIC_DIR / "css" / "lab.css").read_text(encoding="utf-8")
    for needle in (".home-view", ".home-hero", ".home-nba-strip", ".home-nba-card",
                   ".home-journey-list", ".home-onboarding"):
        assert needle in css, f"lab.css missing W3-F2 style: {needle}"


def test_home_view_escapes_server_strings():
    """home.js must use escapeHtml for server strings (titles, event details)."""
    home_js = (STATIC_DIR / "js" / "views" / "home.js").read_text(encoding="utf-8")
    assert "escapeHtml" in home_js, "home.js must use escapeHtml"


def test_home_js_suggestion_source_label_has_no_section_glyph():
    """home.js suggestion source-label fallback must not use the § glyph."""
    home_js = (STATIC_DIR / "js" / "views" / "home.js").read_text(encoding="utf-8")
    assert "§" not in home_js, "home.js must not contain the § glyph"
    assert "src.label || (src.section_id ? `${src.section_id}` : '')" in home_js, (
        "home.js source-label fallback must render the bare section_id"
    )


def test_home_view_has_quicknav_and_product_pillars():
    """home.js must render the quick-nav row (from homeNavModel) and the
    empty-state product pillars, plus the one-time entrance class and a
    normalized sparkline path (home-redesign Task 2)."""
    js = (STATIC_DIR / "js" / "views" / "home.js").read_text(encoding="utf-8")
    # quick-nav driven by the pure model
    assert "homeNavModel" in js, "home must render the quick-nav model"
    assert "home-nav-row" in js and "home-nav-card" in js
    # empty-state product pillars + real CTAs
    assert "home-pillars" in js, "empty state must show product value pillars"
    assert "home-hero-draft" in js and "home-hero-folder" in js
    # one-time entrance class + sparkline normalized for the draw-in animation
    assert "home-animate-in" in js
    assert 'pathLength="1"' in js


def test_next_action_js_exports_select_next_actions():
    """nextAction.js must export selectNextActions."""
    js = (STATIC_DIR / "js" / "nextAction.js").read_text(encoding="utf-8")
    assert "export function selectNextActions" in js, \
        "nextAction.js must export selectNextActions"


def test_journey_helpers_exports_three_functions():
    """journeyHelpers.js must export mergeJourney, sparklinePath, severityDonut."""
    js = (STATIC_DIR / "js" / "journeyHelpers.js").read_text(encoding="utf-8")
    assert "export function mergeJourney" in js, "journeyHelpers.js must export mergeJourney"
    assert "export function sparklinePath" in js, "journeyHelpers.js must export sparklinePath"
    assert "export function severityDonut" in js, "journeyHelpers.js must export severityDonut"


# ---------------------------------------------------------------------------
# W3-F4: Converse UI tests
# ---------------------------------------------------------------------------

def test_answer_html_js_exists():
    """js/answerHtml.js must exist (W3-F4 shared renderer)."""
    assert (STATIC_DIR / "js" / "answerHtml.js").exists(), \
        "Missing js/answerHtml.js"


def test_answer_html_js_exports_render_answer_html():
    """answerHtml.js must export renderAnswerHtml with escapeHtml-first security."""
    js = (STATIC_DIR / "js" / "answerHtml.js").read_text(encoding="utf-8")
    assert "export function renderAnswerHtml" in js, \
        "answerHtml.js must export renderAnswerHtml"
    assert re.search(r"escapeHtml\(\s*answer", js), \
        "answerHtml.js renderAnswerHtml must pass answer through escapeHtml FIRST"


def test_cite_mini_card_js_exists():
    """js/components/citeMiniCard.js must exist (W3-F4 shared cite handlers)."""
    assert (STATIC_DIR / "js" / "components" / "citeMiniCard.js").exists(), \
        "Missing js/components/citeMiniCard.js"


def test_cite_mini_card_exports_attach_cite_handlers():
    """citeMiniCard.js must export attachCiteHandlers."""
    js = (STATIC_DIR / "js" / "components" / "citeMiniCard.js").read_text(encoding="utf-8")
    assert "export function attachCiteHandlers" in js, \
        "citeMiniCard.js must export attachCiteHandlers"
    assert "escapeHtml" in js, "citeMiniCard.js must escapeHtml citation fields"


def test_converse_panel_js_exists():
    """js/components/conversePanel.js must exist (W3-F4 FAB + panel)."""
    assert (STATIC_DIR / "js" / "components" / "conversePanel.js").exists(), \
        "Missing js/components/conversePanel.js"


def test_converse_panel_exports_mount_and_pure_helpers():
    """conversePanel.js must export mountConversePanel, deriveContext, nextThreadState."""
    js = (STATIC_DIR / "js" / "components" / "conversePanel.js").read_text(encoding="utf-8")
    assert "export function mountConversePanel" in js, \
        "conversePanel.js must export mountConversePanel"
    assert "export function deriveContext" in js, \
        "conversePanel.js must export deriveContext"
    assert "export function nextThreadState" in js, \
        "conversePanel.js must export nextThreadState"
    assert "export function threadKey" in js, \
        "conversePanel.js must export threadKey"


def test_converse_panel_escapes_user_text():
    """conversePanel.js must escapeHtml user-entered text in bubbles."""
    js = (STATIC_DIR / "js" / "components" / "conversePanel.js").read_text(encoding="utf-8")
    assert "escapeHtml" in js, "conversePanel.js must use escapeHtml"


def test_ask_js_re_exports_from_answer_html():
    """ask.js must re-export renderAnswerHtml from answerHtml.js (W3-F4 extraction)."""
    ask_js = (STATIC_DIR / "js" / "views" / "ask.js").read_text(encoding="utf-8")
    assert "answerHtml.js" in ask_js, \
        "ask.js must reference answerHtml.js (re-export after W3-F4 extraction)"


def test_api_js_has_converse_endpoints():
    """api.js must export converse and getConversation (W3-F4)."""
    api_js = (STATIC_DIR / "js" / "api.js").read_text(encoding="utf-8")
    assert "export const converse" in api_js, "api.js must export converse"
    assert "export const getConversation" in api_js, "api.js must export getConversation"


def test_store_js_has_conversations_field():
    """store.js must reference conversations Map (W3-F4 thread store)."""
    store_js = (STATIC_DIR / "js" / "store.js").read_text(encoding="utf-8")
    assert "conversations" in store_js, \
        "store.js must reference conversations (W3-F4 thread store)"


def test_main_js_mounts_converse_panel():
    """main.js must import and mount conversePanel (W3-F4)."""
    main_js = (STATIC_DIR / "js" / "main.js").read_text(encoding="utf-8")
    assert "conversePanel" in main_js, "main.js must reference conversePanel"
    assert "mountConversePanel" in main_js, "main.js must call mountConversePanel"


# ---------------------------------------------------------------------------
# home-redesign task 4: Researches header persistent "+ New research" button
# ---------------------------------------------------------------------------

def test_researches_header_has_persistent_new_research_button():
    """researches.js header must carry a persistent #ws-new-btn that reveals
    the (now hidden-by-default) #ws-create-row create control (home-redesign
    task 4)."""
    js = (STATIC_DIR / "js" / "views" / "researches.js").read_text(encoding="utf-8")
    assert "ws-new-btn" in js, "header must carry a persistent + New research button"
    assert "New research" in js
    # the create row is now hidden by default (revealed by the header button)
    assert "ws-create-row" in js and "hidden" in js
    # header shows a count of researches
    assert "researches-header" in js


def test_lab_css_has_converse_styles():
    """lab.css must include W3-F4 converse panel styles."""
    css = (STATIC_DIR / "css" / "lab.css").read_text(encoding="utf-8")
    for needle in (".converse-fab", ".converse-panel", ".converse-bubble",
                   ".converse-header", ".converse-shimmer"):
        assert needle in css, f"lab.css missing W3-F4 style: {needle}"


def test_lab_css_dock_right_offset():
    """lab.css must set #dock right:76px so dock and FAB never overlap (W3-F4)."""
    css = (STATIC_DIR / "css" / "lab.css").read_text(encoding="utf-8")
    assert "right: 76px" in css, \
        "lab.css must set right:76px on #dock to avoid FAB overlap"


def test_converse_node_test_file_exists():
    """tests/js/converse.test.mjs must exist (W3-F4 pure-function tests)."""
    assert (REPO_ROOT / "tests" / "js" / "converse.test.mjs").exists(), \
        "Missing tests/js/converse.test.mjs"


@pytest.mark.skipif(not _FASTAPI_AVAILABLE, reason="fastapi not installed")
def test_get_static_converse_panel_js_returns_200(lab_client):
    """GET /static/js/components/conversePanel.js must return 200."""
    res = lab_client.get("/static/js/components/conversePanel.js")
    assert res.status_code == 200


@pytest.mark.skipif(not _FASTAPI_AVAILABLE, reason="fastapi not installed")
def test_get_static_cite_mini_card_js_returns_200(lab_client):
    """GET /static/js/components/citeMiniCard.js must return 200."""
    res = lab_client.get("/static/js/components/citeMiniCard.js")
    assert res.status_code == 200


@pytest.mark.skipif(not _FASTAPI_AVAILABLE, reason="fastapi not installed")
def test_get_static_answer_html_js_returns_200(lab_client):
    """GET /static/js/answerHtml.js must return 200."""
    res = lab_client.get("/static/js/answerHtml.js")
    assert res.status_code == 200


# ---------------------------------------------------------------------------
# W3-F5: Timeline view
# ---------------------------------------------------------------------------

def test_timeline_layout_js_exists():
    """js/timeline/layout.js must exist (W3-F5 pure geometry module)."""
    assert (STATIC_DIR / "js" / "timeline" / "layout.js").exists(), \
        "Missing js/timeline/layout.js"


def test_timeline_view_not_stub():
    """views/timeline.js must not be the F1 stub (must reference timeline/layout.js)."""
    tl_js = (STATIC_DIR / "js" / "views" / "timeline.js").read_text(encoding="utf-8")
    assert "timeline/layout.js" in tl_js, \
        "timeline.js must import from timeline/layout.js (not the stub)"
    assert "stub-view" not in tl_js, "timeline.js must not be the F1 stub"


def test_timeline_view_escapes_server_strings():
    """views/timeline.js must use escapeHtml for server strings (statements, rationales)."""
    tl_js = (STATIC_DIR / "js" / "views" / "timeline.js").read_text(encoding="utf-8")
    assert "escapeHtml" in tl_js, "timeline.js must use escapeHtml"


def test_timeline_view_dispatches_rc_discuss():
    """views/timeline.js must dispatch CustomEvent('rc:discuss') for gap Discuss button."""
    tl_js = (STATIC_DIR / "js" / "views" / "timeline.js").read_text(encoding="utf-8")
    assert "rc:discuss" in tl_js, "timeline.js must dispatch rc:discuss CustomEvent"


def test_timeline_view_dispatches_rc_open_paper():
    """views/timeline.js must dispatch rc:open-paper for library drawer handoff."""
    tl_js = (STATIC_DIR / "js" / "views" / "timeline.js").read_text(encoding="utf-8")
    assert "rc:open-paper" in tl_js, "timeline.js must dispatch rc:open-paper"
    assert "__rcPendingPaper" in tl_js, "timeline.js must set window.__rcPendingPaper"


def test_api_js_has_temporal_and_gaps_endpoints():
    """api.js must export getTemporal, getGaps, refreshGaps (W3-F5)."""
    api_js = (STATIC_DIR / "js" / "api.js").read_text(encoding="utf-8")
    for name in ("getTemporal", "getGaps", "refreshGaps"):
        assert f"export const {name}" in api_js, f"api.js must export {name}"


def test_store_js_has_gaps_setter():
    """store.js must export setGaps (W3-F5 additive)."""
    store_js = (STATIC_DIR / "js" / "store.js").read_text(encoding="utf-8")
    assert "export function setGaps" in store_js, "store.js must export setGaps"


def test_reducer_handles_gaps_updated():
    """reducer.js must handle gaps_updated event -> ['gaps'] (W3-F5 additive)."""
    reducer_js = (STATIC_DIR / "js" / "reducer.js").read_text(encoding="utf-8")
    assert "gaps_updated" in reducer_js, "reducer.js must handle gaps_updated event"


def test_lab_css_has_timeline_styles():
    """lab.css must include W3-F5 timeline styles."""
    css = (STATIC_DIR / "css" / "lab.css").read_text(encoding="utf-8")
    for needle in (".tl-root", ".tl-gap-diamond", ".tl-dot", ".tl-segment",
                   ".tl-legend", ".tl-detail-panel"):
        assert needle in css, f"lab.css missing W3-F5 style: {needle}"


def test_timeline_layout_test_file_exists():
    """tests/js/timelineLayout.test.mjs must exist (W3-F5 node tests)."""
    assert (REPO_ROOT / "tests" / "js" / "timelineLayout.test.mjs").exists(), \
        "Missing tests/js/timelineLayout.test.mjs"


@pytest.mark.skipif(not _FASTAPI_AVAILABLE, reason="fastapi not installed")
def test_get_static_timeline_view_js_returns_200(lab_client):
    """GET /static/js/views/timeline.js must return 200 (W3-F5)."""
    res = lab_client.get("/static/js/views/timeline.js")
    assert res.status_code == 200


@pytest.mark.skipif(not _FASTAPI_AVAILABLE, reason="fastapi not installed")
def test_get_static_timeline_layout_js_returns_200(lab_client):
    """GET /static/js/timeline/layout.js must return 200 (W3-F5)."""
    res = lab_client.get("/static/js/timeline/layout.js")
    assert res.status_code == 200


def test_ask_js_has_local_render_answer_import():
    """W3-F4 HIGH regression: a bare `export {X} from` creates no local binding;
    ask.js must locally import renderAnswerHtml for its own render path."""
    src = (STATIC_DIR / "js" / "views" / "ask.js").read_text(encoding="utf-8")
    assert "import { renderAnswerHtml } from '../answerHtml.js'" in src


# ---------------------------------------------------------------------------
# W3-F5 blocker fixes (commit f48bc4d review)
# ---------------------------------------------------------------------------

def test_timeline_view_uses_relx_coordinate_helper():
    """timeline.js must define _relX and apply it to every rendered x so that
    canvas-inner positions are relative to the scrollable strip (not full-width).
    This fixes the rightmost-years clipping bug (CRITICAL-1)."""
    tl_js = (STATIC_DIR / "js" / "views" / "timeline.js").read_text(encoding="utf-8")
    assert "_relX" in tl_js, (
        "timeline.js must define _relX helper to subtract labelWidth from layout x coords"
    )
    # The inner-width must be totalW - labelWidth (not totalW)
    assert "totalW - OPTS.labelWidth" in tl_js or "innerW" in tl_js, (
        "timeline.js canvas-inner width must be totalW - labelWidth (innerW)"
    )


def test_timeline_view_subscribes_to_gaps_topic():
    """timeline.js mount() must subscribe to the 'gaps' store topic and refetch
    api.getGaps() so gaps_updated SSE events trigger a re-render (HIGH-2)."""
    tl_js = (STATIC_DIR / "js" / "views" / "timeline.js").read_text(encoding="utf-8")
    assert "'gaps'" in tl_js, (
        "timeline.js must subscribe to the 'gaps' store topic"
    )
    assert "api.getGaps()" in tl_js, (
        "timeline.js gaps subscriber must call api.getGaps() to refetch"
    )


def test_timeline_view_year_header_outside_canvas_inner():
    """timeline.js must render the year header strip OUTSIDE tl-canvas-inner so
    that it can be scroll-synced without fighting overflow (MEDIUM-3).
    The year header must NOT use position:sticky inline style."""
    tl_js = (STATIC_DIR / "js" / "views" / "timeline.js").read_text(encoding="utf-8")
    assert "tl-year-strip" in tl_js, (
        "timeline.js must use a .tl-year-strip sibling element outside tl-canvas-inner"
    )
    # The old position:sticky should be gone from the year header
    assert "position:sticky" not in tl_js, (
        "timeline.js year header must not use position:sticky (replaced by scroll-sync)"
    )
    # The scroll sync must be wired
    assert "scrollLeft" in tl_js, (
        "timeline.js must sync yearStrip.scrollLeft to canvasWrap.scrollLeft"
    )


def test_timeline_view_requeries_canvas_wrap_after_render():
    """timeline.js _render() must re-query .tl-canvas-wrap after innerHTML rebuild
    so the click-outside-close listener is wired to the live DOM node (LOW-4)."""
    tl_js = (STATIC_DIR / "js" / "views" / "timeline.js").read_text(encoding="utf-8")
    # _render must contain a querySelector for tl-canvas-wrap (not only on mount)
    render_section = tl_js[tl_js.find("function _render()"):]
    assert ".tl-canvas-wrap" in render_section, (
        "timeline.js _render() must re-query .tl-canvas-wrap after innerHTML rebuild"
    )


# ---------------------------------------------------------------------------
# W3-F7: Self-explanatory layer + premium polish
# ---------------------------------------------------------------------------

def test_glossary_js_exists():
    """js/glossary.js must exist (W3-F7 pure glossary)."""
    assert (STATIC_DIR / "js" / "glossary.js").exists(), \
        "Missing js/glossary.js"


def test_glossary_js_exports_tip_and_glossary():
    """glossary.js must export tip() and GLOSSARY."""
    js = (STATIC_DIR / "js" / "glossary.js").read_text(encoding="utf-8")
    assert "export function tip" in js, "glossary.js must export tip()"
    assert "export const GLOSSARY" in js, "glossary.js must export GLOSSARY"


def test_explainer_js_exists():
    """js/components/explainer.js must exist (W3-F7)."""
    assert (STATIC_DIR / "js" / "components" / "explainer.js").exists(), \
        "Missing js/components/explainer.js"


def test_explainer_js_exports_explainer_banner():
    """explainer.js must export explainerBanner."""
    js = (STATIC_DIR / "js" / "components" / "explainer.js").read_text(encoding="utf-8")
    assert "export function explainerBanner" in js, \
        "explainer.js must export explainerBanner"


def test_help_panel_js_exists():
    """js/components/helpPanel.js must exist (W3-F7)."""
    assert (STATIC_DIR / "js" / "components" / "helpPanel.js").exists(), \
        "Missing js/components/helpPanel.js"


def test_help_panel_imports_glossary():
    """helpPanel.js must import from glossary.js (single source of truth for glossary table)."""
    js = (STATIC_DIR / "js" / "components" / "helpPanel.js").read_text(encoding="utf-8")
    assert "glossary.js" in js, "helpPanel.js must import from glossary.js"


def test_lab_css_has_data_tip_rule():
    """lab.css must include [data-tip] tooltip CSS (W3-F7)."""
    css = (STATIC_DIR / "css" / "lab.css").read_text(encoding="utf-8")
    assert "[data-tip]" in css, "lab.css must have [data-tip] CSS rule"
    assert "attr(data-tip)" in css, "lab.css [data-tip]::after must use content: attr(data-tip)"
    assert '[data-tip-pos="right"]' in css or "[data-tip-pos='right']" in css, \
        'lab.css must have [data-tip-pos="right"] variant'


def test_ask_js_imports_cite_mini_card():
    """ask.js must use attachCiteHandlers from citeMiniCard.js (F4 leftover)."""
    ask_js = (STATIC_DIR / "js" / "views" / "ask.js").read_text(encoding="utf-8")
    assert "attachCiteHandlers" in ask_js, \
        "ask.js must import/use attachCiteHandlers from citeMiniCard"
    assert "citeMiniCard" in ask_js, \
        "ask.js must reference citeMiniCard module"


def test_lab_css_no_dead_dock_class():
    """lab.css must not contain the dead .dock { right: 76px } class rule (F4 leftover).
    The real rule is on #dock."""
    css = (STATIC_DIR / "css" / "lab.css").read_text(encoding="utf-8")
    import re as _re
    dead_rules = _re.findall(r'\.dock\s*\{\s*right:\s*76px', css)
    assert not dead_rules, \
        "lab.css must not contain dead .dock { right: 76px } class rule (use #dock)"


def test_converse_panel_mirrors_to_store():
    """conversePanel.js must mirror threads into store.getConversations() (F4 leftover)."""
    js = (STATIC_DIR / "js" / "components" / "conversePanel.js").read_text(encoding="utf-8")
    assert "getConversations" in js, \
        "conversePanel.js must call store.getConversations() for write-through"


def test_each_view_has_explainer_call():
    """home, graph, draft, timeline, ask, compare views must import/call explainerBanner (W3-F7)."""
    views_to_check = ['home', 'graph', 'draft', 'timeline', 'ask', 'compare']
    for view_name in views_to_check:
        js = (STATIC_DIR / "js" / "views" / f"{view_name}.js").read_text(encoding="utf-8")
        assert "explainerBanner" in js, \
            f"views/{view_name}.js must call explainerBanner (W3-F7)"


def test_main_js_imports_help_panel():
    """main.js must import openHelpPanel from helpPanel.js (W3-F7)."""
    main_js = (STATIC_DIR / "js" / "main.js").read_text(encoding="utf-8")
    assert "helpPanel" in main_js, "main.js must reference helpPanel.js"
    assert "openHelpPanel" in main_js, "main.js must call openHelpPanel"


def test_glossary_node_test_file_exists():
    """tests/js/glossary.test.mjs must exist (W3-F7 node tests)."""
    assert (REPO_ROOT / "tests" / "js" / "glossary.test.mjs").exists(), \
        "Missing tests/js/glossary.test.mjs"


@pytest.mark.skipif(not _FASTAPI_AVAILABLE, reason="fastapi not installed")
def test_get_static_glossary_js_returns_200(lab_client):
    """GET /static/js/glossary.js must return 200 (W3-F7)."""
    res = lab_client.get("/static/js/glossary.js")
    assert res.status_code == 200


@pytest.mark.skipif(not _FASTAPI_AVAILABLE, reason="fastapi not installed")
def test_get_static_explainer_js_returns_200(lab_client):
    """GET /static/js/components/explainer.js must return 200 (W3-F7)."""
    res = lab_client.get("/static/js/components/explainer.js")
    assert res.status_code == 200


@pytest.mark.skipif(not _FASTAPI_AVAILABLE, reason="fastapi not installed")
def test_get_static_help_panel_js_returns_200(lab_client):
    """GET /static/js/components/helpPanel.js must return 200 (W3-F7)."""
    res = lab_client.get("/static/js/components/helpPanel.js")
    assert res.status_code == 200


# ---------------------------------------------------------------------------
# W3-F7 drift-guard: glossary tip() wired into badge components
# ---------------------------------------------------------------------------

def test_paper_card_imports_tip_from_glossary():
    """paperCard.js must import tip from glossary.js and call tip() for data-tip attributes (F7 drift-guard)."""
    js = (STATIC_DIR / "js" / "components" / "paperCard.js").read_text(encoding="utf-8")
    assert "from '../glossary.js'" in js, \
        "paperCard.js must import from glossary.js"
    # tip() is interpolated into template literals: ${tip('...')} -> data-tip="..." at runtime
    assert "tip(" in js, \
        "paperCard.js must call tip() to inject data-tip attributes into HTML templates"


def test_suggestions_panel_imports_tip_from_glossary():
    """suggestionsPanel.js must import tip from glossary.js and call tip() for data-tip attributes (F7 drift-guard)."""
    js = (STATIC_DIR / "js" / "components" / "suggestionsPanel.js").read_text(encoding="utf-8")
    assert "from '../glossary.js'" in js, \
        "suggestionsPanel.js must import from glossary.js"
    # tip() is interpolated into template literals: ${tip('...')} -> data-tip="..." at runtime
    assert "tip(" in js, \
        "suggestionsPanel.js must call tip() to inject data-tip attributes into HTML templates"


# ---------------------------------------------------------------------------
# v0.3.1 — Upload PDF tab + draft-first flow drift-guards
# ---------------------------------------------------------------------------

def test_ingest_modal_has_upload_tab():
    """The Add Papers modal must offer the file-picker/drag-drop Upload tab."""
    js = (STATIC_DIR / "js" / "components" / "ingestModal.js").read_text(encoding="utf-8")
    assert 'data-tab="upload"' in js
    assert "ingest-dropzone" in js
    assert 'type="file"' in js
    assert "ingest-draft-checkbox" in js


def test_ingest_modal_default_tab_is_upload():
    """Upload must be the default tab — it's the primary add-your-draft gesture."""
    js = (STATIC_DIR / "js" / "components" / "ingestModal.js").read_text(encoding="utf-8")
    assert "openModal(tab = 'upload'" in js
    assert "_renderModal(activeTab = 'upload'" in js


def test_api_js_exports_upload_paper():
    js = (STATIC_DIR / "js" / "api.js").read_text(encoding="utf-8")
    assert "export async function uploadPaper" in js
    assert "/api/papers/upload" in js


def test_ingest_helpers_export_upload_validation():
    js = (STATIC_DIR / "js" / "components" / "ingestHelpers.js").read_text(encoding="utf-8")
    assert "export function validateUploadFile" in js
    assert "MAX_UPLOAD_BYTES" in js


def test_onboarding_add_draft_opens_upload_tab():
    """The onboarding 'Add your draft' step opens Upload with draft pre-checked."""
    js = (STATIC_DIR / "js" / "components" / "onboarding.js").read_text(encoding="utf-8")
    assert "openIngest('upload', { draft: true })" in js


def test_home_and_next_action_wire_open_ingest_draft():
    home = (STATIC_DIR / "js" / "views" / "home.js").read_text(encoding="utf-8")
    nba = (STATIC_DIR / "js" / "nextAction.js").read_text(encoding="utf-8")
    assert "'open-ingest-draft'" in nba
    assert "open-ingest-draft" in home
    assert "openModal('upload', { draft: true })" in home


def test_lab_css_has_upload_styles():
    css = (STATIC_DIR / "css" / "lab.css").read_text(encoding="utf-8")
    assert ".ingest-dropzone" in css
    assert ".ingest-dropzone.dragover" in css


# ---------------------------------------------------------------------------
# W4-F2: Library list view + status/relation columns
# ---------------------------------------------------------------------------

def test_library_helpers_exports_four_functions():
    """js/libraryHelpers.js must export deriveStatus, dominantRelation, buildRows, sortRows."""
    js = (STATIC_DIR / "js" / "libraryHelpers.js").read_text(encoding="utf-8")
    assert "export function deriveStatus" in js, \
        "libraryHelpers.js must export deriveStatus"
    assert "export function dominantRelation" in js, \
        "libraryHelpers.js must export dominantRelation"
    assert "export function buildRows" in js, \
        "libraryHelpers.js must export buildRows"
    assert "export function sortRows" in js, \
        "libraryHelpers.js must export sortRows"


def test_library_js_has_view_toggle():
    """library.js must persist view mode to localStorage 'rc.libraryView'."""
    lib_js = (STATIC_DIR / "js" / "views" / "library.js").read_text(encoding="utf-8")
    assert "rc.libraryView" in lib_js, \
        "library.js must use localStorage key 'rc.libraryView' for view mode"


def test_library_js_imports_library_helpers():
    """library.js must import from libraryHelpers.js."""
    lib_js = (STATIC_DIR / "js" / "views" / "library.js").read_text(encoding="utf-8")
    assert "libraryHelpers.js" in lib_js, \
        "library.js must import from libraryHelpers.js"


def test_lab_css_has_library_table_styles():
    """lab.css must include W4-F2 library table styles: .lib-table, .lib-view-toggle, .lib-status-pill."""
    css = (STATIC_DIR / "css" / "lab.css").read_text(encoding="utf-8")
    for needle in (".lib-table", ".lib-view-toggle", ".lib-status-pill"):
        assert needle in css, f"lab.css missing W4-F2 style: {needle}"


# ---------------------------------------------------------------------------
# W4-F3: Draft-centric graph mode
# ---------------------------------------------------------------------------

def test_draft_layout_exports_pure_functions():
    """js/graph/draftLayout.js must export the four pure draft-mode helpers."""
    js = (STATIC_DIR / "js" / "graph" / "draftLayout.js").read_text(encoding="utf-8")
    for name in ("buildDraftModel", "layoutDraftEgo",
                 "makeDraftPredicate", "collectPaperEntities"):
        assert f"export function {name}" in js, \
            f"draftLayout.js must export {name}"


def test_draft_layout_reuses_dominant_relation():
    """draftLayout.js must import dominantRelation from libraryHelpers.js
    (single source of truth — no duplicated stance logic)."""
    js = (STATIC_DIR / "js" / "graph" / "draftLayout.js").read_text(encoding="utf-8")
    assert "from '../libraryHelpers.js'" in js, \
        "draftLayout.js must import from ../libraryHelpers.js"
    assert "dominantRelation" in js, \
        "draftLayout.js must reuse dominantRelation (not reimplement it)"


def test_graph_js_has_mode_toggle():
    """views/graph.js must render the segmented mode toggle and persist the
    mode to localStorage 'rc.graphMode' (W4-F3)."""
    graph_js = (STATIC_DIR / "js" / "views" / "graph.js").read_text(encoding="utf-8")
    assert "rc.graphMode" in graph_js, \
        "graph.js must persist the mode under localStorage key 'rc.graphMode'"
    assert "Draft" in graph_js, \
        "graph.js mode toggle must have a Draft segment"
    assert "graph-mode-toggle" in graph_js, \
        "graph.js must render the .graph-mode-toggle element"
    assert "_draftModeActive" in graph_js, \
        "graph.js must guard live deltas with _draftModeActive (saved-view pattern)"


def test_graphview_exports_set_physics_and_override():
    """graph/graphview.js must export setPhysics and setOverridePredicate (W4-F3 additive)."""
    js = (STATIC_DIR / "js" / "graph" / "graphview.js").read_text(encoding="utf-8")
    assert "export function setPhysics" in js, \
        "graphview.js must export setPhysics"
    assert "export function setOverridePredicate" in js, \
        "graphview.js must export setOverridePredicate"


def test_lab_css_has_graph_mode_styles():
    """lab.css must include the W4-F3 segmented mode-toggle styles."""
    css = (STATIC_DIR / "css" / "lab.css").read_text(encoding="utf-8")
    for needle in (".graph-mode-toggle", ".graph-mode-seg",
                   ".graph-mode-toggle.disabled"):
        assert needle in css, f"lab.css missing W4-F3 style: {needle}"


def test_draft_layout_node_test_file_exists():
    """tests/js/draftLayout.test.mjs must exist (W4-F3 node tests)."""
    assert (REPO_ROOT / "tests" / "js" / "draftLayout.test.mjs").exists(), \
        "Missing tests/js/draftLayout.test.mjs"


@pytest.mark.skipif(not _FASTAPI_AVAILABLE, reason="fastapi not installed")
def test_get_static_draft_layout_js_returns_200(lab_client):
    """GET /static/js/graph/draftLayout.js must return 200 (W4-F3)."""
    res = lab_client.get("/static/js/graph/draftLayout.js")
    assert res.status_code == 200


# ---------------------------------------------------------------------------
# W4-F1: Researches overview screen + topbar workspace switcher
# ---------------------------------------------------------------------------

def test_api_js_has_workspace_endpoints():
    """api.js must export getWorkspaces, createWorkspace, patchWorkspace, activateWorkspace (W4-F1)."""
    api_js = (STATIC_DIR / "js" / "api.js").read_text(encoding="utf-8")
    for name in ("getWorkspaces", "createWorkspace", "patchWorkspace", "activateWorkspace"):
        assert f"export const {name}" in api_js, f"api.js must export {name}"


def test_main_js_registers_researches_route():
    """main.js must register the '/researches' route and mount the workspace switcher (W4-F1)."""
    main_js = (STATIC_DIR / "js" / "main.js").read_text(encoding="utf-8")
    assert "'/researches'" in main_js, "main.js must registerRoute('/researches', ...)"
    assert "mountWorkspaceSwitcher" in main_js, "main.js must mount the workspace switcher"
    assert "getWorkspaces" in main_js, "main.js boot must fetch workspaces (non-fatal)"


def test_index_html_has_workspace_switcher():
    """index.html must have the #workspace-switcher topbar button (W4-F1)."""
    html = _index_text()
    assert 'id="workspace-switcher"' in html, \
        'index.html missing <button id="workspace-switcher">'
    # Must sit between the title and the draft chip in the topbar
    title_pos = html.find("topbar-title")
    switcher_pos = html.find('id="workspace-switcher"')
    chip_pos = html.find('id="draft-chip"')
    assert title_pos < switcher_pos < chip_pos, \
        "#workspace-switcher must be between .topbar-title and #draft-chip"


def test_workspace_switcher_reloads_after_activate():
    """workspaceSwitcher.js must reload the page after a successful activate (W4-F1)."""
    js = (STATIC_DIR / "js" / "components" / "workspaceSwitcher.js").read_text(encoding="utf-8")
    assert "activateWorkspace" in js, "workspaceSwitcher.js must call activateWorkspace"
    assert "location.reload" in js, "workspaceSwitcher.js must reload after activate"


def test_researches_view_escapes_names():
    """views/researches.js must escapeHtml all workspace names / draft titles (W4-F1)."""
    js = (STATIC_DIR / "js" / "views" / "researches.js").read_text(encoding="utf-8")
    assert "escapeHtml" in js, "researches.js must use escapeHtml"
    assert "escapeHtml(r.name)" in js, "researches.js must escapeHtml the workspace name"
    assert "escapeHtml(r.draftTitle)" in js, "researches.js must escapeHtml the draft title"
    assert "from '../format.js'" in js, \
        "researches.js must import escapeHtml from format.js (no local duplicate)"


def test_researches_view_reloads_after_activate():
    """views/researches.js must activate + reload when opening another research (W4-F1)."""
    js = (STATIC_DIR / "js" / "views" / "researches.js").read_text(encoding="utf-8")
    assert "activateWorkspace" in js, "researches.js must call activateWorkspace"
    assert "location.reload" in js, "researches.js must reload after activate"


def test_workspace_switcher_escapes_names():
    """workspaceSwitcher.js must escapeHtml workspace names in the button and menu (W4-F1)."""
    js = (STATIC_DIR / "js" / "components" / "workspaceSwitcher.js").read_text(encoding="utf-8")
    assert "escapeHtml" in js, "workspaceSwitcher.js must use escapeHtml"
    assert "from '../format.js'" in js, \
        "workspaceSwitcher.js must import escapeHtml from format.js"


def test_store_js_has_workspaces_field_and_setter():
    """store.js must have workspaces field in _state and export setWorkspaces (W4-F1)."""
    store_js = (STATIC_DIR / "js" / "store.js").read_text(encoding="utf-8")
    assert "workspaces:" in store_js, "store.js must have workspaces: field in _state"
    assert "export function setWorkspaces" in store_js, \
        "store.js must export setWorkspaces"


def test_workspace_helpers_exports_three_functions():
    """workspaceHelpers.js must export splitWorkspaces, validateWorkspaceName, workspaceCardModel."""
    js = (STATIC_DIR / "js" / "workspaceHelpers.js").read_text(encoding="utf-8")
    for name in ("splitWorkspaces", "validateWorkspaceName", "workspaceCardModel"):
        assert f"export function {name}" in js, f"workspaceHelpers.js must export {name}"


def test_lab_css_has_researches_styles():
    """lab.css must include the W4-F1 researches/switcher styles."""
    css = (STATIC_DIR / "css" / "lab.css").read_text(encoding="utf-8")
    for needle in (".ws-switcher", ".ws-menu",
                   ".researches-view", ".ws-archived", ".ws-create-row"):
        assert needle in css, f"lab.css missing W4-F1 style: {needle}"


# ---------------------------------------------------------------------------
# feat/researches-tab (Task 3): sortable tracking table replaces the card grid
# ---------------------------------------------------------------------------

def test_researches_view_renders_table_not_cards():
    """researches.js must render a sortable <table class="researches-table">,
    not the old ws-card grid markup."""
    js = (STATIC_DIR / "js" / "views" / "researches.js").read_text(encoding="utf-8")
    assert "<table" in js, "researches.js must render a <table>"
    assert "researches-table" in js, "researches.js must use the researches-table class"
    assert "ws-card" not in js, "researches.js must not contain leftover ws-card markup"


def test_researches_view_imports_row_model_and_sort():
    """researches.js must import researchRowModel and sortResearchRows from workspaceHelpers.js
    (feat/researches-tab Task 3)."""
    js = (STATIC_DIR / "js" / "views" / "researches.js").read_text(encoding="utf-8")
    assert "researchRowModel" in js, "researches.js must import/use researchRowModel"
    assert "sortResearchRows" in js, "researches.js must import/use sortResearchRows"
    assert "from '../workspaceHelpers.js'" in js, \
        "researches.js must import from workspaceHelpers.js"


def test_researches_view_still_calls_crud_handlers():
    """researches.js must still call the same workspace CRUD endpoints after the
    card -> table rewrite (feat/researches-tab Task 3)."""
    js = (STATIC_DIR / "js" / "views" / "researches.js").read_text(encoding="utf-8")
    for name in ("activateWorkspace", "createWorkspace", "patchWorkspace", "deleteWorkspace"):
        assert f"api.{name}" in js, f"researches.js must still call api.{name}"


def test_researches_view_has_active_row_class():
    """researches.js must apply researches-row--active to the active research's row."""
    js = (STATIC_DIR / "js" / "views" / "researches.js").read_text(encoding="utf-8")
    assert "researches-row--active" in js, \
        "researches.js must apply the researches-row--active class"


def test_researches_view_empty_state_text():
    """researches.js must show the exact empty-state copy when there are no researches."""
    js = (STATIC_DIR / "js" / "views" / "researches.js").read_text(encoding="utf-8")
    assert "No researches yet" in js and "create one to get started" in js, \
        "researches.js must show the exact empty-state text"


def test_lab_css_has_researches_table_styles():
    """lab.css must include the Task 3 tracking-table styles: table container,
    active row, strength mini-bar segments and citation coverage bar."""
    css = (STATIC_DIR / "css" / "lab.css").read_text(encoding="utf-8")
    for needle in (".researches-table", ".researches-table-wrap",
                   ".researches-row--active", ".research-strength-bar",
                   ".research-strength-seg", ".research-cov-bar",
                   ".research-sub-count"):
        assert needle in css, f"lab.css missing Task 3 table style: {needle}"


def test_researches_view_active_rows_pass_explicit_isarchived_boolean():
    """Active-table rows must pass an explicit boolean isArchived to _rowHtml, not
    rely on Array.map's implicit (element, index, array) callback signature.
    `rows.map(_rowHtml)` would silently pass the array INDEX as isArchived —
    falsy for row 0, truthy for every row after it — breaking Open/rename/row-open
    on every active row past the first (regression found in Task 3 re-review)."""
    js = (STATIC_DIR / "js" / "views" / "researches.js").read_text(encoding="utf-8")
    assert "_rowHtml(r, false)" in js, \
        "researches.js must pass an explicit `false` isArchived for active rows"
    assert "rows.map(_rowHtml)" not in js, \
        "researches.js must not pass _rowHtml directly to .map (index leaks into isArchived)"


def test_researches_view_archived_rows_have_no_open_affordance():
    """Archived rows must not offer an Open button or the row-open click/keydown
    binding: api.activateWorkspace() 409s server-side for an archived workspace id
    (workspaces.py activate_workspace), so any such click is a guaranteed error
    toast (regression found in Task 3 review). The Open button and the
    data-ws-row click-to-open attribute must both be gated on `!isArchived`,
    mirroring how the rename button is already suppressed for archived rows."""
    js = (STATIC_DIR / "js" / "views" / "researches.js").read_text(encoding="utf-8")
    assert "const openBtn = isArchived" in js, \
        "researches.js must gate the Open button on isArchived"
    assert "const rowAttrs = isArchived" in js, \
        "researches.js must gate the data-ws-row click-to-open attribute on isArchived"


def test_workspace_helpers_node_test_file_exists():
    """tests/js/workspaceHelpers.test.mjs must exist (W4-F1 node tests)."""
    assert (REPO_ROOT / "tests" / "js" / "workspaceHelpers.test.mjs").exists(), \
        "Missing tests/js/workspaceHelpers.test.mjs"


@pytest.mark.skipif(not _FASTAPI_AVAILABLE, reason="fastapi not installed")
def test_get_static_researches_view_js_returns_200(lab_client):
    """GET /static/js/views/researches.js must return 200 (W4-F1)."""
    res = lab_client.get("/static/js/views/researches.js")
    assert res.status_code == 200


@pytest.mark.skipif(not _FASTAPI_AVAILABLE, reason="fastapi not installed")
def test_get_static_workspace_switcher_js_returns_200(lab_client):
    """GET /static/js/components/workspaceSwitcher.js must return 200 (W4-F1)."""
    res = lab_client.get("/static/js/components/workspaceSwitcher.js")
    assert res.status_code == 200


def test_sse_reloads_on_workspace_changed():
    """A second tab must fully reload when another tab switches research —
    its whole store belongs to the old workspace (v0.4 final-review fix)."""
    js = (STATIC_DIR / "js" / "sse.js").read_text(encoding="utf-8")
    assert "workspace_changed" in js
    assert "location.reload" in js


def test_graph_draft_mode_exits_saved_view_first():
    js = (STATIC_DIR / "js" / "views" / "graph.js").read_text(encoding="utf-8")
    assert "_restoreLive()" in js.split("function _setMode")[1].split("function ")[0]


# ---------------------------------------------------------------------------
# W5-C3: Citation Coverage UI — drift-guards
# ---------------------------------------------------------------------------

def test_index_html_has_citations_banner():
    """index.html must have the #citations-banner element (W5-C3)."""
    html = _index_text()
    assert 'id="citations-banner"' in html, 'index.html missing #citations-banner'
    assert 'id="citations-banner-text"' in html, 'index.html missing #citations-banner-text'
    assert 'id="citations-banner-link"' in html, 'index.html missing #citations-banner-link'
    assert 'id="citations-banner-collapse"' in html, 'index.html missing #citations-banner-collapse'


def test_main_js_references_citations_banner_and_mounts_panel():
    """main.js must reference citations-banner and mount citationsPanel (W5-C3)."""
    main_js = (STATIC_DIR / "js" / "main.js").read_text(encoding="utf-8")
    assert "citations-banner" in main_js, "main.js must reference citations-banner"
    assert "citationsPanel" in main_js, "main.js must reference citationsPanel"
    assert "mountCitationsPanel" in main_js, "main.js must call mountCitationsPanel"


def test_api_js_exports_citations_endpoints():
    """api.js must export getDraftCitations and resolveCitations (W5-C3)."""
    api_js = (STATIC_DIR / "js" / "api.js").read_text(encoding="utf-8")
    assert "getDraftCitations" in api_js, "api.js must export getDraftCitations"
    assert "resolveCitations" in api_js, "api.js must export resolveCitations"


def test_store_js_has_set_citation_coverage():
    """store.js must export setCitationCoverage (W5-C3)."""
    store_js = (STATIC_DIR / "js" / "store.js").read_text(encoding="utf-8")
    assert "setCitationCoverage" in store_js, "store.js must export setCitationCoverage"


def test_reducer_handles_citation_coverage_updated():
    """reducer.js must handle citation_coverage_updated event (W5-C3)."""
    reducer_js = (STATIC_DIR / "js" / "reducer.js").read_text(encoding="utf-8")
    assert "citation_coverage_updated" in reducer_js, \
        "reducer.js must handle citation_coverage_updated event"


def test_next_action_js_has_add_cited_papers_rule():
    """nextAction.js must have the add-cited-papers rule (W5-C3)."""
    js = (STATIC_DIR / "js" / "nextAction.js").read_text(encoding="utf-8")
    assert "add-cited-papers" in js, "nextAction.js must have add-cited-papers rule"
    assert "open-citations" in js, "nextAction.js add-cited-papers must use open-citations action"


def test_css_has_citations_banner_and_chip_add():
    """lab.css must include #citations-banner and .chip-add styles (W5-C3)."""
    css = (STATIC_DIR / "css" / "lab.css").read_text(encoding="utf-8")
    assert "#citations-banner" in css, "lab.css missing #citations-banner"
    assert ".chip-add" in css, "lab.css missing .chip-add"


def test_citations_helpers_test_file_exists():
    """tests/js/citationsHelpers.test.mjs must exist (W5-C3 node tests)."""
    assert (REPO_ROOT / "tests" / "js" / "citationsHelpers.test.mjs").exists(), \
        "Missing tests/js/citationsHelpers.test.mjs"


def test_settings_view_has_auto_add_citations_toggle():
    """v0.5.1: cited papers download automatically; Settings holds the off-switch."""
    js = (STATIC_DIR / "js" / "views" / "settings.js").read_text(encoding="utf-8")
    assert "auto_add_citations" in js
    assert "s-auto-add-citations" in js


def test_citations_panel_references_auto_mode():
    js = (STATIC_DIR / "js" / "components" / "citationsPanel.js").read_text(encoding="utf-8")
    assert "auto_add_citations" in js
    assert "citations-note-muted" in js


# ---------------------------------------------------------------------------
# W5-ACT: Background-activity indicator — drift-guards
# ---------------------------------------------------------------------------

def test_index_html_has_activity_indicator():
    """index.html must have #activity-indicator (W5-ACT)."""
    html = _index_text()
    assert 'id="activity-indicator"' in html, 'index.html missing #activity-indicator'
    assert 'activity-indicator' in html, 'index.html missing activity-indicator class'


def test_main_js_references_activity_indicator_and_getjobs():
    """main.js must reference activity-indicator and import/call getJobs (W5-ACT)."""
    main_js = (STATIC_DIR / "js" / "main.js").read_text(encoding="utf-8")
    assert "activity-indicator" in main_js, "main.js must reference activity-indicator"
    assert "getJobs" in main_js, "main.js must call getJobs for boot hydration"


def test_reducer_handles_job_started_and_job_finished():
    """reducer.js must handle 'job_started' and 'job_finished' events (W5-ACT)."""
    reducer_js = (STATIC_DIR / "js" / "reducer.js").read_text(encoding="utf-8")
    assert "'job_started'" in reducer_js, "reducer.js must handle job_started"
    assert "'job_finished'" in reducer_js, "reducer.js must handle job_finished"


def test_api_js_exports_get_jobs():
    """api.js must export getJobs (W5-ACT)."""
    api_js = (STATIC_DIR / "js" / "api.js").read_text(encoding="utf-8")
    assert "export const getJobs" in api_js, "api.js must export getJobs"


def test_dock_js_references_active_jobs():
    """progressDock.js must reference activeJobs (W5-ACT background lines)."""
    dock_js = (STATIC_DIR / "js" / "components" / "progressDock.js").read_text(encoding="utf-8")
    assert "activeJobs" in dock_js, "progressDock.js must reference activeJobs"


def test_citations_helpers_has_chip_loading():
    """citationsHelpers.js statusChip must include chip-loading case (W5-ACT)."""
    js = (STATIC_DIR / "js" / "citationsHelpers.js").read_text(encoding="utf-8")
    assert "chip-loading" in js, "citationsHelpers.js must have chip-loading status"


def test_css_has_activity_spin_and_prefers_reduced_motion():
    """lab.css must have .activity-spin and prefers-reduced-motion rule (W5-ACT)."""
    css = (STATIC_DIR / "css" / "lab.css").read_text(encoding="utf-8")
    assert ".activity-spin" in css, "lab.css missing .activity-spin"
    assert "prefers-reduced-motion" in css, "lab.css missing prefers-reduced-motion guard"


def test_reader_js_renders_tab_bar_from_tabstate_tabs():
    """reader.js must render the Original/Simplified/Text tab bar by looping
    over tabState.tabs, not the earlier interim hardcoded Original+Text pair
    gated on model.hasPdf (commit c83ac7b) -- that interim gate is what left
    no-PDF papers with no tab bar at all (no Simplified tab either)."""
    js = (STATIC_DIR / "js" / "components" / "reader.js").read_text(encoding="utf-8")

    assert "tabState.tabs.map(" in js, (
        "reader.js must render the tab bar by mapping over tabState.tabs, not a hardcoded pair"
    )
    assert "hasTabs = tabState.tabs.length > 1" in js, (
        "reader.js must derive hasTabs from tabState.tabs.length, not model.hasPdf"
    )
    # The interim hardcoded Original tab button markup must be gone -- it
    # would mean a literal button in the template rather than one produced
    # by the tabs loop.
    assert 'data-tab="original">Original</button>' not in js, (
        "reader.js must not hardcode the Original tab button; it must come from the tabs loop"
    )
    # The Original pane/button must only ever exist when 'original' is
    # actually one of tabState.tabs (no-PDF papers get no PDF pane at all).
    assert "tabState.tabs.includes('original')" in js, (
        "reader.js must gate the PDF pane on tabState.tabs.includes('original')"
    )


def test_reader_js_has_simplified_tab_wiring():
    """reader.js must wire the Simplified tab: lazy /simplified fetch, the
    exact empty-state and disclaimer copy, and the Simplify further endpoints."""
    js = (STATIC_DIR / "js" / "components" / "reader.js").read_text(encoding="utf-8")
    assert "getSimplified" in js, "reader.js must call api.getSimplified"
    assert "postSimplify" in js, "reader.js must call api.postSimplify"
    assert "simplifiedModel" in js, "reader.js must use simplifiedModel"
    assert "simplifiedDisplayState" in js, "reader.js must use simplifiedDisplayState"
    assert "pollDecision" in js, "reader.js must bound-poll the simplify job via pollDecision"
    assert "hasn't been analyzed yet — run analysis from the Library to get the simplified view." in js, (
        "reader.js must render the exact empty-state copy"
    )
    assert "it may lose nuance; check the Original tab for the real thing." in js, (
        "reader.js must render the exact simplified-note copy"
    )


def test_reader_js_guards_simplified_async_paths_with_generation_token():
    """reader.js must guard every async continuation that can mutate the
    Simplified-tab cache/DOM with a per-open generation token, not just the
    global _open boolean (post-review fix).

    Root cause: the PDF (Original) tab already protects its async
    continuations with an identity check (`_pdfFrame !== iframe`), but the
    Simplified tab's continuations (the no-PDF prefetch in _renderContent,
    the lazy /simplified fetch in _ensureSimplifiedPane, and the Simplify
    further job poll/finalRefresh in _watchSimplifyJob) had no such guard.
    Closing the reader on paper A mid-Simplify-job and opening paper B let
    A's job finish, refetch A's /simplified, pass a bare `if (!_open)`
    check (true, because B is now open), and poison B's cached
    _simplifiedData -- rendered into B's pane and cached, so even a fresh
    tab click on B kept showing A's content.
    """
    js = (STATIC_DIR / "js" / "components" / "reader.js").read_text(encoding="utf-8")

    assert "let _readerGeneration" in js, "reader.js must have a _readerGeneration counter"
    assert "++_readerGeneration" in js, "reader.js must increment _readerGeneration once per open"

    # Must appear in each of: the no-PDF prefetch, the lazy simplified fetch's
    # .then/.catch, the postSimplify click handler, and the job poll/
    # finalRefresh -- not just once. A regression that drops the guard from
    # any one of those spots reintroduces the poisoning race above.
    guard_uses = re.findall(r"gen !== _readerGeneration\) return", js)
    assert len(guard_uses) >= 8, (
        f"reader.js must gate simplified-tab async continuations on the generation token "
        f"in every continuation (prefetch, lazy fetch x2, click handler x3, poll x2, "
        f"finalRefresh); found only {len(guard_uses)}"
    )


def test_reader_js_gates_regenerate_button_on_provider_configured():
    """The rewrite-view 'Regenerate' button must only render when a provider
    is configured, matching the standalone 'Simplify further' button's
    showButton gate (post-review fix -- it previously rendered unconditionally,
    offering to regenerate with no LLM key present)."""
    js = (STATIC_DIR / "js" / "components" / "reader.js").read_text(encoding="utf-8")
    assert "resp.provider_configured" in js, (
        "reader.js must gate the Regenerate button on resp.provider_configured"
    )


def test_reader_js_bullet_link_only_when_section_exists():
    """A simplified bullet's section reference must only render as a
    clickable link when that section exists in the CURRENT reader sections;
    otherwise it must fall back to a plain, non-clickable label (post-review
    fix -- a link to a missing section id called _setActive with an id
    matching nothing, which cleared every active nav/section highlight)."""
    js = (STATIC_DIR / "js" / "components" / "reader.js").read_text(encoding="utf-8")
    assert "label === undefined" in js, (
        "reader.js must check the section-label lookup for a miss before rendering a link"
    )


def test_api_js_has_simplified_endpoints():
    """api.js must export getSimplified/postSimplify (Task 3)."""
    js = (STATIC_DIR / "js" / "api.js").read_text(encoding="utf-8")
    assert "export const getSimplified" in js, "api.js must export getSimplified"
    assert "export const postSimplify" in js, "api.js must export postSimplify"


def test_lab_css_has_simplified_tab_styles():
    """lab.css must style the Simplified pane and its bullets/button (Task 3)."""
    css = (STATIC_DIR / "css" / "lab.css").read_text(encoding="utf-8")
    for selector in (".reader-simplified-pane", ".simplified-group", ".simplified-bullet",
                     ".simplified-note", ".btn-simplify-further"):
        assert selector in css, f"lab.css missing {selector}"


def test_activity_helpers_test_file_exists():
    """tests/js/activityHelpers.test.mjs must exist (W5-ACT node tests)."""
    assert (REPO_ROOT / "tests" / "js" / "activityHelpers.test.mjs").exists(), \
        "Missing tests/js/activityHelpers.test.mjs"


def test_reader_panes_hidden_attribute_wins_over_display_rules():
    """The reader's three tab panes share one grid cell and are toggled via the
    `hidden` attribute — but `.reader-pdf-pane` sets `display: flex`, which
    outranks the UA's `[hidden] { display: none }`. Without an explicit
    [hidden] override the PDF pane keeps painting behind the Text/Simplified
    tabs (user-visible overlap bug). This pins the guard rule."""
    css = (STATIC_DIR / "css" / "lab.css").read_text(encoding="utf-8")
    assert ".reader-pdf-pane[hidden]" in css, (
        "lab.css must explicitly force display:none for hidden reader panes"
    )


# ---------------------------------------------------------------------------
# feat/sidebar-labels: expanded labeled sidebar; Citations joins main group
# ---------------------------------------------------------------------------

class TestSidebarLabels:
    def _index(self) -> str:
        return (STATIC_DIR / "index.html").read_text(encoding="utf-8")

    def _css(self) -> str:
        return (STATIC_DIR / "css" / "lab.css").read_text(encoding="utf-8")

    def test_every_nav_button_has_a_label(self):
        html = self._index()
        for label in ("Home", "Library", "Graph", "Draft", "Timeline",
                      "Ask", "Compare", "Citations", "Help", "Settings"):
            assert f'<span class="nav-label">{label}</span>' in html, label

    def test_citations_button_sits_after_compare_before_spacer(self):
        html = self._index()
        compare = html.index('data-route="/compare"')
        placement = html.index('id="topbar-placement"')
        spacer = html.index('class="nav-spacer"')
        help_btn = html.index('id="topbar-help"')
        settings = html.index('data-route="/settings"')
        assert compare < placement < spacer < help_btn < settings

    def test_nav_width_expanded_desktop(self):
        """Desktop --nav-width must be exactly 208px (one canonical declaration
        string — no fuzzy/whitespace-tolerant matching)."""
        css = self._css()
        assert "--nav-width:    208px;" in css

    def test_nav_width_and_labels_collapse_on_mobile(self):
        css = self._css()
        mobile = css[css.index("@media (max-width: 640px)"):]
        assert "--nav-width: 56px;" in mobile
        assert ".nav-label" in mobile and "display: none;" in mobile

    def test_tooltip_suppressed_when_labels_visible(self):
        # desktop rule disabling the [title]::after tooltip for nav buttons
        # must appear before the 640px block (where it is deliberately re-armed)
        css = self._css()
        desktop = css.split("@media (max-width: 640px)")[0]
        assert ".nav-btn[title]::after" in desktop
        assert "content: none;" in desktop

    def test_tooltip_rearmed_on_mobile(self):
        css = self._css()
        mobile = css[css.index("@media (max-width: 640px)"):]
        assert ".nav-btn[title]::after" in mobile
        assert "content: attr(title);" in mobile


# ---------------------------------------------------------------------------
# feat/draft-opportunities (Task 3): per-section uncited-paper opportunities
# block + Save note, wired into views/draft.js
# ---------------------------------------------------------------------------

def test_opportunity_helpers_js_exists():
    """js/opportunityHelpers.js must exist (Task 3 pure helpers)."""
    assert (STATIC_DIR / "js" / "opportunityHelpers.js").exists(), \
        "Missing js/opportunityHelpers.js"


def test_opportunity_helpers_exports_two_functions():
    """opportunityHelpers.js must export opportunityModel and noteRowModel."""
    js = (STATIC_DIR / "js" / "opportunityHelpers.js").read_text(encoding="utf-8")
    assert "export function opportunityModel" in js, \
        "opportunityHelpers.js must export opportunityModel"
    assert "export function noteRowModel" in js, \
        "opportunityHelpers.js must export noteRowModel"


def test_opportunity_helpers_test_file_exists():
    """tests/js/opportunityHelpers.test.mjs must exist (Task 3 node tests)."""
    assert (REPO_ROOT / "tests" / "js" / "opportunityHelpers.test.mjs").exists(), \
        "Missing tests/js/opportunityHelpers.test.mjs"


def test_api_js_has_opportunities_and_notes_endpoints():
    """api.js must export getOpportunities/getNotes/saveNote/updateNote/
    deleteNote/exportNotes (Task 3)."""
    api_js = (STATIC_DIR / "js" / "api.js").read_text(encoding="utf-8")
    for name in ("getOpportunities", "getNotes", "saveNote", "updateNote",
                 "deleteNote", "exportNotes"):
        assert f"export const {name}" in api_js, f"api.js must export {name}"


@pytest.mark.skipif(not _FASTAPI_AVAILABLE, reason="fastapi not installed")
def test_get_static_opportunity_helpers_js_returns_200(lab_client):
    """GET /static/js/opportunityHelpers.js must return 200."""
    res = lab_client.get("/static/js/opportunityHelpers.js")
    assert res.status_code == 200


def test_draft_js_imports_opportunity_model_and_calls_get_opportunities():
    """draft.js must import opportunityModel and call api.getOpportunities()."""
    js = (STATIC_DIR / "js" / "views" / "draft.js").read_text(encoding="utf-8")
    assert "opportunityModel" in js, "draft.js must reference opportunityModel"
    assert "getOpportunities" in js, "draft.js must call api.getOpportunities"


def test_draft_js_renders_opportunities_block_markup():
    """draft.js must render the collapsible opportunities block with its
    count label and toggle/row/save-note hooks."""
    js = (STATIC_DIR / "js" / "views" / "draft.js").read_text(encoding="utf-8")
    assert "draft-opp-block" in js, "draft.js must render .draft-opp-block"
    assert "Uncited papers that could help here" in js, (
        "draft.js must render the 'Uncited papers that could help here (n)' label"
    )
    assert "draft-opp-toggle" in js, "draft.js must render the collapsible toggle button"
    assert "draft-opp-save-btn" in js, "draft.js must render the Save note button"


def test_draft_js_opportunities_block_renders_in_detail_column_not_section_list():
    """The full opportunities block (rationale/evidence/Save note) must render
    in _renderDetail (the right-hand draft-detail column) for the currently
    selected section, NOT inside _renderSectionList's per-row markup — a
    narrow scannable nav row is the wrong place for that much content. The
    left list may keep only a lightweight "+n" count badge."""
    js = (STATIC_DIR / "js" / "views" / "draft.js").read_text(encoding="utf-8")

    detail_start = js.index("function _renderDetail(")
    detail_body = js[detail_start:js.index("\nfunction _renderAlignCard(")]
    list_start = js.index("function _renderSectionList(")
    list_body = js[list_start:js.index("// Uncited-paper opportunities block")]

    # The full block (toggle button + save button) is built/wired from the
    # detail-column render path.
    assert "_renderOpportunityBlock(opp)" in detail_body, (
        "_renderDetail must render the opportunities block for the selected section"
    )
    assert "_wireOpportunityBlock(detailEl, sections)" in detail_body, (
        "_renderDetail must wire the opportunities block's toggle/quote/save handlers"
    )

    # The left section-list row must NOT embed the full block or its save button —
    # only the lightweight count badge.
    assert "draft-opp-save-btn" not in list_body, (
        "_renderSectionList must not render the Save note button (moved to detail column)"
    )
    assert "_renderOpportunityBlock(" not in list_body, (
        "_renderSectionList must not call _renderOpportunityBlock (moved to detail column)"
    )
    assert "draft-opp-count-badge" in list_body, (
        "_renderSectionList must still render a lightweight '+n' count badge"
    )


def test_draft_js_opportunities_expand_state_persists_per_section():
    """Expand/collapse of the detail-column opportunities block must persist
    across re-renders via the module-level _oppExpandedSections set, keyed by
    section_id (so re-selecting a section restores its expand state)."""
    js = (STATIC_DIR / "js" / "views" / "draft.js").read_text(encoding="utf-8")
    assert "_oppExpandedSections" in js, (
        "draft.js must track expand state in _oppExpandedSections"
    )


def test_draft_js_opportunities_dispatch_rc_open_reader():
    """draft.js opportunity quote click must dispatch rc:open-reader with {paperId, quote}."""
    js = (STATIC_DIR / "js" / "views" / "draft.js").read_text(encoding="utf-8")
    assert "rc:open-reader" in js, "draft.js must dispatch rc:open-reader"
    assert re.search(r"detail:\s*\{\s*paperId:\s*rec\.paperId,\s*quote:\s*rec\.quote", js), (
        "draft.js opportunity quote handler must dispatch {paperId: rec.paperId, quote: rec.quote, ...}"
    )


def test_draft_js_save_note_calls_api_and_toasts():
    """draft.js Save note handler must call api.saveNote(...) and show a
    'Saved to Notes' toast."""
    js = (STATIC_DIR / "js" / "views" / "draft.js").read_text(encoding="utf-8")
    assert "api.saveNote(" in js, "draft.js must call api.saveNote(...)"
    assert "Saved to Notes" in js, "draft.js must toast 'Saved to Notes' after a successful save"


def test_draft_js_escapes_opportunity_title_rationale_and_quote():
    """draft.js opportunity row renderer must escapeHtml every server string
    (title, rationale, quote) before interpolating into markup."""
    js = (STATIC_DIR / "js" / "views" / "draft.js").read_text(encoding="utf-8")
    assert "escapeHtml(s.title" in js, "draft.js must escapeHtml the opportunity title"
    assert "escapeHtml(s.rationale)" in js, "draft.js must escapeHtml the opportunity rationale"
    assert "escapeHtml(s.quote)" in js, "draft.js must escapeHtml the opportunity quote"


def test_lab_css_has_opportunities_block_styles():
    """lab.css must include the Task 3 opportunities-block styles."""
    css = (STATIC_DIR / "css" / "lab.css").read_text(encoding="utf-8")
    for needle in (".draft-opp-block", ".draft-opp-toggle", ".draft-opp-row",
                   ".draft-opp-quote-btn", ".draft-opp-save-btn"):
        assert needle in css, f"lab.css missing Task 3 style: {needle}"


# ---------------------------------------------------------------------------
# feat/draft-opportunities (Task 4): Notes view + sidebar entry
# ---------------------------------------------------------------------------

def test_index_html_has_notes_nav_button_positioned_correctly():
    """index.html must have a Notes nav button with data-route="/notes" and a
    labeled span, placed after #topbar-placement (Citations) and before
    .nav-spacer."""
    html = _index_text()
    assert 'data-route="/notes"' in html, 'index.html missing Notes nav button data-route="/notes"'
    assert '<span class="nav-label">Notes</span>' in html, (
        'index.html missing Notes nav-label span'
    )
    placement_pos = html.find('id="topbar-placement"')
    notes_pos = html.find('data-route="/notes"')
    spacer_pos = html.find('nav-spacer')
    assert placement_pos != -1 and notes_pos != -1 and spacer_pos != -1, (
        "index.html missing one of #topbar-placement / Notes button / nav-spacer"
    )
    assert placement_pos < notes_pos < spacer_pos, (
        "Notes nav button must be positioned after #topbar-placement and before .nav-spacer"
    )


def test_main_js_imports_notes_view_and_registers_route():
    """main.js must import views/notes.js and register the /notes route."""
    main_js = (STATIC_DIR / "js" / "main.js").read_text(encoding="utf-8")
    assert "notesView" in main_js, "main.js must reference notesView"
    assert "./views/notes.js" in main_js, "main.js must import from './views/notes.js'"
    assert "registerRoute('/notes'" in main_js, "main.js must call registerRoute('/notes', notesView)"


def test_notes_view_js_exists():
    """js/views/notes.js must exist (Task 4)."""
    assert (STATIC_DIR / "js" / "views" / "notes.js").exists(), \
        "Missing js/views/notes.js"


def test_notes_view_uses_escape_html_and_calls_notes_endpoints():
    """views/notes.js must escape server strings and call getNotes/updateNote/
    deleteNote/exportNotes (Task 4)."""
    js = (STATIC_DIR / "js" / "views" / "notes.js").read_text(encoding="utf-8")
    assert "escapeHtml" in js, "notes.js must use escapeHtml"
    for name in ("getNotes", "updateNote", "deleteNote", "exportNotes"):
        assert f"api.{name}(" in js, f"notes.js must call api.{name}(...)"


def test_notes_view_uses_note_row_model():
    """views/notes.js must use noteRowModel from opportunityHelpers.js to
    normalize saved-note fields (Task 4)."""
    js = (STATIC_DIR / "js" / "views" / "notes.js").read_text(encoding="utf-8")
    assert "noteRowModel" in js, "notes.js must reference noteRowModel"
    assert "opportunityHelpers.js" in js, "notes.js must import from opportunityHelpers.js"


def test_notes_view_renders_empty_state():
    """views/notes.js must render the exact empty-state copy."""
    js = (STATIC_DIR / "js" / "views" / "notes.js").read_text(encoding="utf-8")
    assert "No notes yet — save suggestions from the Draft view." in js, (
        "notes.js must render the exact empty-state message"
    )


def test_notes_view_dispatches_rc_open_reader():
    """views/notes.js evidence-quote click must dispatch rc:open-reader with
    {paperId: note.paper_id, quote: note.evidence_quote} (via noteRowModel's
    paperId/quote fields)."""
    js = (STATIC_DIR / "js" / "views" / "notes.js").read_text(encoding="utf-8")
    assert "rc:open-reader" in js, "notes.js must dispatch rc:open-reader"
    assert re.search(r"detail:\s*\{\s*paperId:\s*row\.paperId,\s*quote:\s*row\.quote", js), (
        "notes.js quote handler must dispatch {paperId: row.paperId, quote: row.quote}"
    )


def test_notes_view_exports_markdown_via_blob_download():
    """views/notes.js Export button must build a Blob + anchor download named
    revision-notes.md from exportNotes()'s {markdown} payload."""
    js = (STATIC_DIR / "js" / "views" / "notes.js").read_text(encoding="utf-8")
    assert "new Blob(" in js, "notes.js must construct a Blob for the markdown download"
    assert "revision-notes.md" in js, "notes.js must download the file as revision-notes.md"


def test_notes_view_has_status_and_delete_controls():
    """views/notes.js must wire Mark done / Dismiss / Reopen / Delete controls."""
    js = (STATIC_DIR / "js" / "views" / "notes.js").read_text(encoding="utf-8")
    for needle in ("note-mark-done", "note-dismiss", "note-reopen", "note-delete"):
        assert needle in js, f"notes.js must reference .{needle}"


def test_notes_view_comment_blur_calls_update_note():
    """views/notes.js editable comment must PATCH on blur via api.updateNote."""
    js = (STATIC_DIR / "js" / "views" / "notes.js").read_text(encoding="utf-8")
    assert "addEventListener('blur'" in js, "notes.js must listen for blur on the comment field"
    assert "updateNote(row.id, { comment:" in js, (
        "notes.js must call api.updateNote(row.id, {comment: ...}) on comment blur"
    )


def test_notes_view_exports_mount_and_unmount():
    """views/notes.js must export mount and unmount (router contract)."""
    js = (STATIC_DIR / "js" / "views" / "notes.js").read_text(encoding="utf-8")
    assert "export function mount" in js, "notes.js must export mount"
    assert "export function unmount" in js, "notes.js must export unmount"


@pytest.mark.skipif(not _FASTAPI_AVAILABLE, reason="fastapi not installed")
def test_get_static_notes_view_js_returns_200(lab_client):
    """GET /static/js/views/notes.js must return 200."""
    res = lab_client.get("/static/js/views/notes.js")
    assert res.status_code == 200


def test_lab_css_has_notes_view_styles():
    """lab.css must include the Task 4 Notes-view styles."""
    css = (STATIC_DIR / "css" / "lab.css").read_text(encoding="utf-8")
    for needle in (".notes-view", ".notes-group", ".note-card", ".note-badge",
                   ".note-actions", ".note-comment"):
        assert needle in css, f"lab.css missing Task 4 style: {needle}"


# ---------------------------------------------------------------------------
# feat/notes-everywhere (Task 3): Save-note wired into draft.js (alignment
# cards + freeform section notes), reader.js, paperCard.js, ask.js; uncited
# opportunities block expanded by default.
# ---------------------------------------------------------------------------

def test_draft_js_alignment_card_save_note_uses_build_note_record():
    """draft.js's cited-alignment card Save-note button must call
    buildNoteRecord('alignment', {...}) with paper/section/relation/
    relevance/rationale/quote, then api.saveNote(...) + toast."""
    js = (STATIC_DIR / "js" / "views" / "draft.js").read_text(encoding="utf-8")
    assert "from '../noteRecord.js'" in js, "draft.js must import buildNoteRecord from noteRecord.js"
    assert "buildNoteRecord('alignment'" in js, (
        "draft.js must call buildNoteRecord('alignment', ...) for the cited-alignment Save-note button"
    )
    assert "draft-align-save-btn" in js, "draft.js must render the .draft-align-save-btn button"
    assert "_alignRegistry" in js, (
        "draft.js must keep alignment note fields out-of-band in _alignRegistry (mirrors _evidenceQuotes/_oppRegistry)"
    )


def test_draft_js_alignment_save_note_data_keys_match_kind():
    """The alignment Save-note record must carry paperId/paperTitle/sectionId/
    sectionTitle/relation/relevance/rationale/quote — the fields buildNoteRecord
    maps for kind 'alignment' — and nothing foreign to that surface (no
    sourceExcerpt/comment, which belong to other kinds)."""
    js = (STATIC_DIR / "js" / "views" / "draft.js").read_text(encoding="utf-8")
    start = js.index("buildNoteRecord('alignment'")
    call_src = js[start:js.index(")", js.index("}", start)) + 1]
    for key in ("paperId:", "paperTitle:", "sectionId:", "sectionTitle:",
                "relation:", "relevance:", "rationale:", "quote:"):
        assert key in call_src, f"alignment buildNoteRecord call missing {key}"
    for foreign_key in ("sourceExcerpt:", "comment:"):
        assert foreign_key not in call_src, (
            f"alignment buildNoteRecord call must not pass {foreign_key} (belongs to another kind)"
        )


def test_draft_js_freeform_section_note_uses_build_note_record():
    """draft.js's per-section "+ note" affordance must call
    buildNoteRecord('freeform', { sectionId, sectionTitle, comment })."""
    js = (STATIC_DIR / "js" / "views" / "draft.js").read_text(encoding="utf-8")
    assert "draft-note-btn" in js, "draft.js must render the .draft-note-btn (+ note) button"
    assert "draft-note-form" in js, "draft.js must render the inline .draft-note-form"
    assert re.search(
        r"buildNoteRecord\('freeform',\s*\{\s*sectionId,\s*sectionTitle,\s*comment\s*\}\)",
        js,
    ), "draft.js must call buildNoteRecord('freeform', { sectionId, sectionTitle, comment })"


def test_draft_js_opportunities_expanded_by_default():
    """The uncited-opportunities block must default to EXPANDED on first
    render: draft.js must seed _oppExpandedSections (via .add(...)) from the
    loaded opportunities BEFORE any user toggle, rather than starting fully
    collapsed with no seeding at all."""
    js = (STATIC_DIR / "js" / "views" / "draft.js").read_text(encoding="utf-8")
    assert "_oppExpandedInitialized" in js, (
        "draft.js must track a one-time initialization flag so seeding only happens once"
    )
    render_start = js.index("async function _render(")
    render_body = js[render_start:js.index("\nfunction _renderNoDraft(")]
    assert "_oppExpandedSections.add(" in render_body, (
        "draft.js must seed _oppExpandedSections with opportunity section ids inside _render "
        "(expanded-by-default), not only inside the toggle click handler"
    )


def test_draft_js_opportunities_expand_seed_gated_on_nonempty():
    """Regression (fix round): _oppExpandedInitialized must NOT flip true
    unconditionally on the first _render() — an early render with zero
    opportunities (not yet loaded) must not permanently skip seeding once
    opportunities populate on a later re-render. The flag may only be set
    AFTER confirming at least one section was actually seeded."""
    js = (STATIC_DIR / "js" / "views" / "draft.js").read_text(encoding="utf-8")
    render_start = js.index("async function _render(")
    render_body = js[render_start:js.index("\nfunction _renderNoDraft(")]

    # The buggy pattern: setting the flag true BEFORE (or regardless of)
    # whether the seed loop found anything to add.
    assert not re.search(
        r"if\s*\(!_oppExpandedInitialized\)\s*\{\s*_oppExpandedInitialized\s*=\s*true;",
        render_body,
    ), (
        "_oppExpandedInitialized must not be set unconditionally at the top of the "
        "seeding block — it must only be set once a section was actually seeded"
    )
    # The fix: the flag assignment must appear AFTER the seeding loop, gated
    # on having found at least one opportunity section.
    add_idx = render_body.index("_oppExpandedSections.add(")
    initialized_idx = render_body.index("_oppExpandedInitialized = true", add_idx)
    assert initialized_idx > add_idx, (
        "_oppExpandedInitialized = true must be set AFTER the seed loop that calls "
        "_oppExpandedSections.add(...), not before it"
    )


def test_draft_js_opportunity_save_note_uses_build_note_record():
    """Regression (fix round): the PRE-EXISTING uncited-opportunity Save-note
    handler must route through buildNoteRecord('opportunity', {...}) so the
    saved note carries kind:'opportunity' — previously it posted a raw,
    kind-less object that the server silently defaulted to kind:'freeform',
    which would have made Task 4's Opportunity kind-filter never show these
    notes."""
    js = (STATIC_DIR / "js" / "views" / "draft.js").read_text(encoding="utf-8")
    assert "buildNoteRecord('opportunity'" in js, (
        "draft.js must call buildNoteRecord('opportunity', ...) for the uncited-opportunity "
        "Save-note handler (kind must not silently default to freeform)"
    )
    start = js.index("buildNoteRecord('opportunity'")
    call_src = js[start:js.index(")", js.index("}", start)) + 1]
    for key in ("paperId:", "paperTitle:", "sectionId:", "sectionTitle:",
                "relation:", "relevance:", "rationale:", "quote:", "quoteSectionId:"):
        assert key in call_src, f"opportunity buildNoteRecord call missing {key}"

    # The old hand-built, kind-less record shape must be gone from the
    # opportunity Save handler specifically (draft_section_id was the
    # server-field-named key of the pre-fix raw object).
    opp_handler_start = js.index("detailEl.querySelectorAll('.draft-opp-save-btn')")
    opp_handler_body = js[opp_handler_start:js.index("\n  });\n}", opp_handler_start)]
    assert "draft_section_id: rec.sectionId" not in opp_handler_body, (
        "the opportunity Save handler must no longer post the old hand-built, kind-less record"
    )


def test_reader_js_save_note_uses_build_note_record():
    """reader.js header 'Save note' button must call buildNoteRecord('reader',
    {paperId, paperTitle, sourceExcerpt, quote}) then saveNote + toast."""
    js = (STATIC_DIR / "js" / "components" / "reader.js").read_text(encoding="utf-8")
    assert "from '../noteRecord.js'" in js, "reader.js must import buildNoteRecord from noteRecord.js"
    assert "reader-save-note-btn" in js, "reader.js must render the .reader-save-note-btn button"
    assert "buildNoteRecord('reader'" in js, "reader.js must call buildNoteRecord('reader', ...)"
    assert "saveNote(" in js, "reader.js must call (api|_apiRef).saveNote(...)"
    assert "Saved to Notes" in js, "reader.js must toast 'Saved to Notes' after a successful save"


def test_reader_js_save_note_guards_selection_read():
    """reader.js must read the selection inside a try/catch (getSelection can
    throw/be unavailable in some embeds)."""
    js = (STATIC_DIR / "js" / "components" / "reader.js").read_text(encoding="utf-8")
    save_note_start = js.index("function _bindSaveNote(")
    save_note_body = js[save_note_start:js.index("\n// ---", save_note_start) if "\n// ---" in js[save_note_start:] else len(js)]
    assert "getSelection" in save_note_body, "_bindSaveNote must read window.getSelection()"
    assert "try {" in save_note_body and "catch" in save_note_body, (
        "_bindSaveNote must guard the selection read with try/catch"
    )


def test_paper_card_js_save_note_uses_build_note_record():
    """paperCard.js card-actions Save-note button must call
    buildNoteRecord('paper', {paperId, paperTitle}) then saveNote + toast."""
    js = (STATIC_DIR / "js" / "components" / "paperCard.js").read_text(encoding="utf-8")
    assert "from '../noteRecord.js'" in js, "paperCard.js must import buildNoteRecord from noteRecord.js"
    assert "btn-save-note" in js, "paperCard.js must render the .btn-save-note button"
    assert "buildNoteRecord('paper'" in js, "paperCard.js must call buildNoteRecord('paper', ...)"
    assert "api.saveNote(" in js, "paperCard.js must call api.saveNote(...)"
    assert "Saved to Notes" in js, "paperCard.js must toast 'Saved to Notes' after a successful save"


def test_ask_js_save_note_uses_build_note_record():
    """ask.js rendered-answer Save-note button must call buildNoteRecord('ask',
    {sourceExcerpt, paperId?, paperTitle?}), capping the excerpt at a sane
    length (2000 chars)."""
    js = (STATIC_DIR / "js" / "views" / "ask.js").read_text(encoding="utf-8")
    assert "from '../noteRecord.js'" in js, "ask.js must import buildNoteRecord from noteRecord.js"
    assert "ask-save-note-btn" in js, "ask.js must render the .ask-save-note-btn button"
    assert "buildNoteRecord('ask'" in js, "ask.js must call buildNoteRecord('ask', ...)"
    assert "api.saveNote(" in js, "ask.js must call api.saveNote(...)"
    assert re.search(r"\.slice\(0,\s*(ASK_NOTE_EXCERPT_MAX|2000)\)", js), (
        "ask.js must cap the answer excerpt to a sane length (2000 chars)"
    )
    assert "Saved to Notes" in js, "ask.js must toast 'Saved to Notes' after a successful save"


def test_lab_css_has_task3_notes_everywhere_styles():
    """lab.css must include the styles for the four new Save-note surfaces."""
    css = (STATIC_DIR / "css" / "lab.css").read_text(encoding="utf-8")
    for needle in (".draft-note-btn", ".draft-note-form", ".draft-align-save-btn",
                   ".reader-save-note-btn", ".btn-save-note", ".ask-save-note-btn"):
        assert needle in css, f"lab.css missing Task 3 (notes-everywhere) style: {needle}"


# ---------------------------------------------------------------------------
# feat/notes-everywhere (Task 3, fix round): in-flight guard against
# duplicate notes from a rapid double-click on the three kinds (reader/paper/
# ask) whose records carry no draft_section_id, so the server's
# (paper_id, draft_section_id) dedupe can never catch the duplicate.
# ---------------------------------------------------------------------------

def _handler_body(js: str, fn_signature: str) -> str:
    """Slice out a function body by its declaration text, up to the next
    top-level function/section-comment boundary (best-effort, good enough for
    these small single-purpose handlers)."""
    start = js.index(fn_signature)
    rest = js[start:]
    end_markers = ["\n// ---", "\nfunction ", "\nasync function "]
    end_offset = len(rest)
    for marker in end_markers:
        idx = rest.find(marker, 1)  # skip offset 0 (the signature itself may match "\nfunction ")
        if idx != -1:
            end_offset = min(end_offset, idx)
    return rest[:end_offset]


def test_reader_js_save_note_guards_duplicate_clicks():
    """reader.js Save-note handler must disable the button for the duration
    of the async saveNote call and re-enable it in a finally (reader notes
    carry no draft_section_id, so the server can't dedupe a double-click)."""
    js = (STATIC_DIR / "js" / "components" / "reader.js").read_text(encoding="utf-8")
    body = _handler_body(js, "function _bindSaveNote(")
    assert "btn.disabled" in body, "reader.js Save-note handler must guard against re-entrant clicks via btn.disabled"
    assert "finally" in body, "reader.js Save-note handler must re-enable the button in a finally block"


def test_paper_card_js_save_note_guards_duplicate_clicks():
    """paperCard.js Save-note handler must disable the button for the
    duration of the async saveNote call and re-enable it in a finally (paper
    notes carry no draft_section_id, so the server can't dedupe a
    double-click)."""
    js = (STATIC_DIR / "js" / "components" / "paperCard.js").read_text(encoding="utf-8")
    body = _handler_body(js, "saveNoteBtn.addEventListener('click'")
    assert "saveNoteBtn.disabled" in body, (
        "paperCard.js Save-note handler must guard against re-entrant clicks via saveNoteBtn.disabled"
    )
    assert "finally" in body, "paperCard.js Save-note handler must re-enable the button in a finally block"


def test_ask_js_save_note_guards_duplicate_clicks():
    """ask.js Save-note handler must disable the button for the duration of
    the async saveNote call and re-enable it in a finally (ask notes carry no
    draft_section_id, so the server can't dedupe a double-click)."""
    js = (STATIC_DIR / "js" / "views" / "ask.js").read_text(encoding="utf-8")
    body = _handler_body(js, "async function _onSaveNoteClick(")
    assert "btn.disabled" in body, "ask.js Save-note handler must guard against re-entrant clicks via btn.disabled"
    assert "finally" in body, "ask.js Save-note handler must re-enable the button in a finally block"


def test_draft_js_section_note_save_guards_duplicate_clicks():
    """draft.js per-section freeform note Save handler (_toggleSectionNoteForm)
    must disable the Save button for the duration of the async saveNote call
    and re-enable it in a finally — a freeform note carries no paper_id, so
    the server's (paper_id, draft_section_id) dedupe can't catch a rapid
    double-click (final-review finding 4)."""
    js = (STATIC_DIR / "js" / "views" / "draft.js").read_text(encoding="utf-8")
    body = _handler_body(js, "saveBtn.addEventListener('click'")
    assert "saveBtn.disabled" in body, (
        "draft.js section-note Save handler must guard against re-entrant clicks via saveBtn.disabled"
    )
    assert "finally" in body, "draft.js section-note Save handler must re-enable the button in a finally block"


# ---------------------------------------------------------------------------
# feat/notes-everywhere (Task 4): notebook view — group by section/paper,
# kind & status filter chips, New note.
# ---------------------------------------------------------------------------

def test_notes_view_uses_notes_group_model():
    """notes.js must group notes via notesGroupModel(filteredNotes, _groupBy)."""
    js = (STATIC_DIR / "js" / "views" / "notes.js").read_text(encoding="utf-8")
    assert "notesGroupModel" in js, "notes.js must reference notesGroupModel"
    assert "notesGroupModel(" in js, "notes.js must call notesGroupModel(...)"
    # It must be called with a variable, not the raw unfiltered _notes array —
    # the kind/status chips must filter BEFORE grouping.
    assert not re.search(r"notesGroupModel\(\s*_notes\s*,", js), (
        "notesGroupModel must be called with the FILTERED notes list, not raw _notes"
    )


def test_notes_view_has_group_by_toggle():
    """notes.js must render a Section/Paper group-by toggle, defaulting to
    'section'."""
    js = (STATIC_DIR / "js" / "views" / "notes.js").read_text(encoding="utf-8")
    assert "_groupBy" in js, "notes.js must track _groupBy state"
    assert "_groupBy = 'section'" in js, "notes.js must default _groupBy to 'section'"
    assert "data-groupby" in js, "notes.js must render a group-by control with data-groupby"
    assert "'section', 'Section'" in js and "'paper', 'Paper'" in js, (
        "notes.js must render 'Section' and 'Paper' group-by options"
    )


def test_notes_view_has_kind_and_status_filter_chips():
    """notes.js must render kind and status filter chips, mirroring the
    Suggestions panel's chip pattern (filter-chips / chip / chip-active)."""
    js = (STATIC_DIR / "js" / "views" / "notes.js").read_text(encoding="utf-8")
    assert "_kindFilter" in js, "notes.js must track _kindFilter state"
    assert "_statusFilter" in js, "notes.js must track _statusFilter state"
    assert "_kindFilter = 'all'" in js, "notes.js must default _kindFilter to 'all'"
    assert "_statusFilter = 'open'" in js, "notes.js must default _statusFilter to 'open'"
    assert "filter-chips" in js, "notes.js must reuse the filter-chips class"
    assert "chip-active" in js, "notes.js must reuse the chip-active class"
    for kind_label in ("Alignment", "Opportunity", "Reader", "Ask", "Paper", "Free-form"):
        assert kind_label in js, f"notes.js must render the '{kind_label}' kind chip"
    # 'paper' is a first-class note kind (js/noteRecord.js's KINDS) — it must
    # have its own dedicated kind chip, not just show up under "All".
    assert "{ value: 'paper', label: 'Paper' }" in js, (
        "notes.js KIND_CHIPS must include a dedicated {value:'paper', label:'Paper'} chip"
    )


def test_notes_view_has_new_note_button_and_uses_build_note_record():
    """notes.js must render a 'New note' button and save via
    buildNoteRecord('freeform', {...}) -> api.saveNote(...)."""
    js = (STATIC_DIR / "js" / "views" / "notes.js").read_text(encoding="utf-8")
    assert "New note" in js, "notes.js must render a 'New note' button"
    assert "from '../noteRecord.js'" in js, "notes.js must import buildNoteRecord from noteRecord.js"
    assert "buildNoteRecord('freeform'" in js, (
        "notes.js's New-note form must call buildNoteRecord('freeform', ...)"
    )
    assert "api.saveNote(" in js, "notes.js must call api.saveNote(...) to save the new note"


def test_notes_view_new_note_uses_store_papers_for_paper_picker():
    """notes.js's optional paper <select> must be sourced from
    store.getState().papers."""
    js = (STATIC_DIR / "js" / "views" / "notes.js").read_text(encoding="utf-8")
    assert "from '../store.js'" in js, "notes.js must import store.js"
    assert "store.getState()" in js, "notes.js must call store.getState()"
    assert ".papers" in js, "notes.js must reference store.getState().papers for the paper picker"


def test_notes_view_export_passes_group_by_arg():
    """notes.js's Export button must call api.exportNotes(_groupBy), not the
    no-arg form, so the exported markdown grouping matches the on-screen
    group-by toggle."""
    js = (STATIC_DIR / "js" / "views" / "notes.js").read_text(encoding="utf-8")
    assert re.search(r"exportNotes\(\s*_groupBy\s*\)", js), (
        "notes.js Export button must call api.exportNotes(_groupBy)"
    )


def test_notes_view_kind_badge_and_source_excerpt_rendered():
    """notes.js note cards must show a kind badge and escaped source_excerpt
    (via row.sourceExcerpt) when present."""
    js = (STATIC_DIR / "js" / "views" / "notes.js").read_text(encoding="utf-8")
    assert "note-kind-badge" in js, "notes.js must render a .note-kind-badge element"
    assert "sourceExcerpt" in js, "notes.js must reference row.sourceExcerpt"
    assert "escapeHtml(m.sourceExcerpt)" in js, "notes.js must escapeHtml the source excerpt"


def test_notes_view_quote_link_requires_paper_and_quote():
    """notes.js's evidence-quote link must only render when the note has BOTH
    a paper and a quote (an ask/freeform note without a paper must not show a
    dangling 'open in source' link)."""
    js = (STATIC_DIR / "js" / "views" / "notes.js").read_text(encoding="utf-8")
    assert re.search(r"m\.quote\s*&&\s*m\.paperId", js), (
        "notes.js quote-link condition must require both m.quote and m.paperId"
    )


def test_lab_css_has_task4_notebook_styles():
    """lab.css must include the Task 4 notebook-view additions: group-by
    toggle, kind badge, and the New-note form."""
    css = (STATIC_DIR / "css" / "lab.css").read_text(encoding="utf-8")
    for needle in (".notes-groupby-seg", ".notes-groupby-btn", ".note-kind-badge",
                   ".notes-new-note-form", ".notes-new-note-textarea"):
        assert needle in css, f"lab.css missing Task 4 notebook style: {needle}"


# ---------------------------------------------------------------------------
# feat/researches-tab (Task 4): Researches sidebar entry + per-tab hover
# descriptions
# ---------------------------------------------------------------------------

ALL_NAV_LABELS = ("Home", "Researches", "Library", "Graph", "Draft", "Timeline",
                  "Ask", "Compare", "Citations", "Notes", "Help", "Settings")


def test_index_html_has_researches_nav_button_positioned_correctly():
    """index.html must have a Researches nav button with data-route="/researches"
    and a labeled span, placed after Home and before .nav-spacer."""
    html = _index_text()
    assert 'data-route="/researches"' in html, (
        'index.html missing Researches nav button data-route="/researches"'
    )
    assert '<span class="nav-label">Researches</span>' in html, (
        'index.html missing Researches nav-label span'
    )
    home_pos = html.find('data-route="/home"')
    researches_pos = html.find('data-route="/researches"')
    spacer_pos = html.find('nav-spacer')
    assert home_pos != -1 and researches_pos != -1 and spacer_pos != -1, (
        "index.html missing one of Home button / Researches button / nav-spacer"
    )
    assert home_pos < researches_pos < spacer_pos, (
        "Researches nav button must be positioned after Home and before .nav-spacer"
    )


def test_every_nav_button_has_a_data_desc():
    """Every nav-btn (all 12, including Citations/Help which are id-wired
    rather than data-route-wired) must carry a data-desc hover description."""
    html = _index_text()
    for label in ALL_NAV_LABELS:
        label_pos = html.find(f'<span class="nav-label">{label}</span>')
        assert label_pos != -1, f"index.html missing nav-label {label}"
        btn_start = html.rfind('<button', 0, label_pos)
        button_markup = html[btn_start:label_pos]
        assert 'data-desc="' in button_markup, (
            f"{label} nav button is missing a data-desc attribute"
        )


def test_researches_nav_button_has_exact_description_copy():
    """The Researches nav button's data-desc must match the fixed brief copy."""
    html = _index_text()
    assert 'data-desc="track all your research projects at a glance"' in html, (
        "Researches nav button data-desc must read "
        "'track all your research projects at a glance'"
    )


def test_lab_css_has_nav_desc_popover_rule():
    """lab.css must define a hover popover for [data-desc] using
    attr(data-desc), distinct from the plain [title] tooltip."""
    css = (STATIC_DIR / "css" / "lab.css").read_text(encoding="utf-8")
    assert ".nav-btn[data-desc]::before" in css, (
        "lab.css missing the .nav-btn[data-desc]::before popover rule"
    )
    assert "content: attr(data-desc);" in css, (
        "lab.css [data-desc] popover must render content: attr(data-desc)"
    )
    assert ".nav-btn:hover[data-desc]::before" in css, (
        "lab.css missing the :hover state that reveals the [data-desc] popover"
    )


def test_lab_css_nav_desc_popover_suppressed_on_mobile():
    """The [data-desc] popover must be suppressed inside the existing
    640px collapse (icon-only rail falls back to the [title] tooltip)."""
    css = (STATIC_DIR / "css" / "lab.css").read_text(encoding="utf-8")
    assert css.count("@media (max-width: 640px)") == 1, (
        "lab.css must keep a single 640px media query (do not add a second one)"
    )
    mobile = css[css.index("@media (max-width: 640px)"):]
    assert ".nav-btn[data-desc]::before" in mobile, (
        "640px block must reference .nav-btn[data-desc]::before to suppress it"
    )
    assert "content: none;" in mobile, (
        "640px block must set content: none to suppress the [data-desc] popover"
    )


# ---------------------------------------------------------------------------
# feat/no-research-selected: none-state affordance + guarded CTAs
# ---------------------------------------------------------------------------

def test_workspace_switcher_renders_research_none_label():
    """workspaceSwitcher.js must render the visible 'Research: none' state."""
    path = STATIC_DIR / "js" / "components" / "workspaceSwitcher.js"
    text = path.read_text(encoding="utf-8")
    assert "Research: none" in text, \
        "workspaceSwitcher.js must render a visible 'Research: none' state"


def test_home_ctas_route_through_ensure_active_research():
    """home.js's empty-hero CTAs must be guarded by ensureActiveResearch."""
    path = STATIC_DIR / "js" / "views" / "home.js"
    text = path.read_text(encoding="utf-8")
    assert "ensureActiveResearch" in text, \
        "home.js must import/call ensureActiveResearch for its empty-hero CTAs"


def test_topbar_add_routes_through_ensure_active_research():
    """main.js's topbar '+ Add papers' button must be guarded by ensureActiveResearch."""
    path = STATIC_DIR / "js" / "main.js"
    text = path.read_text(encoding="utf-8")
    assert "ensureActiveResearch" in text, \
        "main.js must call ensureActiveResearch for the topbar add-papers button"


def test_researchguard_test_file_exists():
    """tests/js/researchGuard.test.mjs must exist (ensureActiveResearch node tests)."""
    assert (REPO_ROOT / "tests" / "js" / "researchGuard.test.mjs").exists(), \
        "Missing tests/js/researchGuard.test.mjs"


def test_no_literal_main_fallback_remains_in_store_or_workspaces():
    """store.py/workspaces.py must not silently reconstitute a 'main' fallback.

    The only legitimate literal-"main" usages left are _DEFAULT_WORKSPACE
    itself, the legacy pre-0.4 migration's explicit main record, and the
    _migrating-guarded normalization check — none of those are a fallback
    that reconstitutes an active/selected workspace out of thin air.
    """
    store_text = (REPO_ROOT / "research_companion" / "store.py").read_text(encoding="utf-8")
    ws_text = (REPO_ROOT / "research_companion" / "workspaces.py").read_text(encoding="utf-8")
    forbidden_patterns = [
        'or _DEFAULT_WORKSPACE',
        'or "main"',
        "or 'main'",
    ]
    for pattern in forbidden_patterns:
        assert pattern not in store_text, \
            f"store.py must not contain the literal fallback pattern: {pattern!r}"
        assert pattern not in ws_text, \
            f"workspaces.py must not contain the literal fallback pattern: {pattern!r}"
    assert 'any(w.get("id") == "main" for w in others)' not in ws_text, \
        "workspaces.py must not special-case 'main' when picking the new active workspace"


# ---------------------------------------------------------------------------
# feat/gap-analysis-section (Task 4): dedicated Gaps view
# ---------------------------------------------------------------------------

def test_gaps_nav_entry_exists():
    """index.html must have a Gaps nav-rail button (gap-analysis-section)."""
    html = _index_text()
    assert 'data-route="/gaps"' in html, "Missing Gaps nav-rail button (data-route=/gaps)"
    assert 'nav-label">Gaps<' in html, "Gaps nav button must have nav-label 'Gaps'"
    assert 'data-desc="research gaps across your papers, as actionable bullets"' in html, \
        "Gaps nav button missing its data-desc"


def test_gaps_view_registered_in_main_js():
    """main.js must import views/gaps.js and register it at /gaps."""
    main_js = (STATIC_DIR / "js" / "main.js").read_text(encoding="utf-8")
    assert "views/gaps.js" in main_js, "main.js must import from views/gaps.js"
    assert "registerRoute('/gaps'" in main_js, "main.js must registerRoute('/gaps', ...)"


def test_gaps_view_renders_bullet_list_not_diamonds():
    """views/gaps.js must render a themed bullet list (not the timeline diamonds)."""
    gaps_js = (STATIC_DIR / "js" / "views" / "gaps.js").read_text(encoding="utf-8")
    assert "gaps-row" in gaps_js, "gaps.js must render .gaps-row bullet rows"
    assert "tl-gap-diamond" not in gaps_js, "gaps.js must not reuse the timeline diamond markup"


def test_gaps_view_uses_gap_helpers():
    """views/gaps.js must import the pure model from gapHelpers.js."""
    gaps_js = (STATIC_DIR / "js" / "views" / "gaps.js").read_text(encoding="utf-8")
    assert "gapHelpers.js" in gaps_js
    assert "gapThemeRowModel" in gaps_js
    assert "sortGapThemes" in gaps_js
    assert "filterGapThemes" in gaps_js


def test_gaps_view_escapes_server_strings():
    """views/gaps.js must use escapeHtml for server-derived strings."""
    gaps_js = (STATIC_DIR / "js" / "views" / "gaps.js").read_text(encoding="utf-8")
    assert "escapeHtml" in gaps_js


def test_gaps_view_calls_refresh_gaps():
    """views/gaps.js must wire a Refresh button to api.refreshGaps()."""
    gaps_js = (STATIC_DIR / "js" / "views" / "gaps.js").read_text(encoding="utf-8")
    assert "refreshGaps" in gaps_js


def test_gaps_view_subscribes_to_gaps_topic():
    """views/gaps.js must subscribe to the 'gaps' store topic (gaps_updated SSE) and refetch."""
    gaps_js = (STATIC_DIR / "js" / "views" / "gaps.js").read_text(encoding="utf-8")
    assert "'gaps'" in gaps_js
    assert "api.getGaps()" in gaps_js


def test_gap_helpers_test_file_exists():
    """tests/js/gapHelpers.test.mjs must exist (node tests for the pure model)."""
    assert (REPO_ROOT / "tests" / "js" / "gapHelpers.test.mjs").exists(), \
        "Missing tests/js/gapHelpers.test.mjs"


def test_lab_css_has_gaps_styles():
    """lab.css must include the Gaps view styles."""
    css = (STATIC_DIR / "css" / "lab.css").read_text(encoding="utf-8")
    for needle in (".gaps-view", ".gaps-row", ".gaps-status-pill", ".gaps-citation-chip"):
        assert needle in css, f"lab.css missing Gaps style: {needle}"


@pytest.mark.skipif(not _FASTAPI_AVAILABLE, reason="fastapi not installed")
def test_get_static_gaps_view_js_returns_200(lab_client):
    """GET /static/js/views/gaps.js must return 200."""
    res = lab_client.get("/static/js/views/gaps.js")
    assert res.status_code == 200


@pytest.mark.skipif(not _FASTAPI_AVAILABLE, reason="fastapi not installed")
def test_get_static_gap_helpers_js_returns_200(lab_client):
    """GET /static/js/gapHelpers.js must return 200."""
    res = lab_client.get("/static/js/gapHelpers.js")
    assert res.status_code == 200
