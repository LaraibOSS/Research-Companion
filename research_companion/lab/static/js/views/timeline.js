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
import { explainerBanner } from '../components/explainer.js';
import { tip } from '../glossary.js';
import { TIMELINE_HOWTO, TIMELINE_KINDS, hiddenPapersNote } from '../timelineGuide.js';

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

// yearStripH is the height of the year-header strip that sits ABOVE the canvas
// but NOT above the labels column. Row labels must be pushed down by it so the
// labels share the same vertical origin as the dots/segments (which live in
// .tl-canvas-inner, below the strip). Single source of truth for both the strip
// markup height and the label offset so they can never drift apart.
const OPTS = { yearWidth: 140, laneHeight: 56, labelWidth: 180, yearStripH: 32 };

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

export function mount(el) {
  _el = el;
  _hiddenKinds.clear();
  _showGaps    = true;
  _selectedGap = null;

  // Explainer banner (shown once until dismissed, via component)
  const banner = explainerBanner(
    'timeline',
    'How the field evolved — diamonds are gaps papers left open.',
  );

  el.innerHTML = _skeletonHtml();
  if (banner) el.prepend(banner);

  _detailPanel = el.querySelector('.tl-detail-panel');
  _canvasWrap  = el.querySelector('.tl-canvas-wrap');

  // Subscribe to store changes for paper titles
  _unsubs.push(store.subscribe(['papers'], _render));

  // Subscribe to gaps_updated SSE events — refetch and re-render
  _unsubs.push(store.subscribe(['gaps'], async () => {
    try {
      _gaps = await api.getGaps();
    } catch (err) {
      console.warn('[timeline] gaps refetch failed:', err);
    }
    _render();
  }));

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

  // Re-query DOM references after innerHTML rebuild (Fix LOW-4)
  _canvasWrap = _el.querySelector('.tl-canvas-wrap');
  _detailPanel = _el.querySelector('.tl-detail-panel');

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

  // Sync sticky year header scroll + label vertical offset (Fix MEDIUM-3)
  const yearStrip = _el.querySelector('.tl-year-strip');
  const labelsCol  = _el.querySelector('.tl-labels-col');
  if (_canvasWrap && yearStrip) {
    _canvasWrap.addEventListener('scroll', () => {
      yearStrip.scrollLeft = _canvasWrap.scrollLeft;
      if (labelsCol) {
        labelsCol.style.transform = `translateY(-${_canvasWrap.scrollTop}px)`;
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

// How to read the grid. The gap-diamond legend above explains the overlay, but
// nothing explained the grid itself -- what a row, a column or a dot is -- so
// the page read as decoration rather than data.
function _guideHtml() {
  const swatches = TIMELINE_KINDS.map(k =>
    `<span class="tl-guide-kind">
       <span class="tl-guide-dot" style="background:${KIND_COLORS[k.kind]}"></span>${escapeHtml(k.label)}
     </span>`).join('');
  const skipped = (_temporal && _temporal.skipped_papers_without_year) || 0;
  const hidden = hiddenPapersNote(skipped);
  const hiddenHtml = hidden.note
    ? `<div class="tl-guide-hidden">${escapeHtml(hidden.note)}</div>`
    : '';
  return `
    <div class="tl-guide">
      <p class="tl-guide-text">${escapeHtml(TIMELINE_HOWTO)}</p>
      <div class="tl-guide-key">${swatches}</div>
      ${hiddenHtml}
    </div>`;
}

function _skeletonHtml() {
  return `
    <div class="tl-root">
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
          <span class="tl-legend-item"${tip('gap')}>
            <span class="tl-diamond tl-diamond-open"></span> Open gap
          </span>
          <span class="tl-legend-item"${tip('gap')}>
            <span class="tl-diamond tl-diamond-partial"></span> Partial
          </span>
          <span class="tl-legend-item"${tip('gap')}>
            <span class="tl-diamond tl-diamond-addressed"></span> Addressed
          </span>
          <span class="tl-legend-item">
            <span class="tl-diamond tl-diamond-draft"></span> Your draft ★
          </span>
        </div>
        <button class="tl-refresh-gaps-btn btn-sm btn-secondary">Refresh gaps</button>
      </div>
      ${_guideHtml()}
      <div class="tl-body tl-skeleton">
        <div class="tl-skel-lane"></div>
        <div class="tl-skel-lane"></div>
        <div class="tl-skel-lane"></div>
      </div>
      <div class="tl-detail-panel graph-detail-panel" style="display:none;"></div>
    </div>`;
}

/**
 * Convert layout x (full-width coordinate, includes labelWidth) to
 * canvas-inner x (relative to the scrollable content, excludes labelWidth).
 * @param {number} x
 * @returns {number}
 */
function _relX(x) {
  return x - OPTS.labelWidth;
}

function _buildCanvasHtml(layout, titleMap, gapIndex) {
  const totalW   = layout.width;
  const innerW   = totalW - OPTS.labelWidth;   // width of the scrollable strip

  // ---- Year header (lives OUTSIDE canvas-inner as a sibling strip) ----
  let yearCells = '';
  for (const tick of layout.yearTicks) {
    // relX converts full-width coord -> inner coord; cell centred at tick
    const cellLeft = _relX(tick.x) - OPTS.yearWidth / 2;
    yearCells += `<div class="tl-year-cell" style="left:${cellLeft}px;width:${OPTS.yearWidth}px">${escapeHtml(String(tick.year))}</div>`;
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
    gapDiamonds += `<div class="${cls}" data-gap-id="${escapeHtml(m.gap_id)}" style="left:${_relX(m.x)}px;top:${layout.gapLane.y}px" title="${escapeHtml(tooltipText)}"></div>`;
  }

  // ---- Track lanes ----
  let laneRows = '';
  for (const lane of layout.lanes) {
    // Dots
    let dots = '';
    for (const pt of lane.points) {
      const color = KIND_COLORS[lane.kind] || '#7d8590';
      const title = escapeHtml(titleMap.get(pt.paper_id) || pt.paper_id);
      dots += `<div class="tl-dot" data-paper-id="${escapeHtml(pt.paper_id)}" style="left:${_relX(pt.x)}px;top:${lane.y}px;background:${color}" title="${title}"></div>`;
    }

    // Segments
    let segs = '';
    for (const seg of lane.segments) {
      const color  = KIND_COLORS[lane.kind] || '#7d8590';
      const segW   = seg.x2 - seg.x1;
      segs += `<div class="tl-segment" style="left:${_relX(seg.x1)}px;top:${seg.y}px;width:${segW}px;background:${color}"></div>`;
    }

    laneRows += `
      <div class="tl-lane-row" data-kind="${escapeHtml(lane.kind)}" style="height:${OPTS.laneHeight}px">
        ${dots}${segs}
      </div>`;
  }

  // ---- Density row (papers published per year) ----
  let densityTicks = '';
  for (const d of layout.paperDensity) {
    const label = `${d.count} ${d.count === 1 ? 'paper' : 'papers'}`;
    densityTicks += `<div class="tl-density-tick" style="left:${_relX(d.x)}px">
      <span class="tl-density-count">${escapeHtml(label)}</span>
    </div>`;
  }

  // ---- Lane labels (sticky left) ----
  // Offset by the year-strip height so labels align with the dots, which live in
  // .tl-canvas-inner (below the strip). Without this the "Gaps" label hides
  // behind the year header and every label sits above its row's dots.
  const labelTop = (y) => y - 10 + OPTS.yearStripH;
  let labels = '';
  // Gap label
  labels += `<div class="tl-lane-label tl-gap-lane-label" style="top:${labelTop(layout.gapLane.y)}px">Gaps</div>`;
  for (const lane of layout.lanes) {
    labels += `<div class="tl-lane-label" data-kind="${escapeHtml(lane.kind)}" style="top:${labelTop(lane.y)}px">${escapeHtml(lane.label)}</div>`;
  }
  // Density-row label (the per-year paper counts sit below the last lane).
  const densityRowTop = OPTS.laneHeight + layout.lanes.length * OPTS.laneHeight;
  labels += `<div class="tl-lane-label tl-density-lane-label" style="top:${labelTop(densityRowTop + 14)}px">Papers / year</div>`;

  const canvasHeight = layout.lanes.length > 0
    ? layout.lanes[layout.lanes.length - 1].y + OPTS.laneHeight
    : OPTS.laneHeight * 2;

  // Year strip is a SIBLING of tl-canvas-wrap (not inside), so it can be synced
  // via scrollLeft without fighting the overflow container (Fix MEDIUM-3).
  return `
    <div class="tl-canvas-outer">
      <div class="tl-labels-col" style="width:${OPTS.labelWidth}px;height:${canvasHeight + OPTS.yearStripH}px">
        ${labels}
      </div>
      <div class="tl-canvas-right" style="flex:1;display:flex;flex-direction:column;overflow:hidden">
        <div class="tl-year-strip" style="overflow:hidden;flex-shrink:0;height:${OPTS.yearStripH}px;position:relative">
          <div class="tl-year-header" style="width:${innerW}px;height:${OPTS.yearStripH}px;position:relative">
            ${yearCells}
          </div>
        </div>
        <div class="tl-canvas-wrap" style="overflow-x:auto;overflow-y:auto;flex:1">
          <div class="tl-canvas-inner" style="position:relative;width:${innerW}px;min-height:${canvasHeight}px">
            <div class="tl-gap-row" style="position:relative;height:${OPTS.laneHeight}px">
              ${gapDiamonds}
            </div>
            ${laneRows}
            <div class="tl-density-row" style="position:relative;height:32px">
              ${densityTicks}
            </div>
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
    detail: { paperId },
    bubbles: true,
  }));
  window.location.hash = '#/library';
}
