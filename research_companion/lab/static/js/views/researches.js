/**
 * views/researches.js — Researches overview screen (route #/researches, W4-F1).
 * Rebuilt as a sortable tracking table (feat/researches-tab, task 3).
 *
 * Sortable tracking table of all workspaces ("researches"):
 *   - inline create row at top (focused when the hash query has ?new=1)
 *   - one <tr> per research: name/active/draft badges, papers, draft,
 *     citation coverage, strength mini-bar, open items, draft-updated,
 *     last-activity, created and action buttons
 *   - clickable header cells toggle _sortCol/_sortDir and re-render
 *     (default: lastActivity desc)
 *   - click row / Open -> activate workspace + full page reload
 *     (clicking the already-active row navigates #/home instead)
 *   - per-row pencil -> inline rename (Enter/blur commits via PATCH)
 *   - per-row Archive -> PATCH archived:true; archived rows live in a
 *     collapsed <details> section below with an Unarchive button
 *   - per-row trash -> confirmDialog() then DELETE /api/workspaces/{id};
 *     reload if the server switched the active research, else refresh
 *
 * All workspace names and draft titles are user/server input -> escapeHtml.
 */

import * as store from '../store.js';
import * as api from '../api.js';
import { showToast } from '../components/toast.js';
import { confirmDialog } from '../components/confirmDialog.js';
import { escapeHtml, timeAgo } from '../format.js';
import {
  deleteConfirmMessage,
  splitWorkspaces,
  validateWorkspaceName,
  researchRowModel,
  sortResearchRows,
} from '../workspaceHelpers.js';

let _el = null;
let _unsub = null;
let _busy = false;       // guard: an activate/reload is already in flight
let _editingId = null;   // workspace id currently in inline-rename mode
let _sortCol = 'lastActivity';
let _sortDir = 'desc';

// Columns sortResearchRows understands; others render as plain (non-clickable) headers.
const _SORTABLE_COLS = new Set(['name', 'papers', 'coverage', 'lastActivity', 'created', 'draftUpdated']);

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

export function mount(el) {
  _el = el;
  _busy = false;
  _editingId = null;
  _unsub = store.subscribe('workspaces', _render);

  // Refresh the snapshot on entry (boot fetch may be stale or still in flight)
  api.getWorkspaces()
    .then(data => store.setWorkspaces(data))
    .catch(err => console.warn('[researches] workspaces fetch failed', err));

  _render();

  // ?new=1 -> focus the create input
  if (/[?&]new=1(&|$)/.test(window.location.hash)) {
    const input = _el.querySelector('#ws-create-input');
    if (input) input.focus();
  }
}

export function unmount() {
  if (_unsub) { _unsub(); _unsub = null; }
  _el = null;
}

// ---------------------------------------------------------------------------
// Render
// ---------------------------------------------------------------------------

function _render() {
  if (!_el) return;
  const { workspaces } = store.getState();
  const { list, activeId } = workspaces;
  const { active, archived } = splitWorkspaces(list, activeId);

  // Preserve create-input value/focus across store-driven re-renders
  const prevInput = _el.querySelector('#ws-create-input');
  const prevValue = prevInput ? prevInput.value : '';
  const hadFocus = prevInput && document.activeElement === prevInput;

  const rows = sortResearchRows(active.map(w => researchRowModel(w, activeId)), _sortCol, _sortDir);
  const archivedRows = sortResearchRows(archived.map(w => researchRowModel(w, activeId)), _sortCol, _sortDir);

  const isEmpty = rows.length === 0 && archivedRows.length === 0;

  const emptyHtml = isEmpty
    ? `<p class="ws-empty-hint muted">No researches yet &mdash; create one to get started.</p>`
    : '';

  const tableHtml = isEmpty ? '' : `
    <div class="researches-table-wrap">
      <table class="researches-table">
        <thead><tr>${_headerRowHtml()}</tr></thead>
        <tbody>${rows.map(_rowHtml).join('')}</tbody>
      </table>
    </div>`;

  const archivedHtml = archivedRows.length > 0
    ? `<details class="ws-archived">
         <summary>Archived (${archivedRows.length})</summary>
         <div class="researches-table-wrap">
           <table class="researches-table researches-table--archived">
             <thead><tr>${_headerRowHtml()}</tr></thead>
             <tbody>${archivedRows.map(r => _rowHtml(r, true)).join('')}</tbody>
           </table>
         </div>
       </details>`
    : '';

  _el.innerHTML = `
    <div class="researches-view">
      <div class="researches-header">
        <h2>Researches</h2>
        <p class="muted">Each research is a separate workspace — its own papers, draft and graph.</p>
      </div>
      <div class="ws-create-row">
        <input id="ws-create-input" type="text" maxlength="120"
               placeholder="Name a new research&hellip;" aria-label="New research name">
        <button id="ws-create-btn" class="btn btn-accent">Create</button>
      </div>
      ${emptyHtml}
      ${tableHtml}
      ${archivedHtml}
    </div>`;

  const input = _el.querySelector('#ws-create-input');
  if (input) {
    input.value = prevValue;
    if (hadFocus) input.focus();
  }

  _bindEvents();
}

// ---------------------------------------------------------------------------
// Header / sort
// ---------------------------------------------------------------------------

function _headerCell(col, label) {
  if (!_SORTABLE_COLS.has(col)) return `<th>${label}</th>`;
  const active = _sortCol === col;
  const arrow = active ? (_sortDir === 'asc' ? ' &#9650;' : ' &#9660;') : '';
  return `<th><button type="button" class="researches-sort-btn${active ? ' researches-sort-btn--active' : ''}"
            data-sort-col="${col}">${label}${arrow}</button></th>`;
}

function _headerRowHtml() {
  return [
    _headerCell('name', 'Research'),
    _headerCell('papers', 'Papers'),
    _headerCell('draft', 'Draft'),
    _headerCell('coverage', 'Citations'),
    _headerCell('strength', 'Strength'),
    _headerCell('openSuggestions', 'Open items'),
    _headerCell('draftUpdated', 'Draft updated'),
    _headerCell('lastActivity', 'Last activity'),
    _headerCell('created', 'Created'),
    _headerCell('actions', 'Actions'),
  ].join('');
}

// ---------------------------------------------------------------------------
// Row rendering
// ---------------------------------------------------------------------------

function _dateStr(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return '';
  return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
}

function _relOrDash(iso) {
  if (!iso) return '&mdash;';
  const rel = timeAgo(iso);
  return rel ? escapeHtml(rel) : '&mdash;';
}

function _strengthBarHtml(r) {
  const bands = r.strengthSegments || [];
  const strong = (bands.find(s => s.band === 'strong') || {}).count || 0;
  const moderate = (bands.find(s => s.band === 'moderate') || {}).count || 0;
  const weak = (bands.find(s => s.band === 'weak') || {}).count || 0;
  const scored = strong + moderate + weak;
  const denom = Math.max(r.analyzed || 0, scored);
  if (denom <= 0) return '<span class="muted">&mdash;</span>';
  const unscored = Math.max(0, denom - scored);
  const pct = n => Math.round((100 * n) / denom);
  const titleParts = [`${strong} strong`, `${moderate} moderate`, `${weak} weak`];
  if (unscored) titleParts.push(`${unscored} unscored`);
  const title = escapeHtml(titleParts.join(' · '));

  const seg = (band, count) => count
    ? `<span class="research-strength-seg research-strength-seg--${band}" style="width:${pct(count)}%"></span>`
    : '';

  return `<div class="research-strength-bar" title="${title}">
    ${seg('strong', strong)}${seg('moderate', moderate)}${seg('weak', weak)}${seg('unscored', unscored)}
  </div>`;
}

function _coverageHtml(r) {
  const label = escapeHtml(r.coverageLabel);
  if (r.coveragePct == null) {
    return `<div>${label}</div>`;
  }
  return `<div>${label}</div>
    <div class="research-cov-bar" title="${r.coveragePct}%">
      <div class="research-cov-bar-fill" style="width:${r.coveragePct}%"></div>
    </div>`;
}

function _rowHtml(r, isArchived) {
  const id = escapeHtml(r.id);
  const rowClass = [
    'researches-row',
    r.isActive ? 'researches-row--active' : '',
    isArchived ? 'researches-row--archived' : '',
  ].filter(Boolean).join(' ');

  const draftCell = r.draftTitle
    ? `<div>${escapeHtml(r.draftTitle)}</div>${r.draftVersions > 0 ? `<div class="research-sub-count muted">v${r.draftVersions}</div>` : ''}`
    : '<div class="muted">&mdash;</div>';

  const archiveBtn = isArchived
    ? `<button class="ws-icon-btn" data-ws-unarchive="${id}">Unarchive</button>`
    : (r.isActive ? '' : `<button class="ws-icon-btn" data-ws-archive="${id}" title="Archive" aria-label="Archive">Archive</button>`);

  const renameBtn = isArchived
    ? ''
    : `<button class="ws-icon-btn" data-ws-rename="${id}" title="Rename" aria-label="Rename">&#9998;</button>`;

  return `
    <tr class="${rowClass}" data-ws-row="${id}" tabindex="0"
        aria-label="Open research ${escapeHtml(r.name)}">
      <td class="researches-cell-name">
        <span class="researches-name" data-ws-name="${id}">${escapeHtml(r.name)}</span>
        ${r.isActive ? '<span class="researches-active-dot" title="Active">&#9679;</span>' : ''}
        ${r.hasDraft ? '<span class="researches-draft-star" title="Has a draft">&#9733;</span>' : ''}
      </td>
      <td>
        <div>${r.papers}</div>
        <div class="research-sub-count muted">${r.analyzed} analyzed &middot; ${r.failed} failed</div>
      </td>
      <td>${draftCell}</td>
      <td>${_coverageHtml(r)}</td>
      <td>${_strengthBarHtml(r)}</td>
      <td>${r.openSuggestions}</td>
      <td>${_relOrDash(r.draftUpdatedIso)}</td>
      <td>${_relOrDash(r.lastActivityIso)}</td>
      <td>${escapeHtml(_dateStr(r.createdAtIso)) || '&mdash;'}</td>
      <td class="researches-cell-actions">
        <button class="btn" data-ws-open="${id}">${r.isActive ? 'Go to Home' : 'Open'}</button>
        ${renameBtn}
        ${archiveBtn}
        <button class="ws-icon-btn ws-icon-btn-danger" data-ws-delete="${id}" title="Delete" aria-label="Delete">&#128465;</button>
      </td>
    </tr>`;
}

// ---------------------------------------------------------------------------
// Events
// ---------------------------------------------------------------------------

function _bindEvents() {
  const createBtn = _el.querySelector('#ws-create-btn');
  const createInput = _el.querySelector('#ws-create-input');
  if (createBtn && createInput) {
    createBtn.addEventListener('click', () => _create(createInput.value));
    createInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') _create(createInput.value);
    });
  }

  // Sortable header buttons
  _el.querySelectorAll('[data-sort-col]').forEach(btn => {
    btn.addEventListener('click', () => _setSort(btn.dataset.sortCol));
  });

  // Row click -> open (unless clicking an inner control)
  _el.querySelectorAll('[data-ws-row]').forEach(row => {
    row.addEventListener('click', (e) => {
      if (e.target.closest('button') || e.target.closest('input')) return;
      _openWorkspace(row.dataset.wsRow);
    });
    row.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && e.target === row) _openWorkspace(row.dataset.wsRow);
    });
  });

  _el.querySelectorAll('[data-ws-open]').forEach(btn => {
    btn.addEventListener('click', () => _openWorkspace(btn.dataset.wsOpen));
  });

  _el.querySelectorAll('[data-ws-rename]').forEach(btn => {
    btn.addEventListener('click', () => _startRename(btn.dataset.wsRename));
  });

  _el.querySelectorAll('[data-ws-archive]').forEach(btn => {
    btn.addEventListener('click', () => _setArchived(btn.dataset.wsArchive, true));
  });

  _el.querySelectorAll('[data-ws-unarchive]').forEach(btn => {
    btn.addEventListener('click', () => _setArchived(btn.dataset.wsUnarchive, false));
  });

  _el.querySelectorAll('[data-ws-delete]').forEach(btn => {
    btn.addEventListener('click', () => _delete(btn.dataset.wsDelete));
  });
}

function _setSort(col) {
  if (!_SORTABLE_COLS.has(col)) return;
  if (_sortCol === col) {
    _sortDir = _sortDir === 'asc' ? 'desc' : 'asc';
  } else {
    _sortCol = col;
    _sortDir = col === 'name' ? 'asc' : 'desc';
  }
  _render();
}

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------

function _existingNames(excludeId) {
  const { workspaces } = store.getState();
  return workspaces.list
    .filter(w => w.id !== excludeId)
    .map(w => w.name || w.id);
}

async function _refresh() {
  try {
    const data = await api.getWorkspaces();
    store.setWorkspaces(data); // notifies 'workspaces' -> _render
  } catch (err) {
    showToast(err.message || 'Failed to refresh researches', 'error');
  }
}

async function _openWorkspace(id) {
  const { workspaces } = store.getState();
  if (id === workspaces.activeId) {
    window.location.hash = '#/home';
    return;
  }
  if (_busy) return;
  _busy = true;
  try {
    await api.activateWorkspace(id);
    window.location.reload();
  } catch (err) {
    _busy = false;
    showToast(err.message || 'Failed to switch research', 'error');
  }
}

async function _create(rawName) {
  if (_busy) return;
  const res = validateWorkspaceName(rawName, _existingNames(null));
  if (!res.ok) {
    showToast(res.error, 'error');
    return;
  }
  _busy = true;
  try {
    const record = await api.createWorkspace(res.name);
    await api.activateWorkspace(record.id);
    window.location.reload();
  } catch (err) {
    _busy = false;
    showToast(err.message || 'Failed to create research', 'error');
  }
}

async function _delete(id) {
  if (_busy) return;
  const { workspaces } = store.getState();
  const rec = (workspaces.list || []).find(w => w.id === id);
  const name = rec ? (rec.name || rec.id) : id;
  const paperCount = rec && rec.stats && rec.stats.papers != null
    ? Number(rec.stats.papers)
    : null;
  const ok = await confirmDialog({
    title: 'Delete this research?',
    message: deleteConfirmMessage(name, paperCount),
    confirmLabel: 'Delete',
    cancelLabel: 'Cancel',
  });
  if (!ok) return;
  try {
    const res = await api.deleteWorkspace(id);
    if (res.switched) {
      // Server moved us to another research; a reload lands there.
      _busy = true;
      window.location.reload();
      return;
    }
    await _refresh();
    showToast('Research deleted', 'info');
  } catch (err) {
    showToast(err.message || 'Failed to delete research', 'error');
  }
}

async function _setArchived(id, archived) {
  try {
    await api.patchWorkspace(id, { archived });
    await _refresh();
  } catch (err) {
    showToast(err.message || 'Failed to update research', 'error');
  }
}

function _startRename(id) {
  if (_editingId) return; // one rename at a time
  const nameEl = _el.querySelector(`[data-ws-name="${CSS.escape(id)}"]`);
  if (!nameEl) return;
  _editingId = id;

  const current = nameEl.textContent;
  const input = document.createElement('input');
  input.type = 'text';
  input.className = 'ws-rename-input';
  input.maxLength = 120;
  input.value = current;
  input.setAttribute('aria-label', 'Rename research');
  nameEl.replaceWith(input);
  input.focus();
  input.select();

  let done = false; // guard: Enter also fires blur
  const finish = async (commit) => {
    if (done) return;
    done = true;
    _editingId = null;
    const newName = input.value;
    if (!commit || newName.trim() === current.trim()) {
      _render();
      return;
    }
    const res = validateWorkspaceName(newName, _existingNames(id));
    if (!res.ok) {
      showToast(res.error, 'error');
      _render();
      return;
    }
    try {
      await api.patchWorkspace(id, { name: res.name });
    } catch (err) {
      showToast(err.message || 'Failed to rename research', 'error');
    }
    await _refresh();
  };

  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') finish(true);
    else if (e.key === 'Escape') finish(false);
  });
  input.addEventListener('blur', () => finish(true));
}
