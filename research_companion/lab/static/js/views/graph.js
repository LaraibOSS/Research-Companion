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
import {
  buildDraftModel, layoutDraftEgo, makeDraftPredicate, collectPaperEntities,
} from '../graph/draftLayout.js';
import { onGraphDeltas } from '../sse.js';
import { viewRowModel } from '../viewsHelpers.js';
import { showToast } from '../components/toast.js';
import { explainerBanner } from '../components/explainer.js';

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

// ---------------------------------------------------------------------------
// Saved-views state (W3-F6)
// ---------------------------------------------------------------------------

let _activeViewId = null;      // currently-loaded saved view (null = live mode)
let _savedViewsEl = null;      // container for the saved-views rows
let _viewChipEl = null;        // "Viewing: <name> — back to live" chip near LIVE badge

// Guard flag: while a saved view is active, suppress live graph_delta application.
let _savedViewActive = false;

// ---------------------------------------------------------------------------
// Draft-mode state (W4-F3)
// ---------------------------------------------------------------------------

const MODE_STORAGE_KEY = 'rc.graphMode';

let _mode = 'explore';                  // 'draft' | 'explore'
let _modeToggleEl = null;               // floating segmented toggle
// Guard flag: while draft mode is active, suppress live graph_delta
// repositioning (same pattern as _savedViewActive).
let _draftModeActive = false;
let _draftSyntheticNodeIds = new Set(); // synthetic 'sec:' node ids (clean removal)
let _draftSyntheticEdgeIds = new Set(); // synthetic alignment edge ids (clean removal)
let _draftFixedNodeIds = [];            // real node ids we pinned on enter
let _draftVisibleIds = new Set();       // draft + papers + sec: nodes
let _expandedEntityIds = new Set();     // entity ids currently expanded
let _expandedByPaper = new Map();       // paperId -> entity ids expanded for it
let _sectorLabels = [];                 // [{text, relation, x, y}] drawn on canvas
let _beforeDrawingHandler = null;       // registered on the network; off() on exit

// Alignment edge colors per relation ('unaligned' papers get NO edges).
const DRAFT_EDGE_COLORS = {
  strengthens: '#3fb950',
  challenges:  '#f85149',
  alternative: '#d29922',
};

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
  // While a saved view or the draft ego layout is active, live deltas must
  // not repaint/reposition it (same guard pattern for both).
  if (_savedViewActive || _draftModeActive) return;
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

  // Explainer banner — appended to the view container (_el)
  if (_el) {
    const banner = explainerBanner(
      'graph',
      'Every paper becomes claims, methods and results — click anything to inspect it.',
    );
    if (banner) _el.prepend(banner);
  }

  // Subscribe to store
  const unsubJobs = store.subscribe(['jobs'], _updateLiveBadge);
  // 'graph' topic is now only used for counter/stat updates from non-delta paths.
  // Delta live-growth goes through onGraphDeltas (registered at module init).
  const unsubSections = store.subscribe(['sections', 'papers'], _updateSectionList);
  const unsubViews = store.subscribe(['views'], _renderSavedViews);
  const unsubDraft = store.subscribe(['draft'], _renderModeToggle);
  _unsubscribers = [unsubJobs, unsubSections, unsubViews, unsubDraft];

  // Graph mode: persisted; default 'draft' when a draft exists (W4-F3)
  _mode = _initialMode();
  _renderModeToggle();

  // Initial data load — always fetch FULL graph (section scoping is client-side via DataView).
  // Draft mode is entered only AFTER the snapshot lands, otherwise loadSnapshot()
  // would clobber the synthetic section nodes and pinned positions.
  _loadInitialGraph().then(() => {
    if (_mounted && _mode === 'draft') _enterDraftMode();
  });
  _loadSections();
  _loadViews();
  _updateLiveBadge();
  _readUrlSection();
}

/**
 * Unmount: hide #graph-canvas, remove panels, unsubscribe.
 */
export function unmount() {
  if (!_mounted) return;
  _mounted = false;

  // Leave the shared graph engine in live/explore state (physics on, no
  // override predicate, no synthetic nodes). _mode stays persisted, so the
  // next mount re-enters draft mode after the fresh snapshot loads.
  if (_draftModeActive) _exitDraftMode({ reload: false });

  _hideCanvas();

  // Remove floating panels from canvas
  const canvas = document.getElementById('graph-canvas');
  if (canvas) {
    if (_leftPanel && _leftPanel.parentNode === canvas) canvas.removeChild(_leftPanel);
    if (_detailPanel && _detailPanel.parentNode === canvas) canvas.removeChild(_detailPanel);
    if (_liveBadge && _liveBadge.parentNode === canvas) canvas.removeChild(_liveBadge);
    if (_viewChipEl && _viewChipEl.parentNode === canvas) canvas.removeChild(_viewChipEl);
    if (_modeToggleEl && _modeToggleEl.parentNode === canvas) canvas.removeChild(_modeToggleEl);
  }
  _leftPanel = null;
  _detailPanel = null;
  _liveBadge = null;
  _statsEl = null;
  _sectionListEl = null;
  _savedViewsEl = null;
  _viewChipEl = null;
  _modeToggleEl = null;

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
    if (!node) return;
    // Synthetic section nodes have no real detail to show.
    if (typeof node.id === 'string' && node.id.startsWith('sec:')) return;
    // In draft mode, clicking a paper toggles its entity ring (W4-F3).
    if (_draftModeActive && node.kind === 'paper' && node.id !== store.getState().draftId) {
      _togglePaperEntities(node.id);
    }
    _showNodeDetail(node);
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

async function _loadViews() {
  try {
    const data = await api.getViews();
    store.setViews((data && data.views) || []);
  } catch (err) {
    // Views endpoint may not be available — fail silently
    store.setViews([]);
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
    <div class="graph-panel-section" id="graph-saved-views-section">
      <div class="graph-panel-label">Saved Views</div>
      <div id="graph-saved-views-list" class="graph-saved-views-list"></div>
    </div>
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
  _savedViewsEl = _leftPanel.querySelector('#graph-saved-views-list');
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

  // VIEW CHIP (shown when a saved view is active)
  _viewChipEl = document.createElement('div');
  _viewChipEl.className = 'graph-view-chip';
  _viewChipEl.style.display = 'none';
  canvas.appendChild(_viewChipEl);

  // MODE TOGGLE — floating top-center segmented pill (W4-F3)
  _modeToggleEl = document.createElement('div');
  _modeToggleEl.className = 'graph-mode-toggle';
  canvas.appendChild(_modeToggleEl);
  _renderModeToggle();
}

// ---------------------------------------------------------------------------
// Draft-centric graph mode (W4-F3)
// ---------------------------------------------------------------------------

function _initialMode() {
  let saved = null;
  try { saved = localStorage.getItem(MODE_STORAGE_KEY); } catch { /* private mode */ }
  if (saved === 'draft' || saved === 'explore') {
    // A persisted 'draft' preference only holds while a draft exists.
    if (saved === 'draft' && !store.getState().draftId) return 'explore';
    return saved;
  }
  return store.getState().draftId ? 'draft' : 'explore';
}

function _persistMode(mode) {
  try { localStorage.setItem(MODE_STORAGE_KEY, mode); } catch { /* private mode */ }
}

function _renderModeToggle() {
  if (!_modeToggleEl) return;
  const { draftId } = store.getState();
  const disabled = !draftId;

  _modeToggleEl.classList.toggle('disabled', disabled);
  if (disabled) {
    _modeToggleEl.setAttribute('data-tip', 'Add a draft to unlock Draft mode');
  } else {
    _modeToggleEl.removeAttribute('data-tip');
  }

  _modeToggleEl.innerHTML = `
    <button class="graph-mode-seg${_mode === 'draft' ? ' active' : ''}"
            data-mode="draft" ${disabled ? 'disabled' : ''}>&#11089; Draft</button>
    <button class="graph-mode-seg${_mode === 'explore' ? ' active' : ''}"
            data-mode="explore">Explore</button>
  `;

  _modeToggleEl.querySelectorAll('.graph-mode-seg').forEach(btn => {
    btn.addEventListener('click', () => {
      if (btn.disabled) return;
      _setMode(btn.dataset.mode);
    });
  });
}

function _setMode(mode) {
  if (mode !== 'draft' && mode !== 'explore') return;
  _mode = mode;
  _persistMode(mode);
  _renderModeToggle();
  if (mode === 'draft') {
    _enterDraftMode();
  } else {
    _exitDraftMode({ reload: true });
  }
}

/** Draft-mode entry failed — toast and fall back to explore cleanly. */
function _fallBackToExplore(message) {
  if (message) showToast(message, 'error');
  _mode = 'explore';
  _persistMode('explore');
  _renderModeToggle();
}

// In-flight guard: prevents a second enter (mount + toggle click racing)
// from double-adding synthetic nodes while the fetches are pending.
let _enteringDraft = false;

async function _enterDraftMode() {
  if (_draftModeActive || _enteringDraft) return;

  const network = graphEngine.getNetwork();
  const nodesDS = graphEngine.getNodesDataSet();
  const edgesDS = graphEngine.getEdgesDataSet();
  if (!network || !nodesDS || !edgesDS) return;

  const { draftId, papers } = store.getState();
  if (!draftId) {
    _fallBackToExplore('Set a draft first to use Draft mode');
    return;
  }

  _enteringDraft = true;
  try {
    await _enterDraftModeInner(network, nodesDS, edgesDS, papers);
  } finally {
    _enteringDraft = false;
  }
}

async function _enterDraftModeInner(network, nodesDS, edgesDS, papers) {
  let alignment, sections;
  try {
    [alignment, sections] = await Promise.all([api.getDraftAlignment(), api.getSections()]);
  } catch (err) {
    _fallBackToExplore(`Draft mode unavailable: ${err.message}`);
    return;
  }
  if (!_mounted || _mode !== 'draft') return; // user navigated / toggled away meanwhile

  const model = buildDraftModel(alignment, sections || [], papers);
  if (!model.draftId || model.sections.length === 0) {
    _fallBackToExplore('No draft sections yet — run alignment first');
    return;
  }

  const { positions, sectorLabels } = layoutDraftEgo(model);
  _draftModeActive = true;

  // 1. Synthetic section nodes (muted boxes, fixed, no physics)
  const secNodes = model.sections.map(s => {
    const id = 'sec:' + s.id;
    const pos = positions.get(id) || { x: 0, y: 0 };
    _draftSyntheticNodeIds.add(id);
    return {
      id,
      kind: 'section',
      label: s.title || 'Section',
      title: s.title || 'Section',
      shape: 'box',
      margin: 6,
      color: {
        background: 'rgba(110,118,129,0.12)',
        border: 'rgba(110,118,129,0.45)',
        highlight: { background: 'rgba(110,118,129,0.2)', border: 'rgba(139,148,158,0.6)' },
      },
      font: { color: '#9aa4b2', size: 11 },
      x: pos.x, y: pos.y,
      fixed: { x: true, y: true },
      physics: false,
    };
  });

  // 2. Synthetic alignment edges (paper -> sec:) — 'unaligned' papers get none
  const alignEdges = [];
  for (const p of model.papers) {
    for (const e of p.edges) {
      const color = DRAFT_EDGE_COLORS[e.relation];
      if (!color) continue;
      const id = `draftedge:${p.paperId}:${e.sectionId}:${e.relation}`;
      if (_draftSyntheticEdgeIds.has(id)) continue;
      _draftSyntheticEdgeIds.add(id);
      alignEdges.push({
        id,
        from: p.paperId,
        to: 'sec:' + e.sectionId,
        relation: e.relation,
        title: e.relation,
        width: 1.5,
        smooth: { enabled: true, type: 'curvedCW', roundness: 0.2 },
        color: { color, highlight: color },
        arrows: { to: { enabled: true, scaleFactor: 0.5 } },
      });
    }
  }

  nodesDS.add(secNodes);
  if (alignEdges.length) edgesDS.add(alignEdges);

  // 3. Pin the real draft/paper nodes at their layout coordinates
  const nodeUpdates = [];
  _draftFixedNodeIds = [];
  for (const [nodeId, pos] of positions) {
    if (_draftSyntheticNodeIds.has(nodeId)) continue;
    if (!nodesDS.get(nodeId)) continue;
    nodeUpdates.push({ id: nodeId, x: pos.x, y: pos.y, fixed: { x: true, y: true }, physics: false });
    _draftFixedNodeIds.push(nodeId);
  }
  if (nodeUpdates.length) nodesDS.update(nodeUpdates);

  // 4. Freeze physics + show only draft/papers/sections (entities hidden)
  _draftVisibleIds = new Set([
    model.draftId,
    ...model.sections.map(s => 'sec:' + s.id),
    ...model.papers.map(p => p.paperId),
  ]);
  _expandedEntityIds = new Set();
  _expandedByPaper = new Map();
  graphEngine.setPhysics(false);
  graphEngine.setOverridePredicate(makeDraftPredicate(_draftVisibleIds, _expandedEntityIds));

  // 5. Sector labels painted straight on the canvas (world coordinates).
  //    FALLBACK if painting misbehaves in some browser: replace this handler
  //    with plain vis nodes (shape:'text') at the same layout coords.
  _sectorLabels = sectorLabels;
  _beforeDrawingHandler = (ctx) => {
    ctx.save();
    // Gold halo behind the draft node (world origin) — makes the anchor of
    // the ego layout unmistakable without mutating node styles.
    const halo = ctx.createRadialGradient(0, 0, 20, 0, 0, 130);
    halo.addColorStop(0, 'rgba(227,179,65,0.28)');
    halo.addColorStop(1, 'rgba(227,179,65,0)');
    ctx.fillStyle = halo;
    ctx.beginPath();
    ctx.arc(0, 0, 130, 0, 2 * Math.PI);
    ctx.fill();
    ctx.strokeStyle = 'rgba(227,179,65,0.5)';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.arc(0, 0, 92, 0, 2 * Math.PI);
    ctx.stroke();

    ctx.font = '12px arial';
    if ('letterSpacing' in ctx) ctx.letterSpacing = '2px';
    ctx.fillStyle = 'rgba(139,148,158,0.75)';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    for (const lbl of _sectorLabels) {
      ctx.fillText(String(lbl.text || '').toUpperCase(), lbl.x, lbl.y);
    }
    ctx.restore();
  };
  network.on('beforeDrawing', _beforeDrawingHandler);

  network.fit();
  _updateStats();
}

/**
 * Exit draft mode — exact inverse of every _enterDraftMode mutation:
 * synthetic nodes/edges removed, pinned nodes released, physics + computed
 * filter restored, canvas painter unregistered, live snapshot reloaded.
 */
function _exitDraftMode({ reload = true } = {}) {
  if (!_draftModeActive) return;
  _draftModeActive = false;

  const network = graphEngine.getNetwork();
  const nodesDS = graphEngine.getNodesDataSet();
  const edgesDS = graphEngine.getEdgesDataSet();

  // 5'. Unregister the sector-label painter
  if (network && _beforeDrawingHandler) network.off('beforeDrawing', _beforeDrawingHandler);
  _beforeDrawingHandler = null;
  _sectorLabels = [];

  // 1'./2'. Remove synthetic section nodes + alignment edges
  if (edgesDS && _draftSyntheticEdgeIds.size) edgesDS.remove([..._draftSyntheticEdgeIds]);
  if (nodesDS && _draftSyntheticNodeIds.size) nodesDS.remove([..._draftSyntheticNodeIds]);
  _draftSyntheticEdgeIds = new Set();
  _draftSyntheticNodeIds = new Set();

  // 3'. Release pinned real nodes (and any expanded entity nodes)
  if (nodesDS) {
    const releaseIds = [..._draftFixedNodeIds, ..._expandedEntityIds]
      .filter(id => nodesDS.get(id));
    if (releaseIds.length) {
      nodesDS.update(releaseIds.map(id => ({ id, fixed: false, physics: true })));
    }
  }
  _draftFixedNodeIds = [];
  _draftVisibleIds = new Set();
  _expandedEntityIds = new Set();
  _expandedByPaper = new Map();

  // 4'. Restore computed filter + physics
  graphEngine.setOverridePredicate(null);
  graphEngine.setPhysics(true);

  if (reload) _loadInitialGraph();
}

/** Toggle the entity ring around a paper (draft mode only). */
function _togglePaperEntities(paperId) {
  const network = graphEngine.getNetwork();
  const nodesDS = graphEngine.getNodesDataSet();
  const edgesDS = graphEngine.getEdgesDataSet();
  if (!network || !nodesDS || !edgesDS) return;

  if (_expandedByPaper.has(paperId)) {
    // Collapse: release + hide this paper's entities
    const ids = _expandedByPaper.get(paperId);
    _expandedByPaper.delete(paperId);
    for (const id of ids) _expandedEntityIds.delete(id);
    const present = ids.filter(id => nodesDS.get(id));
    if (present.length) {
      nodesDS.update(present.map(id => ({ id, fixed: false, physics: true })));
    }
  } else {
    // Expand: deterministic small ring around the paper, fixed
    const entityIds = collectPaperEntities(edgesDS.get(), paperId)
      .filter(id => nodesDS.get(id))
      .sort();
    if (entityIds.length === 0) return;
    const paperPos = (network.getPositions([paperId]) || {})[paperId] || { x: 0, y: 0 };
    const ringRadius = 90;
    nodesDS.update(entityIds.map((id, i) => {
      const a = -Math.PI / 2 + (2 * Math.PI * i) / entityIds.length;
      return {
        id,
        x: paperPos.x + ringRadius * Math.cos(a),
        y: paperPos.y + ringRadius * Math.sin(a),
        fixed: { x: true, y: true },
        physics: false,
      };
    }));
    _expandedByPaper.set(paperId, entityIds);
    for (const id of entityIds) _expandedEntityIds.add(id);
  }

  graphEngine.setOverridePredicate(makeDraftPredicate(_draftVisibleIds, _expandedEntityIds));
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
      // Clicking "Full graph" also restores live mode if a saved view is active
      if (!secId && _savedViewActive) {
        _restoreLive();
      }
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

// ---------------------------------------------------------------------------
// Saved views section (W3-F6)
// ---------------------------------------------------------------------------

function _renderSavedViews() {
  if (!_savedViewsEl) return;
  const { views } = store.getState();
  const rows = viewRowModel(views || [], _activeViewId);

  if (rows.length === 0) {
    _savedViewsEl.innerHTML =
      `<div class="graph-views-empty muted">No saved views yet — save one from Ask.</div>`;
    return;
  }

  _savedViewsEl.innerHTML = rows.map(row => {
    const label = escapeHtml(row.label);
    const id = escapeHtml(row.id);
    const pinTitle = row.pinned ? 'Unpin' : 'Pin';
    const pinClass = row.pinned ? 'graph-views-pin-btn pinned' : 'graph-views-pin-btn';
    return `
      <div class="graph-views-row${row.active ? ' active' : ''}" data-view-id="${id}">
        <button class="${pinClass}" data-action="pin" title="${pinTitle}" aria-label="${pinTitle}">
          <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 18 18"
               fill="${row.pinned ? 'currentColor' : 'none'}"
               stroke="currentColor" stroke-width="1.7"
               stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 2L6 8l-4 1 5 5 1-4 6-6-2-2z"/>
            <line x1="3" y1="15" x2="7" y2="11"/>
          </svg>
        </button>
        <span class="graph-views-name" data-action="load">${label}</span>
        <span class="graph-views-count muted">${escapeHtml(String(row.count))}</span>
        <button class="graph-views-delete-btn" data-action="delete" title="Delete view" aria-label="Delete view">&times;</button>
      </div>
    `;
  }).join('');

  // Wire events
  _savedViewsEl.querySelectorAll('.graph-views-row').forEach(rowEl => {
    const viewId = rowEl.dataset.viewId;

    rowEl.addEventListener('click', (e) => {
      const action = e.target.closest('[data-action]');
      if (!action) return;

      switch (action.dataset.action) {
        case 'pin': _handlePin(viewId, rowEl); break;
        case 'load': _loadViewSnapshot(viewId); break;
        case 'delete': _startDeleteConfirm(rowEl, viewId); break;
      }
    });
  });
}

async function _handlePin(viewId, rowEl) {
  const { views } = store.getState();
  const view = (views || []).find(v => v.view_id === viewId);
  if (!view) return;
  const newPinned = !view.pinned;
  try {
    await api.patchView(viewId, { pinned: newPinned });
    await _loadViews();
  } catch (err) {
    showToast(`Could not update pin: ${err.message}`, 'error');
  }
}

async function _loadViewSnapshot(viewId) {
  try {
    const data = await api.getViewGraph(viewId);
    // A saved view replaces the whole dataset — leave draft mode first
    // (no reload: loadSnapshot below provides the data).
    if (_draftModeActive) {
      _mode = 'explore';
      _persistMode('explore');
      _exitDraftMode({ reload: false });
      _renderModeToggle();
    }
    const { draftId } = store.getState();
    graphEngine.loadSnapshot(data, draftId);
    _activeViewId = viewId;
    _savedViewActive = true;
    _renderSavedViews();
    _updateViewChip(data.view);
    if (data.missing_node_ids && data.missing_node_ids.length > 0) {
      const n = data.missing_node_ids.length;
      showToast(`${n} saved node${n !== 1 ? 's' : ''} no longer exist in the graph`, 'error');
    }
    _updateStats();
  } catch (err) {
    showToast(`Could not load view: ${err.message}`, 'error');
  }
}

function _restoreLive() {
  _activeViewId = null;
  _savedViewActive = false;
  _renderSavedViews();
  _updateViewChip(null);
  // Reload the full live graph
  _loadInitialGraph();
}

function _updateViewChip(view) {
  if (!_viewChipEl) return;
  if (!view) {
    _viewChipEl.style.display = 'none';
    _viewChipEl.innerHTML = '';
    return;
  }
  const name = escapeHtml(view.name || 'Saved view');
  _viewChipEl.innerHTML =
    `Viewing: <strong>${name}</strong> &mdash; <span class="graph-view-chip-live">back to live</span>`;
  _viewChipEl.style.display = 'flex';

  // Wire "back to live" click
  const liveLink = _viewChipEl.querySelector('.graph-view-chip-live');
  if (liveLink) {
    liveLink.addEventListener('click', _restoreLive);
  }
}

function _startDeleteConfirm(rowEl, viewId) {
  // Swap row content to inline "Delete? yes / no" (no confirm())
  rowEl.innerHTML = `
    <span class="graph-views-delete-prompt muted">Delete?</span>
    <button class="btn btn-danger btn-sm graph-views-confirm-yes">yes</button>
    <button class="btn btn-secondary btn-sm graph-views-confirm-no">no</button>
  `;

  rowEl.querySelector('.graph-views-confirm-no').addEventListener('click', () => {
    _renderSavedViews();
  });

  rowEl.querySelector('.graph-views-confirm-yes').addEventListener('click', async () => {
    try {
      await api.deleteView(viewId);
      // If deleting the active view, restore live mode
      if (_activeViewId === viewId) {
        _restoreLive();
        return;
      }
      await _loadViews();
    } catch (err) {
      showToast(`Could not delete view: ${err.message}`, 'error');
      _renderSavedViews();
    }
  });
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
