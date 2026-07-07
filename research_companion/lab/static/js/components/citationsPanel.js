/**
 * components/citationsPanel.js — Citation Coverage panel (W5-C3).
 *
 * Mounted ONCE from main.js. Fixed-right panel, width 400px, z-index 380.
 * Non-modal — page behind stays interactive.
 * Toggled by CustomEvent('rc:toggle-citations') + Esc closes.
 */

import * as store from '../store.js';
import * as api from '../api.js';
import { showToast } from './toast.js';
import {
  coverageCounts,
  missingCount,
  statusChip,
  availableEntries,
  groupByStatus,
} from '../citationsHelpers.js';
import { escapeHtml } from '../format.js';

// ---------------------------------------------------------------------------
// Panel state
// ---------------------------------------------------------------------------

let _panel = null;        // HTMLElement
let _open  = false;
let _fetched = false;     // lazy-fetch on first open
let _apiRef = api;
let _storeRef = store;
let _unsubscribe = null;
let _updating = false;    // guard: true while fetch is in-flight

// ---------------------------------------------------------------------------
// Exported mount
// ---------------------------------------------------------------------------

/**
 * Mount the citations panel once into document.body.
 * @param {object} storeRef  — store module (injected for testability)
 * @param {object} apiRef    — api module (injected for testability)
 */
export function mountCitationsPanel(storeRef = store, apiRef = api) {
  if (_panel) return;

  _apiRef   = apiRef;
  _storeRef = storeRef;

  _panel = document.createElement('div');
  _panel.id = 'citations-panel';
  _panel.className = 'citations-panel';
  _panel.setAttribute('aria-label', 'Cited papers panel');
  _panel.setAttribute('role', 'complementary');
  _render();
  document.body.appendChild(_panel);

  // Toggle event
  window.addEventListener('rc:toggle-citations', () => _toggle());

  // Esc closes when open
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && _open) _close();
  });

  // Outside-click closes
  document.addEventListener('mousedown', (e) => {
    if (_open && _panel && !_panel.contains(e.target)) _close();
  });

  // Subscribe: if open and stale, refetch
  _unsubscribe = storeRef.subscribe('citations', () => {
    const { citationCoverage } = storeRef.getState();
    if (_open && !_updating && citationCoverage && citationCoverage.stale) {
      _fetchAndUpdate();
      return;
    }
    _render();
  });
}

// ---------------------------------------------------------------------------
// Toggle / open / close
// ---------------------------------------------------------------------------

function _toggle() {
  if (_open) {
    _close();
  } else {
    _openPanel();
  }
}

function _openPanel() {
  _open = true;
  _panel.classList.add('open');
  if (!_fetched) {
    _fetched = true;
    _fetchAndUpdate();
  }
}

function _close() {
  _open = false;
  _panel.classList.remove('open');
}

// ---------------------------------------------------------------------------
// Fetch
// ---------------------------------------------------------------------------

async function _fetchAndUpdate() {
  _updating = true;
  try {
    const data = await _apiRef.getDraftCitations();
    if (data) {
      _storeRef.setCitationCoverage(data);
    }
  } catch (err) {
    showToast('Failed to load citation coverage', 'error');
    console.error('[citationsPanel] fetch error', err);
  } finally {
    _updating = false;
    _render();
  }
}

// ---------------------------------------------------------------------------
// Render
// ---------------------------------------------------------------------------

function _render() {
  if (!_panel) return;
  const { citationCoverage } = _storeRef.getState();
  _panel.innerHTML = _buildHtml(citationCoverage);
  _bindEvents(citationCoverage);
}

function _buildHtml(coverage) {
  const counts = coverageCounts(coverage);
  const refs = coverage && Array.isArray(coverage.references) ? coverage.references : [];
  const source = coverage && coverage.source;
  const avail = availableEntries(coverage);
  const availLen = avail.length;
  const grouped = groupByStatus(refs);
  const missing = missingCount(counts);

  // Header title
  const headerTitle = counts.total > 0
    ? `Cited papers — ${counts.in_library} of ${counts.total} in library`
    : 'Cited papers';

  // Related-work amber note
  const relatedWorkNote = source === 'related_work'
    ? `<div class="citations-note-amber">List from related-work extraction — full bibliography could not be parsed; coverage may be incomplete.</div>`
    : '';

  // "Add all" button
  const addAllBtn = availLen > 0
    ? `<button class="btn btn-accent btn-sm citations-add-all">Add all (${escapeHtml(String(availLen))})</button>`
    : '';

  // "Resolve missing" button
  const resolveBtn = counts.unchecked > 0
    ? `<button class="btn btn-secondary btn-sm citations-resolve">Resolve missing (${escapeHtml(String(counts.unchecked))})</button>`
    : '';

  // Body
  let bodyHtml;
  if (refs.length === 0) {
    const emptyMsg = coverage && coverage.draft_paper_id
      ? 'No citations found. If your draft has a bibliography, try resolving references.'
      : 'No draft is set. Upload your draft paper to see citation coverage.';
    bodyHtml = `<div class="citations-empty">${escapeHtml(emptyMsg)}</div>`;
  } else {
    bodyHtml = grouped.map(entry => _renderRow(entry)).join('');
  }

  return `
    <div class="citations-header">
      <div class="citations-title-row">
        <span class="citations-title">${escapeHtml(headerTitle)}</span>
        <button class="citations-close btn btn-secondary btn-sm" aria-label="Close citations panel">&times;</button>
      </div>
      ${relatedWorkNote}
      <div class="citations-actions">
        ${addAllBtn}
        ${resolveBtn}
      </div>
    </div>
    <div class="citations-body">
      ${bodyHtml}
    </div>`;
}

function _renderRow(entry) {
  const chip = statusChip(entry);
  const rawTitle = (entry.resolved && entry.resolved.title)
    || entry.title
    || _truncate(entry.raw || '', 90);
  const year = (entry.resolved && entry.resolved.year) || entry.year || '';
  const rawAttr = escapeHtml(entry.raw || '');

  const addBtn = entry.status === 'available' && entry.add_target
    ? `<button class="btn btn-accent btn-sm citations-row-add" data-index="${escapeHtml(String(entry.index))}">Add</button>`
    : '';

  return `
    <div class="citation-row" data-index="${escapeHtml(String(entry.index))}" title="${rawAttr}">
      <div class="citation-row-main">
        <span class="citation-row-title">${escapeHtml(rawTitle)}</span>
        ${year ? `<span class="citation-row-year">${escapeHtml(String(year))}</span>` : ''}
      </div>
      <div class="citation-row-meta">
        <span class="citation-chip ${escapeHtml(chip.cls)}">${escapeHtml(chip.label)}</span>
        ${addBtn}
      </div>
    </div>`;
}

function _truncate(str, maxLen) {
  if (str.length <= maxLen) return str;
  return str.slice(0, maxLen - 1) + '…';
}

// ---------------------------------------------------------------------------
// Event binding
// ---------------------------------------------------------------------------

function _bindEvents(coverage) {
  if (!_panel) return;

  // Close button
  _panel.querySelector('.citations-close')?.addEventListener('click', _close);

  // Add all
  _panel.querySelector('.citations-add-all')?.addEventListener('click', async () => {
    const avail = availableEntries(coverage);
    if (avail.length === 0) return;
    showToast(`Adding ${avail.length} paper${avail.length === 1 ? '' : 's'}…`, 'info');
    for (const entry of avail) {
      // Mark row as queued
      const rowEl = _findRow(entry.index);
      if (rowEl) rowEl.querySelector('.citation-chip').textContent = 'Queued…';
      try {
        await _apiRef.addPaper(entry.add_target);
        if (rowEl) rowEl.querySelector('.citation-chip').textContent = 'Added ✓';
      } catch (err) {
        const msg = err.message || 'Error';
        if (rowEl) {
          rowEl.querySelector('.citation-chip').textContent = 'Failed';
          rowEl.querySelector('.citation-chip').title = escapeHtml(msg);
        }
      }
    }
  });

  // Resolve missing
  _panel.querySelector('.citations-resolve')?.addEventListener('click', async () => {
    const counts = coverageCounts(coverage);
    try {
      await _apiRef.resolveCitations();
      showToast(`Resolving ${counts.unchecked} reference${counts.unchecked === 1 ? '' : 's'}…`, 'info');
    } catch (err) {
      if (err && err.status === 409) {
        showToast('Resolution already in progress.', 'info');
      } else {
        showToast('Failed to start resolution.', 'error');
      }
    }
  });

  // Per-row add buttons
  _panel.querySelectorAll('.citations-row-add').forEach(btn => {
    btn.addEventListener('click', async () => {
      const idxStr = btn.dataset.index;
      const refs = coverage && Array.isArray(coverage.references) ? coverage.references : [];
      const entry = refs.find(r => String(r.index) === idxStr);
      if (!entry || !entry.add_target) return;
      btn.disabled = true;
      btn.textContent = 'Adding…';
      try {
        await _apiRef.addPaper(entry.add_target);
        btn.textContent = 'Added ✓';
        btn.classList.remove('btn-accent');
        btn.classList.add('btn-secondary');
      } catch (err) {
        btn.textContent = 'Failed';
        btn.disabled = false;
        showToast(err.message || 'Failed to add paper', 'error');
      }
    });
  });
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function _findRow(index) {
  if (!_panel) return null;
  let found = null;
  _panel.querySelectorAll('.citation-row').forEach(el => {
    if (el.dataset.index === String(index)) found = el;
  });
  return found;
}
