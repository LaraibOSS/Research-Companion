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
import { nodeToVis, edgeToVis, KIND_COLORS } from '../graph/mapping.js';
import * as graphEngine from '../graph/graphview.js';
import { onGraphDeltas } from '../sse.js';

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
let _unsubGraphDeltas = null;

// Injectable search debounce scheduler (defaults to setTimeout; injectable for tests).
let _searchScheduler = (fn, ms) => setTimeout(fn, ms);
let _searchCanceller = (id) => clearTimeout(id);

/**
 * Inject a custom scheduler/canceller for the search debounce (for testing).
 * @param {Function} scheduler
 * @param {Function} canceller
 */
export function _setSearchScheduler(scheduler, canceller) {
  _searchScheduler = scheduler;
  _searchCanceller = canceller;
}

// ---------------------------------------------------------------------------
// Module init — register graph delta subscription from sse.js
// This runs once when the module is first imported.
// ---------------------------------------------------------------------------

_unsubGraphDeltas = onGraphDeltas((batch) => {
  if (!_mounted) return;
  const { draftId } = store.getState();
  for (const delta of batch) {
    graphEngine.applyDelta(delta, draftId);
  }
  _updateStats();
});

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
  // 'graph' topic is now only used for counter/stat updates from non-delta paths.
  // Delta live-growth goes through onGraphDeltas (registered at module init).
  const unsubSections = store.subscribe(['sections', 'papers'], _updateSectionList);
  _unsubscribers = [unsubJobs, unsubSections];

  // Initial data load — always fetch FULL graph (section scoping is client-side via DataView)
  _loadInitialGraph();
  _loadSections();
  _updateLiveBadge();
  _readUrlSection();
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
  if (_searchDebounceTimer) _searchCanceller(_searchDebounceTimer);
  _searchDebounceTimer = null;
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
    // Always fetch the FULL graph — section scoping is purely client-side via DataView.
    // The DataView filter (_rebuildViews) handles section visibility without re-fetching.
    const graphJson = await api.getGraph();
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

// 'graph' topic subscriptions are no longer used for delta handling.
// graph_delta live-growth goes through onGraphDeltas (module init above).
// Stats are updated directly from the delta handler and from _loadInitialGraph.

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

  // Search box — debounced dim (not DataView filter)
  const searchInput = _leftPanel.querySelector('#graph-search');
  searchInput.addEventListener('input', (e) => {
    if (_searchDebounceTimer) _searchCanceller(_searchDebounceTimer);
    _searchDebounceTimer = _searchScheduler(() => {
      _searchDebounceTimer = null;
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
      const isActive = _activeSectionId === sec.section_id;
      const title = escapeHtml(sec.title || `Section ${idx + 1}`);
      const count = sec.node_count != null ? ` <span class="muted">${sec.node_count}</span>` : '';
      rows.push(
        `<div class="graph-section-row${isActive ? ' active' : ''}" data-section-id="${escapeHtml(sec.section_id)}">` +
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
      // Section scoping is purely client-side DataView filter — no re-fetch needed.
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
  paper:   'card',
  concept: 'dot',
  method:  'dot',
  dataset: 'dot',
  claim:   'dot',
  result:  'dot',
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
