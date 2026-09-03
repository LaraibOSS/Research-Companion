/**
 * views/gaps.js — Dedicated Gaps section (gap-analysis-section, Phase 1 of
 * Research Ideation).
 * Route: /gaps
 *
 * Renders the synthesized cross-corpus gap THEMES (GET /api/gaps `themes`)
 * as a readable, filterable, sortable bullet list — complementary to the
 * Timeline's diamond overlay, which is unchanged.
 *
 * Layout: header (count + Refresh button) -> filter chips (type, status) +
 * sort buttons (score/recency/frequency) -> bullet rows (type + fws badges,
 * citation chips, status pill, frequency) -> empty state.
 */

import * as store from '../store.js';
import * as api from '../api.js';
import { escapeHtml } from '../format.js';
import { showToast } from '../components/toast.js';
import {
  gapThemeRowModel,
  sortGapThemes,
  filterGapThemes,
} from '../gapHelpers.js';

// ---------------------------------------------------------------------------
// Module state
// ---------------------------------------------------------------------------

let _el = null;
let _unsubs = [];
let _gaps = null;          // last fetched GET /api/gaps payload
let _sortCol = 'score';
let _sortDir = 'desc';
let _typeFilter = 'all';
let _statusFilter = 'all';

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

export function mount(el) {
  _el = el;
  _sortCol = 'score';
  _sortDir = 'desc';
  _typeFilter = 'all';
  _statusFilter = 'all';

  el.innerHTML = `<div class="gaps-view"><div class="gaps-loading muted">Loading gaps…</div></div>`;

  // Subscribe to gaps_updated SSE events (same 'gaps' topic the timeline uses)
  _unsubs.push(store.subscribe(['gaps'], async () => {
    try {
      _gaps = await api.getGaps();
    } catch (err) {
      console.warn('[gaps] refetch failed:', err);
    }
    _render();
  }));

  _fetch();
}

export function unmount() {
  for (const u of _unsubs) u();
  _unsubs = [];
  _el = null;
}

// ---------------------------------------------------------------------------
// Data fetching
// ---------------------------------------------------------------------------

async function _fetch() {
  try {
    _gaps = await api.getGaps();
  } catch (err) {
    console.warn('[gaps] fetch failed:', err);
  }
  _render();
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

function _render() {
  if (!_el) return;

  const themes = (_gaps && Array.isArray(_gaps.themes)) ? _gaps.themes : [];
  const draftAddresses = (_gaps && Array.isArray(_gaps.draft_addresses)) ? _gaps.draft_addresses : [];

  const rows = themes.map(t => gapThemeRowModel(t, draftAddresses));
  const filtered = filterGapThemes(rows, { type: _typeFilter, status: _statusFilter });
  const sorted = sortGapThemes(filtered, _sortCol, _sortDir);

  _el.innerHTML = `
    <div class="gaps-view">
      <div class="gaps-header">
        <div class="gaps-header-main">
          <h2>Gaps <span class="gaps-count">${escapeHtml(String(sorted.length))}</span></h2>
          <p class="muted">Research gaps synthesized across your library — what's missing, and whether it's still open.</p>
        </div>
        <button class="btn btn-secondary btn-sm gaps-refresh-btn">Refresh gaps</button>
      </div>
      ${themes.length > 0 ? _controlsHtml() : ''}
      <div class="gaps-body">
        ${sorted.length === 0 ? _emptyHtml(themes.length > 0) : sorted.map(_rowHtml).join('')}
      </div>
    </div>`;

  _bindEvents();
}

function _controlsHtml() {
  return `
    <div class="gaps-controls">
      <div class="gaps-filter-chips filter-chips">
        <span class="muted gaps-chips-label">Type:</span>
        ${_chip('type', 'all', 'All', _typeFilter)}
        ${_chip('type', 'limitation', 'Limitation', _typeFilter)}
        ${_chip('type', 'future_work', 'Future work', _typeFilter)}
      </div>
      <div class="gaps-filter-chips filter-chips">
        <span class="muted gaps-chips-label">Status:</span>
        ${_chip('status', 'all', 'All', _statusFilter)}
        ${_chip('status', 'open', 'Open', _statusFilter)}
        ${_chip('status', 'partial', 'Partial', _statusFilter)}
        ${_chip('status', 'addressed', 'Addressed', _statusFilter)}
      </div>
      <div class="gaps-sort-seg" role="group" aria-label="Sort by">
        ${_sortBtn('score', 'Relevance')}
        ${_sortBtn('recency', 'Recency')}
        ${_sortBtn('frequency', 'Frequency')}
      </div>
    </div>`;
}

function _emptyHtml(hasAnyThemes) {
  const msg = hasAnyThemes
    ? 'No gaps match this filter.'
    : 'Add papers, then Refresh to surface research gaps.';
  return `<div class="gaps-empty muted">${escapeHtml(msg)}</div>`;
}

function _chip(dim, value, label, current) {
  const active = current === value ? ' chip-active' : '';
  return `<button class="chip${active}" data-${dim}-filter="${escapeHtml(value)}">${escapeHtml(label)}</button>`;
}

function _sortBtn(col, label) {
  const active = _sortCol === col;
  const arrow = active ? (_sortDir === 'asc' ? ' &#9650;' : ' &#9660;') : '';
  return `<button class="gaps-sort-btn${active ? ' gaps-sort-btn--active' : ''}" data-sort-col="${col}">${escapeHtml(label)}${arrow}</button>`;
}

function _rowHtml(r) {
  const citationChips = r.citations.map(c => `
    <button class="chip gaps-citation-chip" data-paper-id="${escapeHtml(c.paperId)}" title="${escapeHtml(c.title)}">
      ${escapeHtml(c.title)}${c.year != null ? ` (${escapeHtml(String(c.year))})` : ''}
    </button>`).join('');

  return `
    <div class="gaps-row" data-theme-id="${escapeHtml(r.id)}">
      <div class="gaps-row-top">
        <span class="chip gaps-type-chip gaps-type-${escapeHtml(r.typeKey)}">${escapeHtml(r.typeLabel)}</span>
        <span class="chip gaps-fws-chip">${escapeHtml(r.fwsLabel)}</span>
        <span class="gaps-status-pill gaps-status-${escapeHtml(r.statusKey)}">${escapeHtml(r.statusLabel)}</span>
        ${r.addressedByDraft ? '<span class="gaps-draft-badge" title="Your draft addresses this">&#9733; Your draft</span>' : ''}
        <span class="gaps-frequency muted" title="Papers raising this gap">${escapeHtml(String(r.frequency))} ${r.frequency === 1 ? 'paper' : 'papers'}</span>
      </div>
      <div class="gaps-bullet">${escapeHtml(r.bullet || r.title)}</div>
      <div class="gaps-citations">${citationChips}</div>
    </div>`;
}

// ---------------------------------------------------------------------------
// Event binding
// ---------------------------------------------------------------------------

function _bindEvents() {
  if (!_el) return;

  _el.querySelectorAll('[data-type-filter]').forEach(btn => {
    btn.addEventListener('click', () => {
      _typeFilter = btn.dataset.typeFilter;
      _render();
    });
  });

  _el.querySelectorAll('[data-status-filter]').forEach(btn => {
    btn.addEventListener('click', () => {
      _statusFilter = btn.dataset.statusFilter;
      _render();
    });
  });

  _el.querySelectorAll('[data-sort-col]').forEach(btn => {
    btn.addEventListener('click', () => {
      const col = btn.dataset.sortCol;
      if (_sortCol === col) {
        _sortDir = _sortDir === 'asc' ? 'desc' : 'asc';
      } else {
        _sortCol = col;
        _sortDir = 'desc';
      }
      _render();
    });
  });

  _el.querySelectorAll('.gaps-citation-chip').forEach(btn => {
    btn.addEventListener('click', () => {
      const paperId = btn.dataset.paperId;
      if (!paperId) return;
      window.__rcPendingPaper = paperId;
      window.dispatchEvent(new CustomEvent('rc:open-paper', {
        detail: { paperId },
        bubbles: true,
      }));
      window.location.hash = '#/library';
    });
  });

  const refreshBtn = _el.querySelector('.gaps-refresh-btn');
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
