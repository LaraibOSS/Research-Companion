/**
 * components/ingestModal.js — Add/Ingest modal.
 *
 * Tabs:
 *   SINGLE: arXiv ID / URL / PDF path -> POST /api/papers -> toast + close
 *   FOLDER: path input + "Start ingest" -> POST /api/ingest -> show result 2s, close
 *
 * API:
 *   openModal()  — open (or re-open) the modal
 *   closeModal() — close
 */

import * as api from '../api.js';
import { showToast } from './toast.js';
import { classifyIngestError } from './ingestHelpers.js';

let _overlay = null;
let _modal = null;
let _autoCloseTimer = null;

// ---------------------------------------------------------------------------
// DOM creation (lazy, once)
// ---------------------------------------------------------------------------

function _ensureDOM() {
  if (_overlay) return;

  _overlay = document.createElement('div');
  _overlay.className = 'ingest-overlay';
  _overlay.addEventListener('click', (e) => {
    if (e.target === _overlay) closeModal();
  });

  _modal = document.createElement('div');
  _modal.className = 'ingest-modal';
  _modal.setAttribute('role', 'dialog');
  _modal.setAttribute('aria-modal', 'true');

  _overlay.appendChild(_modal);
  document.body.appendChild(_overlay);

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && _overlay.classList.contains('open')) closeModal();
  });
}

// ---------------------------------------------------------------------------
// Render modal content
// ---------------------------------------------------------------------------

function _renderModal(activeTab = 'single') {
  _modal.innerHTML = `
    <div class="ingest-modal-header">
      <span class="ingest-modal-title">Add Papers</span>
      <button class="ingest-close-btn" aria-label="Close">&times;</button>
    </div>
    <div class="ingest-tabs">
      <button class="ingest-tab${activeTab === 'single' ? ' ingest-tab-active' : ''}" data-tab="single">Single paper</button>
      <button class="ingest-tab${activeTab === 'folder' ? ' ingest-tab-active' : ''}" data-tab="folder">Ingest folder</button>
    </div>
    <div class="ingest-tab-body" id="ingest-tab-body"></div>
  `;

  _modal.querySelector('.ingest-close-btn').addEventListener('click', closeModal);

  _modal.querySelector('.ingest-tabs').addEventListener('click', (e) => {
    const tab = e.target.closest('[data-tab]');
    if (!tab) return;
    _renderModal(tab.dataset.tab);
    // Focus first input
    setTimeout(() => {
      const inp = _modal.querySelector('input');
      if (inp) inp.focus();
    }, 0);
  });

  const body = _modal.querySelector('#ingest-tab-body');

  if (activeTab === 'single') {
    body.innerHTML = `
      <div class="ingest-form">
        <label class="ingest-label" for="ingest-single-input">arXiv ID, URL, or PDF path</label>
        <input id="ingest-single-input" class="add-input" type="text"
               placeholder="e.g. 2312.12345 or /path/to/paper.pdf" autocomplete="off">
        <div class="ingest-error-line" id="ingest-single-error" style="display:none"></div>
        <div class="ingest-form-actions">
          <button class="btn btn-accent" id="ingest-single-add-btn">Add</button>
        </div>
      </div>
    `;

    const inp = body.querySelector('#ingest-single-input');
    const errLine = body.querySelector('#ingest-single-error');

    function _showSingleError(msg) {
      errLine.textContent = msg;
      errLine.style.display = '';
    }

    async function _doSingleAdd() {
      const target = (inp.value || '').trim();
      if (!target) return;
      errLine.style.display = 'none';
      try {
        const res = await api.addPaper(target);
        showToast(`Paper queued — job ${res.job_id}`, 'info');
        closeModal();
      } catch (err) {
        _showSingleError(err.message);
      }
    }

    body.querySelector('#ingest-single-add-btn').addEventListener('click', _doSingleAdd);
    inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') _doSingleAdd(); });

    // Auto-focus
    setTimeout(() => inp.focus(), 0);

  } else {
    // Folder tab
    body.innerHTML = `
      <div class="ingest-form">
        <label class="ingest-label" for="ingest-folder-input">Folder path</label>
        <input id="ingest-folder-input" class="add-input" type="text"
               placeholder="/path/to/folder" autocomplete="off">
        <div class="ingest-error-line" id="ingest-folder-error" style="display:none"></div>
        <div class="ingest-info-line" id="ingest-folder-info" style="display:none"></div>
        <div class="ingest-form-actions">
          <button class="btn btn-accent" id="ingest-folder-start-btn">Start ingest</button>
        </div>
      </div>
    `;

    const inp   = body.querySelector('#ingest-folder-input');
    const errLine  = body.querySelector('#ingest-folder-error');
    const infoLine = body.querySelector('#ingest-folder-info');

    async function _doFolderIngest() {
      const folder = (inp.value || '').trim();
      if (!folder) return;
      errLine.style.display = 'none';
      infoLine.style.display = 'none';

      const startBtn = body.querySelector('#ingest-folder-start-btn');
      startBtn.disabled = true;

      try {
        const res = await api.ingest(folder);
        // Show info for 2s then close
        infoLine.textContent = `Found ${res.discovered} PDFs — ingest started`;
        infoLine.style.display = '';
        _autoCloseTimer = setTimeout(() => closeModal(), 2000);
      } catch (err) {
        startBtn.disabled = false;
        const kind = classifyIngestError(err);
        if (kind === 'conflict') {
          showToast('An ingest is already running', 'error');
          closeModal();
        } else {
          errLine.textContent = err.message;
          errLine.style.display = '';
        }
      }
    }

    body.querySelector('#ingest-folder-start-btn').addEventListener('click', _doFolderIngest);
    inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') _doFolderIngest(); });

    // Auto-focus
    setTimeout(() => inp.focus(), 0);
  }
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Open the add/ingest modal.
 * @param {'single'|'folder'} [tab='single']
 */
export function openModal(tab = 'single') {
  if (_autoCloseTimer !== null) {
    clearTimeout(_autoCloseTimer);
    _autoCloseTimer = null;
  }
  _ensureDOM();
  _renderModal(tab);
  _overlay.classList.add('open');
  document.body.style.overflow = 'hidden';
}

/**
 * Close the modal.
 */
export function closeModal() {
  if (_autoCloseTimer !== null) {
    clearTimeout(_autoCloseTimer);
    _autoCloseTimer = null;
  }
  if (!_overlay) return;
  _overlay.classList.remove('open');
  document.body.style.overflow = '';
}
