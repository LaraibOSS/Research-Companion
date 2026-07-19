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
  linkTargetOptions,
} from '../citationsHelpers.js';
import { citationDownloadTargets } from '../activityHelpers.js';
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

  // Subscribe: if open and stale, refetch; also re-render on activity changes
  _unsubscribe = storeRef.subscribe(['citations', 'activity'], () => {
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
  const { citationCoverage, activeJobs, papers } = _storeRef.getState();
  const downloadTargets = citationDownloadTargets(activeJobs);
  _panel.innerHTML = _buildHtml(citationCoverage, downloadTargets, papers);
  _bindEvents(citationCoverage);
}

function _buildHtml(coverage, downloadTargets = new Set(), papers = null) {
  const counts = coverageCounts(coverage);
  const refs = coverage && Array.isArray(coverage.references) ? coverage.references : [];
  const source = coverage && coverage.source;
  const avail = availableEntries(coverage);
  const availLen = avail.length;
  // Mark entries that are currently downloading
  const markedRefs = refs.map(r => ({
    ...r,
    downloading: !!(r.add_target && downloadTargets.has(r.add_target)),
  }));
  const grouped = groupByStatus(markedRefs);
  const missing = missingCount(counts);

  // Header title — the in_library/total headline plus a breakdown so the
  // "Add all" count reconciles with what's shown (fetchable vs. unresolved).
  const breakdownParts = [];
  if (counts.available > 0) breakdownParts.push(`${counts.available} fetchable`);
  if (counts.unresolved > 0) breakdownParts.push(`${counts.unresolved} unresolved`);
  const breakdown = breakdownParts.length > 0 ? ` · ${breakdownParts.join(' · ')}` : '';
  const headerTitle = counts.total > 0
    ? `Cited references — ${counts.in_library} of ${counts.total} in library${breakdown}`
    : 'Cited references';

  // Related-work amber note
  const relatedWorkNote = source === 'related_work'
    ? `<div class="citations-note-amber">List from related-work extraction — full bibliography could not be parsed; coverage may be incomplete.</div>`
    : '';

  // Auto-download note (v0.5.1): downloads are automatic unless turned off in
  // Settings — the panel's job is to present what could NOT be fetched.
  const settings = _storeRef.getState().settings || {};
  const autoNote = (settings.auto_add_citations !== false && counts.total > 0)
    ? `<div class="citations-note-muted">Missing papers download automatically — anything listed as Unresolved could not be fetched.</div>`
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
    bodyHtml = grouped.map(entry => _renderRow(entry, papers)).join('');
  }

  return `
    <div class="citations-header">
      <div class="citations-title-row">
        <span class="citations-title">${escapeHtml(headerTitle)}</span>
        <button class="citations-close btn btn-secondary btn-sm" aria-label="Close citations panel">&times;</button>
      </div>
      ${relatedWorkNote}
      ${autoNote}
      <div class="citations-actions">
        ${addAllBtn}
        ${resolveBtn}
      </div>
    </div>
    <div class="citations-body">
      ${bodyHtml}
    </div>`;
}

/**
 * @param {object} entry — reference entry
 * @param {Map|Array|null} papers — library papers snapshot (store.papers Map,
 *   the same shape/source _buildLinkPicker uses) for resolving the matched
 *   paper's title without a per-row fetch.
 */
function _renderRow(entry, papers = null) {
  const chip = statusChip(entry);
  const rawTitle = (entry.resolved && entry.resolved.title)
    || entry.title
    || _truncate(entry.raw || '', 90);
  const year = (entry.resolved && entry.resolved.year) || entry.year || '';
  const rawAttr = escapeHtml(entry.raw || '');

  const addBtn = entry.status === 'available' && entry.add_target
    ? `<button class="btn btn-accent btn-sm citations-row-add" data-index="${escapeHtml(String(entry.index))}">Add</button>`
    : '';

  // "Link…" is offered for any row not already in the library (unchecked /
  // unresolved / available). Available rows keep Add alongside it.
  const linkBtn = entry.status !== 'in_library'
    ? `<button class="btn btn-secondary btn-sm citations-row-link" data-index="${escapeHtml(String(entry.index))}">Link…</button>`
    : '';

  // Manually-linked rows: keep the "In library ✓" chip but flag provenance,
  // and offer Unlink (only manual links are reversible — auto matches aren't).
  const manual = entry.match_kind === 'manual';
  const chipTitle = manual ? ' title="manually linked"' : '';
  const manualMark = manual
    ? `<span class="citation-manual-mark" title="manually linked">manually linked</span>`
    : '';
  const unlinkBtn = manual
    ? `<button class="btn btn-secondary btn-sm citations-row-unlink" data-index="${escapeHtml(String(entry.index))}">Unlink</button>`
    : '';

  // For in_library rows, show what this reference actually resolved to — the
  // matched paper's title, looked up from the already-fetched library
  // snapshot (no per-row fetch; same `papers` source _buildLinkPicker reads
  // from state.papers).
  let linkedTitleLine = '';
  if (entry.status === 'in_library' && entry.matched_paper_id) {
    const matched = papers instanceof Map ? papers.get(entry.matched_paper_id) : null;
    const matchedTitle = (matched && matched.title) || entry.matched_paper_id;
    linkedTitleLine = `<div class="citation-row-detail">→ ${escapeHtml(matchedTitle)}</div>`;
  }

  return `
    <div class="citation-row" data-index="${escapeHtml(String(entry.index))}" title="${rawAttr}">
      <div class="citation-row-main">
        <span class="citation-row-title">${escapeHtml(rawTitle)}</span>
        ${year ? `<span class="citation-row-year">${escapeHtml(String(year))}</span>` : ''}
      </div>
      ${linkedTitleLine}
      <div class="citation-row-meta">
        <span class="citation-chip ${escapeHtml(chip.cls)}"${chipTitle}>${escapeHtml(chip.label)}</span>
        ${manualMark}
        ${addBtn}
        ${linkBtn}
        ${unlinkBtn}
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

  // Per-row Unlink buttons — only rendered for match_kind === 'manual' rows.
  // Mirrors the link flow: POST, push the returned coverage into the store
  // (re-renders the panel), toast on success/failure. No confirm() — a link
  // is trivially re-creatable via "Link…", so there's nothing to lose.
  _panel.querySelectorAll('.citations-row-unlink').forEach(btn => {
    btn.addEventListener('click', async () => {
      const idxStr = btn.dataset.index;
      const idx = Number(idxStr);
      btn.disabled = true;
      btn.textContent = 'Unlinking…';
      try {
        const payload = await _apiRef.unlinkCitation(idx);
        _storeRef.setCitationCoverage(payload);
        showToast('Unlinked', 'info');
      } catch (err) {
        showToast(err.message || 'Unlink failed', 'error');
        btn.disabled = false;
        btn.textContent = 'Unlink';
      }
    });
  });

  // Per-row "Link…" buttons — toggle an inline picker under the row.
  _panel.querySelectorAll('.citations-row-link').forEach(btn => {
    btn.addEventListener('click', () => {
      const idxStr = btn.dataset.index;
      const rowEl = _findRow(idxStr);
      if (!rowEl) return;
      const existing = rowEl.querySelector('.citations-link-picker');
      if (existing) {           // toggle off
        existing.remove();
        return;
      }
      const refs = coverage && Array.isArray(coverage.references) ? coverage.references : [];
      const entry = refs.find(r => String(r.index) === idxStr);
      if (!entry) return;
      rowEl.appendChild(_buildLinkPicker(entry));
    });
  });
}

/**
 * Build the inline "Link…" picker for a citation row: a disclaimer line + a
 * <select> of library papers. Linking on `change` calls the backend, updates
 * coverage (which re-renders the panel) and refreshes the library snapshot so
 * the backfilled year shows.
 * @param {object} entry — the reference entry (has .index)
 * @returns {HTMLElement}
 */
function _buildLinkPicker(entry) {
  const state = _storeRef.getState();
  const papers = state.papers instanceof Map
    ? [...state.papers.values()]
    : (Array.isArray(state.papers) ? state.papers : []);
  const options = linkTargetOptions(papers, state.draftId);

  const wrap = document.createElement('div');
  wrap.className = 'citations-link-picker';

  const disclaimer = document.createElement('div');
  disclaimer.className = 'citations-link-disclaimer';
  disclaimer.textContent =
    "Titles & years here come from your draft's citations, not the papers themselves.";
  wrap.appendChild(disclaimer);

  const select = document.createElement('select');
  select.className = 'citations-link-select';
  const placeholder = document.createElement('option');
  placeholder.value = '';
  placeholder.textContent = 'Pick the library paper…';
  select.appendChild(placeholder);
  for (const opt of options) {
    const o = document.createElement('option');
    o.value = opt.paperId;
    o.textContent = opt.label;
    select.appendChild(o);
  }

  select.addEventListener('change', async () => {
    const paperId = select.value;
    if (!paperId) return;                 // ignore the placeholder
    select.disabled = true;
    try {
      const payload = await _apiRef.linkCitation(entry.index, paperId);
      // Notifies ['citations'] -> panel re-renders (this picker is discarded).
      _storeRef.setCitationCoverage(payload);
      // Refresh the library snapshot so the backfilled year shows.
      try {
        const fresh = await _apiRef.getPapers();
        _refreshPapers(fresh);
      } catch (e) {
        console.warn('[citationsPanel] library refresh failed', e);
      }
      const linked = papers.find(p => p.paper_id === paperId);
      const title = (linked && linked.title) || paperId;
      showToast('Linked — ' + title, 'info');
    } catch (err) {
      showToast(err.message || 'Link failed', 'error');
      select.disabled = false;
    }
  });

  wrap.appendChild(select);
  return wrap;
}

/**
 * Merge a fresh GET /api/papers array into the store's papers Map and notify.
 * The store has no setPapers; this mirrors the merge-and-notify pattern used by
 * the add/patch flows (main.js snapshotRefresher, library.js metadata save).
 * @param {Array} papers
 */
function _refreshPapers(papers) {
  if (!Array.isArray(papers)) return;
  const s = _storeRef.getState();
  for (const p of papers) {
    if (!p || !p.paper_id) continue;
    s.papers.set(p.paper_id, { ...s.papers.get(p.paper_id), ...p });
  }
  _storeRef.notify(['papers']);
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
