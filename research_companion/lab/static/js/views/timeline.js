/**
 * views/timeline.js — Full Timeline view for the Research Lab.
 * Route: /timeline
 * W3-F5.
 *
 * Layout:
 *   - Dismissable explainer banner
 *   - Toolbar: kind filter chips, gap overlay toggle, legend, Refresh Gaps button
 *   - Horizontally scrollable canvas: sticky year header, sticky-left lane labels,
 *     lane rows (dots + connecting segments), bottom density row
 *   - Gap lane (top of canvas): diamond markers
 *   - Right detail panel (reuses .graph-detail-panel): gap detail on click
 */

import * as store  from '../store.js';
import * as api    from '../api.js';
import { escapeHtml } from '../format.js';
import { KIND_COLORS } from '../graph/mapping.js';
import { layoutTimeline } from '../timeline/layout.js';
import { showToast }      from '../components/toast.js';

// ---------------------------------------------------------------------------
// Module state
// ---------------------------------------------------------------------------

let _el          = null;     // mount root
let _unsubs      = [];       // store unsubscribers
let _temporal    = null;     // last fetched temporal data
let _gaps        = null;     // last fetched gaps overview
let _hiddenKinds = new Set();
let _showGaps    = true;
let _selectedGap = null;     // { gap, paperEntry, inDraft }
let _detailPanel = null;     // right panel DOM element
let _canvasWrap  = null;     // scrollable canvas wrapper

const OPTS = { yearWidth: 140, laneHeight: 56, labelWidth: 180 };

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

export function mount(el) {
  _el = el;
  _hiddenKinds.clear();
  _showGaps    = true;
  _selectedGap = null;

  el.innerHTML = _skeletonHtml();

  _detailPanel = el.querySelector('.tl-detail-panel');
  _canvasWrap  = el.querySelector('.tl-canvas-wrap');

  // Dismiss explainer
  const dismissBtn = el.querySelector('.tl-explainer-dismiss');
  if (dismissBtn) {
    dismissBtn.addEventListener('click', () => {
      const banner = el.querySelector('.tl-explainer');
      if (banner) banner.style.display = 'none';
    });
  }

  // Subscribe to store changes for paper titles
  _unsubs.push(store.subscribe(['papers'], _render));

  // Lazy fetch both data sources
  _fetchAll();
}

export function unmount() {
  for (const u of _unsubs) u();
  _unsubs = [];
  _el     = null;
  _detailPanel = null;
  _canvasWrap  = null;
}

// ---------------------------------------------------------------------------
// Data fetching
// ---------------------------------------------------------------------------

async function _fetchAll() {
  try {
    [_temporal, _gaps] = await Promise.all([
      api.getTemporal(),
      api.getGaps(),
    ]);
  } catch (err) {
    console.warn('[timeline] fetch failed:', err);
  }
  _render();
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

function _render() {
  if (!_el) return;

  const layout = layoutTimeline(_temporal, _gaps, OPTS);

  // Empty state
  if (!_temporal || layout.width === 0) {
    const missing = (_temporal && _temporal.skipped_papers_without_year) || 0;
    _el.querySelector('.tl-body').innerHTML = `
      <div class="tl-empty">
        <div class="tl-empty-msg">
          Temporal view appears once your papers have years
          ${missing > 0 ? `— <strong>${escapeHtml(String(missing))}</strong> papers missing years` : ''}.
        </div>
        <button class="btn-primary tl-add-btn" onclick="window.location.hash='#/library'">
          Add papers
        </button>
      </div>`;
    return;
  }

  // Build paper_id -> title map from store
  const { papers } = store.getState();
  const titleMap = new Map();
  for (const [id, p] of papers) {
    titleMap.set(id, p.title || id);
  }

  // Also index gaps for the detail panel
  const gapIndex = _buildGapIndex();

  _el.querySelector('.tl-body').innerHTML = _buildCanvasHtml(layout, titleMap, gapIndex);

  // Wire toolbar chips
  _wireToolbar();

  // Wire dot/gap clicks after render
  _el.querySelectorAll('.tl-dot[data-paper-id]').forEach(dot => {
    dot.addEventListener('click', () => _openPaperDrawer(dot.dataset.paperId));
    dot.title = escapeHtml(titleMap.get(dot.dataset.paperId) || dot.dataset.paperId);
  });

  _el.querySelectorAll('.tl-gap-diamond[data-gap-id]').forEach(diamond => {
    diamond.addEventListener('click', () => {
      const gapId = diamond.dataset.gapId;
      _openGapDetail(gapId, gapIndex, titleMap);
    });
  });

  // Close detail panel if clicking canvas
  if (_canvasWrap) {
    _canvasWrap.addEventListener('click', (e) => {
      if (!e.target.closest('.tl-gap-diamond') && !e.target.closest('.tl-detail-panel')) {
        _closeDetail();
      }
    });
  }
}

// ---------------------------------------------------------------------------
// Toolbar wiring
// ---------------------------------------------------------------------------

function _wireToolbar() {
  if (!_el) return;

  // Kind filter chips
  _el.querySelectorAll('.tl-kind-chip[data-kind]').forEach(chip => {
    const kind = chip.dataset.kind;
    chip.classList.toggle('tl-chip-off', _hiddenKinds.has(kind));
    chip.addEventListener('click', () => {
      if (_hiddenKinds.has(kind)) {
        _hiddenKinds.delete(kind);
      } else {
        _hiddenKinds.add(kind);
      }
      _applyKindFilter();
      chip.classList.toggle('tl-chip-off', _hiddenKinds.has(kind));
    });
  });

  // Gap overlay toggle
  const gapToggle = _el.querySelector('.tl-gap-toggle');
  if (gapToggle) {
    gapToggle.checked = _showGaps;
    gapToggle.addEventListener('change', () => {
      _showGaps = gapToggle.checked;
      const gapRow = _el.querySelector('.tl-gap-row');
      if (gapRow) gapRow.style.display = _showGaps ? '' : 'none';
    });
  }

  // Refresh Gaps button
  const refreshBtn = _el.querySelector('.tl-refresh-gaps-btn');
  if (refreshBtn) {
    refreshBtn.addEventListener('click', async () => {
      try {
        showToast('Analyzing gaps…');
        await api.refreshGaps();
      } catch (err) {
        showToast('Failed to refresh gaps: ' + (err.message || 'error'));
      }
    });
  }
}

function _applyKindFilter() {
  if (!_el) return;
  _el.querySelectorAll('.tl-lane-row[data-kind]').forEach(row => {
    const kind = row.dataset.kind;
    row.style.display = _hiddenKinds.has(kind) ? 'none' : '';
  });
}

// ---------------------------------------------------------------------------
// HTML builders
// ---------------------------------------------------------------------------

function _skeletonHtml() {
  return `
    <div class="tl-root">
      <div class="tl-explainer">
        <span>How the field evolved — diamonds are gaps papers left open.</span>
        <button class="tl-explainer-dismiss" title="Dismiss">×</button>
      </div>
      <div class="tl-toolbar">
        <div class="tl-filter-chips">
          <span class="tl-chips-label muted">Show:</span>
          <button class="tl-kind-chip btn-chip" data-kind="concept" style="--chip-color:${KIND_COLORS.concept}">Concepts</button>
          <button class="tl-kind-chip btn-chip" data-kind="method"  style="--chip-color:${KIND_COLORS.method}">Methods</button>
          <button class="tl-kind-chip btn-chip" data-kind="dataset" style="--chip-color:${KIND_COLORS.dataset}">Datasets</button>
          <span class="tl-gap-toggle-wrap">
            <label class="tl-toggle-label">
              <input type="checkbox" class="tl-gap-toggle" checked>
              Gap overlay
            </label>
          </span>
        </div>
        <div class="tl-legend">
          <span class="tl-legend-item">
            <span class="tl-diamond tl-diamond-open"></span> Open gap
          </span>
          <span class="tl-legend-item">
            <span class="tl-diamond tl-diamond-partial"></span> Partial
          </span>
          <span class="tl-legend-item">
            <span class="tl-diamond tl-diamond-addressed"></span> Addressed
          </span>
          <span class="tl-legend-item">
            <span class="tl-diamond tl-diamond-draft"></span> Your draft ★
          </span>
        </div>
        <button class="tl-refresh-gaps-btn btn-sm btn-secondary">Refresh gaps</button>
      </div>
      <div class="tl-body tl-skeleton">
        <div class="tl-skel-lane"></div>
        <div class="tl-skel-lane"></div>
        <div class="tl-skel-lane"></div>
      </div>
      <div class="tl-detail-panel graph-detail-panel" style="display:none;"></div>
    </div>`;
}

function _buildCanvasHtml(layout, titleMap, gapIndex) {
  const totalW = layout.width;

  // ---- Year header ----
  let yearCells = '';
  for (const tick of layout.yearTicks) {
    yearCells += `<div class="tl-year-cell" style="left:${tick.x - OPTS.yearWidth / 2}px;width:${OPTS.yearWidth}px">${escapeHtml(String(tick.year))}</div>`;
  }

  // ---- Gap lane ----
  let gapDiamonds = '';
  for (const m of layout.gapLane.markers) {
    const entry = gapIndex.get(m.gap_id);
    const stmt  = entry ? entry.gap.statement : m.gap_id;
    const tooltipText = stmt.length > 80 ? stmt.slice(0, 77) + '…' : stmt;
    let cls = 'tl-gap-diamond';
    if (m.draftAddresses) cls += ' tl-diamond-draft';
    else if (m.status === 'addressed') cls += ' tl-diamond-addressed';
    else if (m.status === 'partially') cls += ' tl-diamond-partial';
    else cls += ' tl-diamond-open';
    gapDiamonds += `<div class="${cls}" data-gap-id="${escapeHtml(m.gap_id)}" style="left:${m.x}px;top:${layout.gapLane.y}px" title="${escapeHtml(tooltipText)}"></div>`;
  }

  // ---- Track lanes ----
  let laneRows = '';
  for (const lane of layout.lanes) {
    // Dots
    let dots = '';
    for (const pt of lane.points) {
      const color = KIND_COLORS[lane.kind] || '#7d8590';
      const title = escapeHtml(titleMap.get(pt.paper_id) || pt.paper_id);
      dots += `<div class="tl-dot" data-paper-id="${escapeHtml(pt.paper_id)}" style="left:${pt.x}px;top:${lane.y}px;background:${color}" title="${title}"></div>`;
    }

    // Segments
    let segs = '';
    for (const seg of lane.segments) {
      const color  = KIND_COLORS[lane.kind] || '#7d8590';
      const segW   = seg.x2 - seg.x1;
      segs += `<div class="tl-segment" style="left:${seg.x1}px;top:${seg.y}px;width:${segW}px;background:${color}"></div>`;
    }

    laneRows += `
      <div class="tl-lane-row" data-kind="${escapeHtml(lane.kind)}" style="height:${OPTS.laneHeight}px">
        ${dots}${segs}
      </div>`;
  }

  // ---- Density row ----
  let densityTicks = '';
  for (const d of layout.paperDensity) {
    densityTicks += `<div class="tl-density-tick" style="left:${d.x}px">
      <span class="tl-density-count">${escapeHtml(String(d.count))}</span>
    </div>`;
  }

  // ---- Lane labels (sticky left) ----
  let labels = '';
  // Gap label
  labels += `<div class="tl-lane-label tl-gap-lane-label" style="top:${layout.gapLane.y - 10}px">Gaps</div>`;
  for (const lane of layout.lanes) {
    labels += `<div class="tl-lane-label" data-kind="${escapeHtml(lane.kind)}" style="top:${lane.y - 10}px">${escapeHtml(lane.label)}</div>`;
  }

  const canvasHeight = layout.lanes.length > 0
    ? layout.lanes[layout.lanes.length - 1].y + OPTS.laneHeight
    : OPTS.laneHeight * 2;

  return `
    <div class="tl-canvas-outer">
      <div class="tl-labels-col" style="width:${OPTS.labelWidth}px;height:${canvasHeight}px">
        ${labels}
      </div>
      <div class="tl-canvas-wrap" style="overflow-x:auto;flex:1">
        <div class="tl-canvas-inner" style="position:relative;width:${totalW - OPTS.labelWidth}px;min-height:${canvasHeight}px">
          <div class="tl-year-header" style="position:sticky;top:0;width:${totalW - OPTS.labelWidth}px;height:32px;z-index:2">
            ${yearCells}
          </div>
          <div class="tl-gap-row" style="position:relative;height:${OPTS.laneHeight}px">
            ${gapDiamonds}
          </div>
          ${laneRows}
          <div class="tl-density-row" style="position:relative;height:32px">
            ${densityTicks}
          </div>
        </div>
      </div>
    </div>`;
}

// ---------------------------------------------------------------------------
// Gap index
// ---------------------------------------------------------------------------

function _buildGapIndex() {
  // Map gap_id -> { gap, paperEntry }
  const idx = new Map();
  if (!_gaps || !_gaps.papers) return idx;
  for (const paperEntry of _gaps.papers) {
    for (const gap of (paperEntry.gaps || [])) {
      idx.set(gap.gap_id, { gap, paperEntry });
    }
  }
  return idx;
}

// ---------------------------------------------------------------------------
// Gap detail panel
// ---------------------------------------------------------------------------

function _openGapDetail(gapId, gapIndex, titleMap) {
  if (!_detailPanel || !_el) return;

  const entry = gapIndex.get(gapId);
  if (!entry) return;

  const { gap, paperEntry } = entry;
  const inDraft = _gaps && (_gaps.draft_addresses || []).includes(gapId);
  const resolution = gap.resolution || { status: 'open' };

  // Resolved-by paper title
  let resolvedByHtml = '';
  if (resolution.status === 'addressed' && resolution.resolved_by) {
    const resTitle = escapeHtml(titleMap.get(resolution.resolved_by) || resolution.resolved_by);
    resolvedByHtml = `<a href="#/library" class="tl-detail-link" data-paper-id="${escapeHtml(resolution.resolved_by)}">${resTitle}</a>`;
  }

  const statusLabel = {
    addressed: 'Addressed',
    partially:  'Partially addressed',
    open:       'Open',
  }[resolution.status] || 'Open';

  const verifiedBadge = gap.evidence && gap.evidence.verified
    ? '<span class="tl-badge tl-badge-verified">Verified</span>'
    : '<span class="tl-badge tl-badge-unverified">Unverified</span>';

  _detailPanel.innerHTML = `
    <div class="tl-detail-inner">
      <div class="tl-detail-header">
        <span class="tl-kind-chip-sm btn-chip">${escapeHtml(gap.kind || 'gap')}</span>
        <button class="tl-detail-close" title="Close">×</button>
      </div>
      ${inDraft ? `<div class="tl-draft-banner">Your draft addresses this gap ★</div>` : ''}
      <p class="tl-detail-statement">${escapeHtml(gap.statement)}</p>
      ${gap.evidence && gap.evidence.quote ? `
        <blockquote class="tl-detail-quote">
          ${escapeHtml(gap.evidence.quote)}
          ${verifiedBadge}
        </blockquote>` : ''}
      <div class="tl-detail-resolution">
        <span class="tl-resolution-status tl-res-${escapeHtml(resolution.status || 'open')}">${escapeHtml(statusLabel)}</span>
        ${resolvedByHtml ? `<span class="tl-resolution-by">by ${resolvedByHtml}</span>` : ''}
        ${resolution.rationale ? `<p class="tl-resolution-rationale">${escapeHtml(resolution.rationale)}</p>` : ''}
      </div>
      <div class="tl-detail-actions">
        <button class="btn-primary tl-discuss-btn" data-paper-id="${escapeHtml(paperEntry.paper_id)}">Discuss</button>
        <button class="btn-secondary tl-view-paper-btn" data-paper-id="${escapeHtml(paperEntry.paper_id)}">View paper</button>
      </div>
    </div>`;

  _detailPanel.style.display = '';

  // Close button
  _detailPanel.querySelector('.tl-detail-close')
    .addEventListener('click', _closeDetail);

  // Discuss button
  _detailPanel.querySelector('.tl-discuss-btn')
    .addEventListener('click', (e) => {
      const paperId = e.currentTarget.dataset.paperId;
      window.dispatchEvent(new CustomEvent('rc:discuss', {
        detail: { type: 'gaps', id: paperId },
        bubbles: true,
      }));
    });

  // View paper button — library handoff
  _detailPanel.querySelector('.tl-view-paper-btn')
    .addEventListener('click', (e) => {
      const paperId = e.currentTarget.dataset.paperId;
      _openPaperDrawer(paperId);
    });

  // Resolved-by link click
  const detailLink = _detailPanel.querySelector('.tl-detail-link[data-paper-id]');
  if (detailLink) {
    detailLink.addEventListener('click', (e) => {
      e.preventDefault();
      _openPaperDrawer(detailLink.dataset.paperId);
    });
  }
}

function _closeDetail() {
  if (_detailPanel) _detailPanel.style.display = 'none';
}

// ---------------------------------------------------------------------------
// Library drawer handoff
// ---------------------------------------------------------------------------

function _openPaperDrawer(paperId) {
  window.__rcPendingPaper = paperId;
  window.dispatchEvent(new CustomEvent('rc:open-paper', {
    detail: { paper_id: paperId },
    bubbles: true,
  }));
  window.location.hash = '#/library';
}
