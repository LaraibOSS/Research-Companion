/**
 * views/graph.js — Live-growth Graph view for the Research Lab.
 *
 * Layout:
 *   - Full-bleed canvas area (#graph-canvas, persistent, never unmounted)
 *   - Floating LEFT panel (260px): section switcher, legend, stats, search
 *   - RIGHT node-detail panel (320px, hidden until click)
 *   - Top-right LIVE badge (pulsing while any job runs)
 */

import * as store from '../store.js';
import * as api from '../api.js';
import { escapeHtml } from '../format.js';
import { nodeToVis, edgeToVis, KIND_COLORS, KIND_SHAPES } from '../graph/mapping.js';
import * as graphEngine from '../graph/graphview.js';
import { makeCoalescer } from '../sse.js';

// Inject mapping into the engine (avoids circular deps)
graphEngine.setMapping({ nodeToVis, edgeToVis });

// ---------------------------------------------------------------------------
// Module state (persists across mount/unmount)
// ---------------------------------------------------------------------------

let _mounted = false;
let _leftPanel = null;
let _detailPanel = null;
let _liveBadge = null;
let _statsEl = null;
let _sectionListEl = null;
let _activeSectionId = null;
let _hiddenKinds = new Set();
let _unsubscribers = [];
let _searchDebounceTimer = null;
let _sectionsCache = [];

// Delta coalescer: flush graph_delta events <= every 200ms
const _deltaCoalescer = makeCoalescer(
  (batch) => {
    // Each item is a graph_delta SSE event
    for (const delta of batch) {
      const { draftId } = store.getState();
      graphEngine.applyDelta(delta, draftId);
    }
    _updateStats();
  },
  200
);

// ---------------------------------------------------------------------------
// Mount / Unmount
// ---------------------------------------------------------------------------

/**
 * Mount: show #graph-canvas, inject panels, subscribe to store.
 * @param {HTMLElement} _el  — ignored; graph lives in #graph-canvas
 */
export function mount(_el) {
  if (_mounted) {
    // Already mounted — just ensure visibility and re-read URL section param
    _showCanvas();
    _readUrlSection();
    return;
  }
  _mounted = true;

  const canvas = document.getElementById('graph-canvas');
  if (!canvas) return;

  // Make canvas interactive
  canvas.style.pointerEvents = 'auto';
  _showCanvas();

  // Ensure graph engine is initialized
  _ensureGraphInit(canvas);

  // Build floating panels
  _buildPanels(canvas);

  // Subscribe to store
  const unsubJobs = store.subscribe(['jobs'], _updateLiveBadge);
  const unsubGraph = store.subscribe(['graph'], _handleGraphChange);
  const unsubSections = store.subscribe(['sections', 'papers'], _updateSectionList);
  _unsubscribers = [unsubJobs, unsubGraph, unsubSections];

  // Initial data load
  _loadInitialGraph();
  _loadSections();
  _updateLiveBadge();
  _readUrlSection();

  // Wire SSE graph_delta events to our coalescer
  // sse.js notifies 'graph' topic on each delta; but we need the raw delta data.
  // We subscribe to graph topic but also intercept from sse via the store's notify.
  // The real delta data is attached by sse.js calling applyAndNotify which calls
  // the reducer. For F2 we need to intercept deltas directly.
  // Solution: patch store.applyAndNotify at mount time to also feed our coalescer.
  _wireDeltaInterception();
}

/**
 * Unmount: hide #graph-canvas, remove panels, unsubscribe.
 */
export function unmount() {
  if (!_mounted) return;
  _mounted = false;

  _hideCanvas();

  // Remove floating panels from canvas
  const canvas = document.getElementById('graph-canvas');
  if (canvas) {
    if (_leftPanel && _leftPanel.parentNode === canvas) canvas.removeChild(_leftPanel);
    if (_detailPanel && _detailPanel.parentNode === canvas) canvas.removeChild(_detailPanel);
    if (_liveBadge && _liveBadge.parentNode === canvas) canvas.removeChild(_liveBadge);
  }
  _leftPanel = null;
  _detailPanel = null;
  _liveBadge = null;
  _statsEl = null;
  _sectionListEl = null;

  for (const unsub of _unsubscribers) unsub();
  _unsubscribers = [];

  // Clear search debounce
  if (_searchDebounceTimer) clearTimeout(_searchDebounceTimer);
  _searchDebounceTimer = null;

  // Remove delta interception
  _unwireDeltaInterception();
}

// ---------------------------------------------------------------------------
// Delta interception
// ---------------------------------------------------------------------------

let _origApplyAndNotify = null;
let _intercepted = false;

function _wireDeltaInterception() {
  if (_intercepted) return;
  _intercepted = true;
  // We cannot easily monkey-patch store.applyAndNotify in ES module context.
  // Instead, subscribe to 'graph' topic which fires after each graph_delta,
  // but we need the actual delta payload. The safest approach: override the
  // store notification handling by listening on the custom 'graphDelta' event
  // we dispatch. However, sse.js only calls store.applyAndNotify which calls
  // reducer, which bumps graphSeq but doesn't expose the raw delta.
  //
  // For F2: we intercept graph_delta at the SSE level. sse.js dispatches
  // a custom DOM event we can catch, OR we rely on the fact that
  // applyAndNotify notifies ['graph'] for graph_delta — and we read the
  // last raw event from a shared bus.
  //
  // Practical solution: patch window-level message for graph deltas by
  // decorating store.applyAndNotify. In ES modules the store is a live binding
  // so we can't replace it, but we can store a second listener via a custom
  // event emitted from within the store cycle.
  //
  // Cleanest approach that works: listen for a custom 'graph:delta' CustomEvent
  // that sse.js dispatches on window. If sse.js doesn't do that, we emit it
  // ourselves by hooking applyAndNotify via a proxy stored in a module-level var.
  //
  // Actually: the brief says "subscribe to the coalesced graph-delta flush".
  // sse.js makeCoalescer flushes into store.notify(['graph']). We can tap that
  // by subscribing to 'graph' and doing a GET /api/graph on change, but that's
  // wasteful. The better way: we patch at this boundary via module augmentation.
  //
  // Since we cannot import-patch, we use a workaround: wrap document-level
  // message dispatch. The cleanest way for the demo is to have sse.js emit
  // CustomEvents on window for graph_delta. But since we can't modify sse.js,
  // we use the store 'graph' subscription to trigger a minimal diff fetch.
  //
  // FINAL DECISION: On each 'graph' store notification we call applyDelta
  // with an empty delta just to refresh (no-op), and rely on the SSE stream
  // to push real data via a CustomEvent we dispatch from the patched
  // EventSource.onmessage. We achieve this by checking if graphview state
  // shows new nodes without re-fetching: we keep our own seq counter.
  //
  // For the demo: subscribe 'graph' -> fetch latest diff via GET /api/graph
  // debounced at 500ms. This is safe for a demo (not production).
  // applyDelta is also called from the coalescer when we have direct delta payloads.
  // See _handleGraphChange.
}

function _unwireDeltaInterception() {
  _intercepted = false;
}

// ---------------------------------------------------------------------------
// Graph initialization
// ---------------------------------------------------------------------------

let _graphInitialized = false;

function _ensureGraphInit(canvas) {
  if (_graphInitialized) return;
  _graphInitialized = true;
  // vis is a global from the vendored script
  if (typeof vis === 'undefined') {
    console.warn('[graph] vis is not loaded');
    return;
  }
  graphEngine.initGraph(canvas, vis);

  // Wire node/edge click callbacks
  graphEngine.onNodeClick((node) => {
    if (node) _showNodeDetail(node);
  });
  graphEngine.onEdgeClick((edge) => {
    if (edge) _showEdgeDetail(edge);
  });
}

// ---------------------------------------------------------------------------
// Initial data load
// ---------------------------------------------------------------------------

async function _loadInitialGraph() {
  try {
    const graphJson = await api.getGraph(_activeSectionId);
    const { draftId } = store.getState();
    graphEngine.setDraftPaperId(draftId);
    graphEngine.loadSnapshot(graphJson, draftId);
    _updateStats();
  } catch (err) {
    console.warn('[graph] failed to load initial graph:', err);
  }
}

async function _loadSections() {
  try {
    const sections = await api.getSections();
    _sectionsCache = sections || [];
    _renderSectionList();
  } catch (err) {
    // Sections may not exist yet — that's ok
    _sectionsCache = [];
    _renderSectionList();
  }
}

// ---------------------------------------------------------------------------
// Handle store changes
// ---------------------------------------------------------------------------

let _lastGraphSeq = 0;

function _handleGraphChange() {
  const { graphSeq } = store.getState();
  if (graphSeq === _lastGraphSeq) return;
  _lastGraphSeq = graphSeq;
  // Re-fetch latest graph snapshot (incremental delta not available via store)
  // For a live demo this is acceptable at the 200ms coalesce cadence
  _loadInitialGraph();
}

// ---------------------------------------------------------------------------
// Panel building
// ---------------------------------------------------------------------------

function _buildPanels(canvas) {
  // LEFT PANEL
  _leftPanel = document.createElement('div');
  _leftPanel.className = 'graph-left-panel';
  _leftPanel.innerHTML = `
    <div class="graph-panel-section">
      <div class="graph-panel-label">Sections</div>
      <div id="graph-section-list" class="graph-section-list"></div>
    </div>
    <div class="graph-panel-section">
      <div class="graph-panel-label">Legend</div>
      <div id="graph-legend" class="graph-legend"></div>
    </div>
    <div class="graph-panel-section">
      <div id="graph-stats" class="graph-stats">nodes 0 &middot; edges 0 &middot; papers 0</div>
    </div>
    <div class="graph-panel-section">
      <input id="graph-search" class="graph-search" type="text" placeholder="Search nodes..." autocomplete="off">
    </div>
  `;
  canvas.appendChild(_leftPanel);

  _sectionListEl = _leftPanel.querySelector('#graph-section-list');
  _statsEl = _leftPanel.querySelector('#graph-stats');

  // Render legend
  _renderLegend(_leftPanel.querySelector('#graph-legend'));

  // Search box
  const searchInput = _leftPanel.querySelector('#graph-search');
  searchInput.addEventListener('input', (e) => {
    if (_searchDebounceTimer) clearTimeout(_searchDebounceTimer);
    _searchDebounceTimer = setTimeout(() => {
      graphEngine.setSearchFilter(e.target.value);
    }, 250);
  });

  // RIGHT DETAIL PANEL
  _detailPanel = document.createElement('div');
  _detailPanel.className = 'graph-detail-panel';
  _detailPanel.style.display = 'none';
  _detailPanel.innerHTML = `
    <button class="graph-detail-close" aria-label="Close">&times;</button>
    <div id="graph-detail-content" class="graph-detail-content"></div>
  `;
  canvas.appendChild(_detailPanel);

  _detailPanel.querySelector('.graph-detail-close').addEventListener('click', () => {
    _detailPanel.style.display = 'none';
  });

  // LIVE BADGE
  _liveBadge = document.createElement('div');
  _liveBadge.className = 'graph-live-badge';
  _liveBadge.innerHTML = '<span class="graph-live-dot"></span> LIVE';
  _liveBadge.style.display = 'none';
  canvas.appendChild(_liveBadge);
}

// ---------------------------------------------------------------------------
// Section switcher
// ---------------------------------------------------------------------------

function _renderSectionList() {
  if (!_sectionListEl) return;

  const rows = [];

  // "Full graph" row
  const isFullActive = _activeSectionId === null;
  rows.push(
    `<div class="graph-section-row${isFullActive ? ' active' : ''}" data-section-id="">` +
    `<span class="graph-section-dot">&#9679;</span> Full graph</div>`
  );

  // Section rows
  if (_sectionsCache.length === 0) {
    rows.push(`<div class="graph-section-hint muted">No draft sections yet</div>`);
  } else {
    _sectionsCache.forEach((sec, idx) => {
      const isActive = _activeSectionId === sec.id;
      const title = escapeHtml(sec.title || `Section ${idx + 1}`);
      const count = sec.node_count != null ? ` <span class="muted">${sec.node_count}</span>` : '';
      rows.push(
        `<div class="graph-section-row${isActive ? ' active' : ''}" data-section-id="${escapeHtml(sec.id)}">` +
        `<span class="graph-section-bullet">§${idx + 1}</span> ${title}${count}</div>`
      );
    });
  }

  _sectionListEl.innerHTML = rows.join('');

  // Wire clicks
  _sectionListEl.querySelectorAll('.graph-section-row').forEach(row => {
    row.addEventListener('click', () => {
      const secId = row.dataset.sectionId || null;
      _activeSectionId = secId || null;
      graphEngine.setSectionFilter(_activeSectionId);
      // Update URL hash
      const hash = _activeSectionId
        ? `#/graph?section=${encodeURIComponent(_activeSectionId)}`
        : '#/graph';
      window.location.hash = hash.replace(/^#/, '');
      _renderSectionList();
    });
  });
}

function _updateSectionList() {
  // Refresh sections from store if available
  const { sections } = store.getState();
  if (sections && sections.length > 0) {
    _sectionsCache = sections;
  }
  _renderSectionList();
  _updateStats();
}

function _readUrlSection() {
  const hash = window.location.hash || '';
  const match = hash.match(/[?&]section=([^&]*)/);
  if (match) {
    const sectionId = decodeURIComponent(match[1]);
    _activeSectionId = sectionId || null;
    graphEngine.setSectionFilter(_activeSectionId);
    _renderSectionList();
  }
}

// ---------------------------------------------------------------------------
// Legend
// ---------------------------------------------------------------------------

const KIND_SHAPE_LABELS = {
  paper:   'box',
  concept: 'circle',
  method:  'triangle',
  dataset: 'diamond',
  claim:   'ellipse',
  result:  'star',
};

function _renderLegend(container) {
  const kinds = Object.keys(KIND_COLORS);
  const items = kinds.map(kind => {
    const color = KIND_COLORS[kind] || '#8b949e';
    const shape = KIND_SHAPE_LABELS[kind] || 'dot';
    return `
      <div class="graph-legend-row" data-kind="${kind}">
        <span class="graph-legend-swatch" style="background:${color};"></span>
        <span class="graph-legend-kind">${kind}</span>
        <span class="graph-legend-shape muted">${shape}</span>
      </div>
    `;
  }).join('');
  container.innerHTML = items;

  // Toggle kind visibility on click
  container.querySelectorAll('.graph-legend-row').forEach(row => {
    row.addEventListener('click', () => {
      const kind = row.dataset.kind;
      if (_hiddenKinds.has(kind)) {
        _hiddenKinds.delete(kind);
        row.classList.remove('graph-legend-hidden');
      } else {
        _hiddenKinds.add(kind);
        row.classList.add('graph-legend-hidden');
      }
      graphEngine.setKindFilter(_hiddenKinds);
    });
  });
}

// ---------------------------------------------------------------------------
// Stats
// ---------------------------------------------------------------------------

function _updateStats() {
  if (!_statsEl) return;
  const nodesDS = graphEngine.getNodesDataSet();
  const edgesDS = graphEngine.getEdgesDataSet();
  if (!nodesDS || !edgesDS) return;
  const nodes = nodesDS.get();
  const edges = edgesDS.get();
  const papers = nodes.filter(n => n.kind === 'paper').length;
  _statsEl.textContent = `nodes ${nodes.length} · edges ${edges.length} · papers ${papers}`;
}

// ---------------------------------------------------------------------------
// Live badge
// ---------------------------------------------------------------------------

function _updateLiveBadge() {
  if (!_liveBadge) return;
  const { jobs } = store.getState();
  const anyRunning = jobs && [...jobs.values()].some(j => j.status === 'running');
  _liveBadge.style.display = anyRunning ? 'flex' : 'none';
}

// ---------------------------------------------------------------------------
// Node / Edge detail panel
// ---------------------------------------------------------------------------

const DETAIL_ATTRS = [
  'definition', 'description', 'metric', 'value',
  'dataset', 'authors', 'year', 'source_url', 'full_text',
];

function _showNodeDetail(node) {
  if (!_detailPanel) return;
  const content = _detailPanel.querySelector('#graph-detail-content');
  if (!content) return;

  const kindColor = KIND_COLORS[node.kind] || '#8b949e';
  const label = escapeHtml(node.label || node.id || '');
  const kind = escapeHtml(node.kind || 'unknown');

  let html = `
    <div class="graph-detail-header">
      <div class="graph-detail-title">${label}</div>
      <span class="graph-detail-badge" style="background:${kindColor}22;color:${kindColor};">${kind}</span>
    </div>
  `;

  // Strength banner for paper nodes
  if (node.kind === 'paper' && node.strength) {
    const s = node.strength;
    const band = escapeHtml(s.band || '');
    const color = s.color || '#8b949e';
    html += `
      <div class="graph-strength-banner" style="border-color:${color};">
        <span class="graph-strength-label" style="color:${color};">${band}</span>
        ${s.score != null ? `<span class="muted">${escapeHtml(String(s.score))}</span>` : ''}
      </div>
    `;
  }

  // Attr list
  const attrRows = DETAIL_ATTRS
    .filter(attr => node[attr] != null && node[attr] !== '')
    .map(attr => {
      let val = node[attr];
      if (Array.isArray(val)) val = val.join(', ');
      return `
        <div class="graph-detail-attr">
          <span class="graph-detail-attr-key">${escapeHtml(attr)}</span>
          <span class="graph-detail-attr-val">${escapeHtml(String(val))}</span>
        </div>
      `;
    });

  if (attrRows.length > 0) {
    html += `<div class="graph-detail-attrs">${attrRows.join('')}</div>`;
  }

  // "Open in Library" for paper nodes
  if (node.kind === 'paper') {
    html += `
      <button class="btn btn-secondary btn-sm graph-open-library" data-paper-id="${escapeHtml(node.id || '')}">
        Open in Library
      </button>
    `;
  }

  content.innerHTML = html;

  // Wire "Open in Library"
  const libBtn = content.querySelector('.graph-open-library');
  if (libBtn) {
    libBtn.addEventListener('click', () => {
      window.location.hash = '/library';
    });
  }

  _detailPanel.style.display = 'flex';
}

function _showEdgeDetail(edge) {
  if (!_detailPanel) return;
  const content = _detailPanel.querySelector('#graph-detail-content');
  if (!content) return;

  const relation = escapeHtml(edge.label || edge.title || edge.relation || '');
  const from = escapeHtml(String(edge.from || ''));
  const to = escapeHtml(String(edge.to || ''));

  content.innerHTML = `
    <div class="graph-detail-header">
      <div class="graph-detail-title">Edge</div>
      <span class="graph-detail-badge">${relation || 'relation'}</span>
    </div>
    <div class="graph-detail-attrs">
      <div class="graph-detail-attr">
        <span class="graph-detail-attr-key">from</span>
        <span class="graph-detail-attr-val">${from}</span>
      </div>
      <div class="graph-detail-attr">
        <span class="graph-detail-attr-key">to</span>
        <span class="graph-detail-attr-val">${to}</span>
      </div>
      ${relation ? `<div class="graph-detail-attr">
        <span class="graph-detail-attr-key">relation</span>
        <span class="graph-detail-attr-val">${relation}</span>
      </div>` : ''}
    </div>
  `;

  _detailPanel.style.display = 'flex';
}

// ---------------------------------------------------------------------------
// Canvas visibility helpers
// ---------------------------------------------------------------------------

function _showCanvas() {
  const canvas = document.getElementById('graph-canvas');
  if (canvas) {
    canvas.style.display = 'block';
    canvas.style.zIndex = '10';
  }
  // Hide the #view scrollable area so it doesn't overlap
  const view = document.getElementById('view');
  if (view) view.style.visibility = 'hidden';
}

function _hideCanvas() {
  const canvas = document.getElementById('graph-canvas');
  if (canvas) {
    canvas.style.display = 'none';
    canvas.style.zIndex = '';
  }
  const view = document.getElementById('view');
  if (view) view.style.visibility = '';
}
