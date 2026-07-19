/**
 * views/researches.js — Researches overview screen (route #/researches, W4-F1).
 *
 * Card grid of all workspaces ("researches"):
 *   - inline create row at top (focused when the hash query has ?new=1)
 *   - active card accent-bordered with an "Active" chip
 *   - click card / Open -> activate workspace + full page reload
 *     (clicking the already-active card navigates #/home instead)
 *   - per-card pencil -> inline rename (Enter/blur commits via PATCH)
 *   - per-card Archive -> PATCH archived:true; archived cards live in a
 *     collapsed <details> section below with an Unarchive button
 *   - per-card trash -> confirmDialog() then DELETE /api/workspaces/{id};
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
  workspaceCardModel,
} from '../workspaceHelpers.js';

let _el = null;
let _unsub = null;
let _busy = false;       // guard: an activate/reload is already in flight
let _editingId = null;   // workspace id currently in inline-rename mode

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

  const models = active.map(w => workspaceCardModel(w, activeId));
  const archivedModels = archived.map(w => workspaceCardModel(w, activeId));

  // Empty state: just the initial workspace with no papers yet
  const isEmpty = models.length === 1 && archivedModels.length === 0
    && models[0].paperCount === 0;

  const emptyHtml = isEmpty
    ? `<p class="ws-empty-hint muted">One research so far — everything you add
         lives here. Create another to explore a second topic side by side.</p>`
    : '';

  const archivedHtml = archivedModels.length > 0
    ? `<details class="ws-archived">
         <summary>Archived (${archivedModels.length})</summary>
         <div class="ws-grid">${archivedModels.map(_archivedCardHtml).join('')}</div>
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
      <div class="ws-grid">${models.map(_cardHtml).join('')}</div>
      ${archivedHtml}
    </div>`;

  const input = _el.querySelector('#ws-create-input');
  if (input) {
    input.value = prevValue;
    if (hadFocus) input.focus();
  }

  _bindEvents();
}

function _cardHtml(m) {
  const id = escapeHtml(m.id);
  const draftHtml = m.draftTitle
    ? `<div class="ws-card-draft">&#9733; ${escapeHtml(m.draftTitle)}</div>`
    : `<div class="ws-card-draft muted">No draft yet</div>`;
  const activity = m.lastActivityIso ? timeAgo(m.lastActivityIso) : 'no activity yet';

  return `
    <div class="ws-card${m.isActive ? ' ws-card-active' : ''}"
         data-ws-card="${id}" role="button" tabindex="0"
         aria-label="Open research ${escapeHtml(m.name)}">
      <div class="ws-card-top">
        <span class="ws-card-name" data-ws-name="${id}">${escapeHtml(m.name)}</span>
        ${m.isActive ? '<span class="ws-active-chip">Active</span>' : ''}
      </div>
      ${draftHtml}
      <div class="ws-card-stats">
        <span>${m.paperCount} paper${m.paperCount === 1 ? '' : 's'}</span>
        <span>&middot;</span>
        <span>${m.openSuggestions} open suggestion${m.openSuggestions === 1 ? '' : 's'}</span>
        <span>&middot;</span>
        <span>${escapeHtml(activity)}</span>
      </div>
      <div class="ws-card-actions">
        <button class="btn" data-ws-open="${id}">${m.isActive ? 'Go to Home' : 'Open'}</button>
        <span class="ws-card-actions-spacer"></span>
        <button class="ws-icon-btn" data-ws-rename="${id}" title="Rename" aria-label="Rename">&#9998;</button>
        ${m.isActive ? '' : `<button class="ws-icon-btn" data-ws-archive="${id}" title="Archive" aria-label="Archive">Archive</button>`}
        <button class="ws-icon-btn ws-icon-btn-danger" data-ws-delete="${id}" title="Delete" aria-label="Delete">&#128465;</button>
      </div>
    </div>`;
}

function _archivedCardHtml(m) {
  const id = escapeHtml(m.id);
  return `
    <div class="ws-card ws-card-archived" data-ws-archived-card="${id}">
      <div class="ws-card-top">
        <span class="ws-card-name">${escapeHtml(m.name)}</span>
      </div>
      <div class="ws-card-stats">
        <span>${m.paperCount} paper${m.paperCount === 1 ? '' : 's'}</span>
      </div>
      <div class="ws-card-actions">
        <button class="btn" data-ws-unarchive="${id}">Unarchive</button>
        <button class="ws-icon-btn ws-icon-btn-danger" data-ws-delete="${id}" title="Delete" aria-label="Delete">&#128465;</button>
      </div>
    </div>`;
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

  // Card click -> open (unless clicking an inner control)
  _el.querySelectorAll('[data-ws-card]').forEach(card => {
    card.addEventListener('click', (e) => {
      if (e.target.closest('button') || e.target.closest('input')) return;
      _openWorkspace(card.dataset.wsCard);
    });
    card.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && e.target === card) _openWorkspace(card.dataset.wsCard);
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
