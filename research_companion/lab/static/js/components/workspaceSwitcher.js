/**
 * components/workspaceSwitcher.js — Topbar workspace ("research") switcher (W4-F1).
 *
 * Mounted ONCE from main.js onto the pre-existing #workspace-switcher button.
 * Shows the active research name + a chevron, or a muted "Research: none"
 * when nothing is active yet (boot fetch is non-fatal) — clicking it still
 * opens the New research / All researches menu either way.
 *
 * The dropdown menu lists non-archived workspaces (active one checkmarked;
 * clicking another activates it and reloads the page), then a divider,
 * "New research" (-> #/researches?new=1) and "All researches" (-> #/researches).
 * Closes on outside click and Escape. Re-renders on store 'workspaces' notify.
 */

import * as store from '../store.js';
import * as api from '../api.js';
import { showToast } from './toast.js';
import { escapeHtml } from '../format.js';
import { splitWorkspaces } from '../workspaceHelpers.js';

let _btn = null;
let _menu = null;
let _open = false;
let _storeRef = null;
let _apiRef = null;
let _busy = false; // activate+reload in flight

/**
 * Mount the switcher once. Safe to call when #workspace-switcher is absent.
 * @param {object} storeRef — store module (injected for testability)
 * @param {object} apiRef   — api module (injected for testability)
 */
export function mountWorkspaceSwitcher(storeRef = store, apiRef = api) {
  _btn = document.getElementById('workspace-switcher');
  if (!_btn) return;
  _storeRef = storeRef;
  _apiRef = apiRef;

  _btn.addEventListener('click', (e) => {
    e.stopPropagation();
    if (_open) _close(); else _openMenu();
  });

  document.addEventListener('click', (e) => {
    if (_open && _menu && !_menu.contains(e.target) && e.target !== _btn) _close();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && _open) _close();
  });

  _storeRef.subscribe('workspaces', () => {
    _renderButton();
    if (_open) _renderMenu();
  });
  _renderButton();
}

// ---------------------------------------------------------------------------
// Button
// ---------------------------------------------------------------------------

function _renderButton() {
  if (!_btn) return;
  const { workspaces } = _storeRef.getState();
  const { list, activeId } = workspaces;
  const active = Array.isArray(list) ? list.find(w => w.id === activeId) : null;

  // Defensive: a research IS active but has no record in the list (e.g. an
  // older server that does not emit env-pinned workspaces). Name it by its id
  // rather than claiming "none" — the top bar must never contradict the fact
  // that a research is being served.
  if (!active && activeId) {
    _btn.innerHTML = `<span class="ws-switcher-name">${escapeHtml(activeId)}</span>`
      + `<span class="ws-switcher-chevron" aria-hidden="true">&#9662;</span>`;
    _btn.setAttribute('aria-haspopup', 'menu');
    _btn.setAttribute('aria-expanded', _open ? 'true' : 'false');
    _btn.title = 'Active research';
    _btn.style.display = '';
    return;
  }

  if (!active) {
    _btn.innerHTML = `<span class="ws-switcher-name ws-switcher-none">Research: none</span>`
      + `<span class="ws-switcher-chevron" aria-hidden="true">&#9662;</span>`;
    _btn.setAttribute('aria-haspopup', 'menu');
    _btn.setAttribute('aria-expanded', _open ? 'true' : 'false');
    _btn.title = 'Choose or create a research';
    _btn.style.display = '';
    return;
  }

  _btn.innerHTML = `<span class="ws-switcher-name">${escapeHtml(active.name || active.id)}</span>`
    + `<span class="ws-switcher-chevron" aria-hidden="true">&#9662;</span>`;
  _btn.setAttribute('aria-haspopup', 'menu');
  _btn.setAttribute('aria-expanded', _open ? 'true' : 'false');
  _btn.title = 'Switch research';
  _btn.style.display = '';
}

// ---------------------------------------------------------------------------
// Menu
// ---------------------------------------------------------------------------

function _openMenu() {
  if (!_menu) {
    _menu = document.createElement('div');
    _menu.className = 'ws-menu';
    _menu.setAttribute('role', 'menu');
    document.body.appendChild(_menu);
  }
  _open = true;
  _renderMenu();
  const rect = _btn.getBoundingClientRect();
  _menu.style.top = `${rect.bottom + 6}px`;
  _menu.style.left = `${rect.left}px`;
  _menu.style.display = '';
  _btn.setAttribute('aria-expanded', 'true');
}

function _close() {
  _open = false;
  if (_menu) _menu.style.display = 'none';
  if (_btn) _btn.setAttribute('aria-expanded', 'false');
}

function _renderMenu() {
  if (!_menu) return;
  const { workspaces } = _storeRef.getState();
  const { list, activeId } = workspaces;
  const { active } = splitWorkspaces(list, activeId);

  const items = active.map(w => {
    const isActive = w.id === activeId;
    return `
      <button class="ws-menu-item${isActive ? ' ws-menu-item-active' : ''}"
              role="menuitem" data-ws-id="${escapeHtml(w.id)}">
        <span class="ws-menu-check" aria-hidden="true">${isActive ? '&#10003;' : ''}</span>
        <span class="ws-menu-name">${escapeHtml(w.name || w.id)}</span>
      </button>`;
  }).join('');

  _menu.innerHTML = `
    ${items}
    <div class="ws-menu-divider" role="separator"></div>
    <button class="ws-menu-item" role="menuitem" data-ws-action="new">
      <span class="ws-menu-check" aria-hidden="true">&#65291;</span>
      <span class="ws-menu-name">New research</span>
    </button>
    <button class="ws-menu-item" role="menuitem" data-ws-action="all">
      <span class="ws-menu-check" aria-hidden="true"></span>
      <span class="ws-menu-name">All researches&hellip;</span>
    </button>`;

  _menu.querySelectorAll('[data-ws-id]').forEach(item => {
    item.addEventListener('click', () => _activate(item.dataset.wsId));
  });
  _menu.querySelectorAll('[data-ws-action]').forEach(item => {
    item.addEventListener('click', () => {
      _close();
      window.location.hash = item.dataset.wsAction === 'new'
        ? '#/researches?new=1'
        : '#/researches';
    });
  });
}

async function _activate(id) {
  const { workspaces } = _storeRef.getState();
  if (id === workspaces.activeId) {
    _close();
    return;
  }
  if (_busy) return;
  _busy = true;
  try {
    await _apiRef.activateWorkspace(id);
    window.location.reload();
  } catch (err) {
    _busy = false;
    _close();
    showToast(err.message || 'Failed to switch research', 'error');
  }
}
