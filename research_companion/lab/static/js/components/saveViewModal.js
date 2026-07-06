/**
 * components/saveViewModal.js — Save subgraph as a named view.
 *
 * Small centered modal (reuses ingest-modal CSS patterns).
 * Pre-fills the name with the Ask question truncated to 60 chars.
 * On save: POST /api/views -> toast "Saved — find it in Graph > Saved views"
 *          -> close. 400 -> inline error.
 * Esc / backdrop closes.
 *
 * API:
 *   openSaveViewModal({ question, nodeIds, onSaved? })
 *   closeSaveViewModal()
 *
 * W3-F6.
 */

import * as api from '../api.js';
import { showToast } from './toast.js';
import { truncateName } from '../viewsHelpers.js';
import { escapeHtml } from '../format.js';

let _overlay = null;
let _modal = null;

// ---------------------------------------------------------------------------
// DOM creation (lazy, once)
// ---------------------------------------------------------------------------

function _ensureDOM() {
  if (_overlay) return;

  _overlay = document.createElement('div');
  _overlay.className = 'ingest-overlay';
  _overlay.addEventListener('click', (e) => {
    if (e.target === _overlay) closeSaveViewModal();
  });

  _modal = document.createElement('div');
  _modal.className = 'ingest-modal save-view-modal';
  _modal.setAttribute('role', 'dialog');
  _modal.setAttribute('aria-modal', 'true');
  _modal.setAttribute('aria-label', 'Save subgraph view');

  _overlay.appendChild(_modal);
  document.body.appendChild(_overlay);

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && _overlay.classList.contains('open')) closeSaveViewModal();
  });
}

// ---------------------------------------------------------------------------
// Render modal content
// ---------------------------------------------------------------------------

function _renderModal({ question, nodeIds, onSaved }) {
  const prefilled = truncateName(question || '', 60);
  const count = Array.isArray(nodeIds) ? nodeIds.length : 0;

  _modal.innerHTML = `
    <div class="ingest-modal-header">
      <span class="ingest-modal-title">Save subgraph view</span>
      <button class="ingest-close-btn" aria-label="Close">&times;</button>
    </div>
    <div class="ingest-form save-view-form">
      <label class="ingest-label" for="save-view-name">View name</label>
      <input id="save-view-name" class="add-input" type="text"
             value="${escapeHtml(prefilled)}"
             placeholder="Enter a name…" autocomplete="off" maxlength="200">
      <div class="save-view-count muted">${escapeHtml(String(count))} node${count !== 1 ? 's' : ''}</div>
      <div class="ingest-error-line" id="save-view-error" style="display:none"></div>
      <div class="ingest-form-actions">
        <button class="btn btn-secondary" id="save-view-cancel-btn">Cancel</button>
        <button class="btn btn-accent" id="save-view-save-btn">Save</button>
      </div>
    </div>
  `;

  const inp      = _modal.querySelector('#save-view-name');
  const errLine  = _modal.querySelector('#save-view-error');
  const saveBtn  = _modal.querySelector('#save-view-save-btn');
  const cancelBtn = _modal.querySelector('#save-view-cancel-btn');

  _modal.querySelector('.ingest-close-btn').addEventListener('click', closeSaveViewModal);
  cancelBtn.addEventListener('click', closeSaveViewModal);

  function _showError(msg) {
    errLine.textContent = msg;
    errLine.style.display = '';
  }

  async function _doSave() {
    const name = (inp.value || '').trim();
    if (!name) {
      _showError('Name is required.');
      return;
    }
    errLine.style.display = 'none';
    saveBtn.disabled = true;
    saveBtn.textContent = 'Saving…';

    try {
      await api.createView({
        name,
        source: { type: 'ask', query: question || '' },
        node_ids: nodeIds || [],
      });
      showToast('Saved — find it in Graph > Saved views', 'info');
      closeSaveViewModal();
      if (typeof onSaved === 'function') onSaved();
    } catch (err) {
      saveBtn.disabled = false;
      saveBtn.textContent = 'Save';
      _showError(err.message || 'Save failed.');
    }
  }

  saveBtn.addEventListener('click', _doSave);
  inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') _doSave(); });

  // Auto-focus and select all (convenient for renaming)
  setTimeout(() => {
    inp.focus();
    inp.select();
  }, 0);
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Open the save-view modal.
 *
 * @param {{ question: string, nodeIds: string[], onSaved?: () => void }} opts
 */
export function openSaveViewModal(opts = {}) {
  _ensureDOM();
  _renderModal(opts);
  _overlay.classList.add('open');
  document.body.style.overflow = 'hidden';
}

/**
 * Close the save-view modal.
 */
export function closeSaveViewModal() {
  if (!_overlay) return;
  _overlay.classList.remove('open');
  document.body.style.overflow = '';
}
