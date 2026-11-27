/**
 * components/ingestModal.js — Add/Ingest modal.
 *
 * Tabs:
 *   UPLOAD: drag-and-drop / file-picker PDF -> POST /api/papers/upload
 *           (optional "This is my draft" -> set_draft=true)   [default tab]
 *   SINGLE: arXiv ID / URL / PDF path -> POST /api/papers -> toast + close
 *   FOLDER: scan -> review -> ingest, two steps within the tab:
 *     1. Scan step  — path input + "Scan folder" -> POST /api/ingest/scan
 *     2. Review step — summary + per-file list (new vs already-in-library) ->
 *        "Ingest N new" -> POST /api/ingest -> store.startIngestManifest(...) -> close
 *   ZOTERO: GET /api/zotero/status -> collection choice -> Preview (dry run) ->
 *           Import -> POST /api/zotero/import, polls GET /api/jobs/{id} and
 *           shows the report. Read-only on the Zotero side.
 *
 * API:
 *   openModal(tab, opts)  — open (or re-open) the modal; opts.draft pre-checks
 *                           the "This is my draft" checkbox on the upload tab
 *   closeModal()          — close
 */

import * as api from '../api.js';
import * as store from '../store.js';
import { showToast } from './toast.js';
import { escapeHtml } from '../format.js';
import { classifyIngestError, validateUploadFile, scanRows, initialSelection, selectionSummary } from './ingestHelpers.js';
import {
  statusView, collectionOptions, reportSummary, reportRows, nextPoll, progressText,
} from '../zoteroHelpers.js';

let _overlay = null;
let _modal = null;
let _autoCloseTimer = null;
let _lastOpts = {};

// Folder tab's local scan/review state. Reset whenever the dialog is
// (re)opened or the tab changes, so a stale file list never shows.
let _folderState = { step: 'scan', folder: '', scanResult: null, selected: new Set() };

function _resetFolderState() {
  _folderState = { step: 'scan', folder: '', scanResult: null, selected: new Set() };
}

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

function _renderModal(activeTab = 'upload', opts = {}) {
  _modal.innerHTML = `
    <div class="ingest-modal-header">
      <span class="ingest-modal-title">Add Papers</span>
      <button class="ingest-close-btn" aria-label="Close">&times;</button>
    </div>
    <div class="ingest-tabs">
      <button class="ingest-tab${activeTab === 'upload' ? ' ingest-tab-active' : ''}" data-tab="upload">Upload PDF</button>
      <button class="ingest-tab${activeTab === 'single' ? ' ingest-tab-active' : ''}" data-tab="single">arXiv / URL / path</button>
      <button class="ingest-tab${activeTab === 'folder' ? ' ingest-tab-active' : ''}" data-tab="folder">Ingest folder</button>
      <button class="ingest-tab${activeTab === 'zotero' ? ' ingest-tab-active' : ''}" data-tab="zotero">Import from Zotero</button>
    </div>
    <div class="ingest-tab-body" id="ingest-tab-body"></div>
  `;

  _modal.querySelector('.ingest-close-btn').addEventListener('click', closeModal);

  _modal.querySelector('.ingest-tabs').addEventListener('click', (e) => {
    const tab = e.target.closest('[data-tab]');
    if (!tab) return;
    if (tab.dataset.tab !== 'folder') _resetFolderState();
    _stopZoteroPoll();
    _renderModal(tab.dataset.tab, _lastOpts);
    // Focus first input
    setTimeout(() => {
      const inp = _modal.querySelector('input');
      if (inp) inp.focus();
    }, 0);
  });

  const body = _modal.querySelector('#ingest-tab-body');

  if (activeTab === 'upload') {
    body.innerHTML = `
      <div class="ingest-form">
        <div class="ingest-dropzone" id="ingest-dropzone" tabindex="0" role="button"
             aria-label="Choose or drop a PDF">
          <div class="ingest-dropzone-icon" aria-hidden="true">&#8682;</div>
          <div class="ingest-dropzone-text">Drag a PDF here, or click to browse</div>
          <input type="file" id="ingest-file-input" accept="application/pdf,.pdf"
                 style="display:none">
        </div>
        <div class="ingest-upload-filename muted" id="ingest-upload-filename"
             style="display:none"></div>
        <label class="ingest-draft-check">
          <input type="checkbox" id="ingest-draft-checkbox"${opts.draft ? ' checked' : ''}>
          This is my draft &#9733;
          <span class="muted">&mdash; the paper everything else is compared against</span>
        </label>
        <div class="ingest-error-line" id="ingest-upload-error" style="display:none"></div>
        <div class="ingest-form-actions">
          <button class="btn btn-accent" id="ingest-upload-btn" disabled>Upload</button>
        </div>
      </div>
    `;

    const dropzone  = body.querySelector('#ingest-dropzone');
    const fileInput = body.querySelector('#ingest-file-input');
    const nameLine  = body.querySelector('#ingest-upload-filename');
    const errLine   = body.querySelector('#ingest-upload-error');
    const checkbox  = body.querySelector('#ingest-draft-checkbox');
    const uploadBtn = body.querySelector('#ingest-upload-btn');
    let _file = null;

    function _showUploadError(msg) {
      errLine.textContent = msg;
      errLine.style.display = '';
    }

    function _selectFile(file) {
      errLine.style.display = 'none';
      if (!file) return;
      const check = validateUploadFile(file.name, file.size);
      if (!check.ok) {
        _file = null;
        uploadBtn.disabled = true;
        nameLine.style.display = 'none';
        _showUploadError(check.message);
        return;
      }
      _file = file;
      nameLine.textContent = file.name;
      nameLine.style.display = '';
      uploadBtn.disabled = false;
    }

    dropzone.addEventListener('click', () => fileInput.click());
    dropzone.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fileInput.click(); }
    });
    fileInput.addEventListener('change', () => _selectFile(fileInput.files[0]));
    dropzone.addEventListener('dragover', (e) => {
      e.preventDefault();
      dropzone.classList.add('dragover');
    });
    dropzone.addEventListener('dragleave', () => dropzone.classList.remove('dragover'));
    dropzone.addEventListener('drop', (e) => {
      e.preventDefault();
      dropzone.classList.remove('dragover');
      _selectFile(e.dataTransfer.files && e.dataTransfer.files[0]);
    });

    uploadBtn.addEventListener('click', async () => {
      if (!_file) return;
      errLine.style.display = 'none';
      uploadBtn.disabled = true;
      uploadBtn.textContent = 'Uploading…';
      try {
        const res = await api.uploadPaper(_file, checkbox.checked);
        if (res.duplicate) {
          // Already in the library (same content, or same arXiv id/DOI). Name it
          // so a deduped upload never looks like a silent failure.
          const title = store.getState().papers.get(res.paper_id)?.title;
          const named = title ? ` as “${title}”` : '';
          if (res.draft_set) {
            store.setDraft(res.paper_id);
            showToast(`Already in your library${named} — set as your draft ★`, 'info');
          } else {
            showToast(`Already in your library${named}`, 'info');
          }
        } else if (res.draft_set) {
          store.setDraft(res.paper_id);
          showToast('Saved as your draft ★', 'info');
        } else {
          showToast(`Paper queued — job ${res.job_id}`, 'info');
        }
        closeModal();
      } catch (err) {
        uploadBtn.disabled = false;
        uploadBtn.textContent = 'Upload';
        _showUploadError(err.message);
      }
    });

  } else if (activeTab === 'single') {
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

  } else if (activeTab === 'zotero') {
    _renderZoteroTab(body);
  } else if (_folderState.step === 'review') {
    _renderFolderReviewStep(body);
  } else {
    _renderFolderScanStep(body);
  }
}

// ---------------------------------------------------------------------------
// Folder tab — scan step
// ---------------------------------------------------------------------------

function _renderFolderScanStep(body) {
  body.innerHTML = `
    <div class="ingest-form">
      <label class="ingest-label" for="ingest-folder-input">Folder path</label>
      <input id="ingest-folder-input" class="add-input" type="text"
             placeholder="/path/to/folder" autocomplete="off" value="${escapeHtml(_folderState.folder)}">
      <div class="ingest-error-line" id="ingest-folder-error" style="display:none"></div>
      <div class="ingest-form-actions">
        <button class="btn btn-accent" id="ingest-folder-scan-btn">Scan folder</button>
      </div>
    </div>
  `;

  const inp     = body.querySelector('#ingest-folder-input');
  const errLine = body.querySelector('#ingest-folder-error');
  const scanBtn = body.querySelector('#ingest-folder-scan-btn');

  function _showError(msg) {
    errLine.textContent = msg;
    errLine.style.display = '';
  }

  async function _doScan() {
    const folder = (inp.value || '').trim();
    errLine.style.display = 'none';
    if (!folder) {
      _showError('Enter a folder path');
      return;
    }

    scanBtn.disabled = true;
    scanBtn.textContent = 'Scanning…';

    try {
      const res = await api.scanFolder(folder);
      _folderState = { step: 'review', folder, scanResult: res, selected: initialSelection(res.files) };
      _renderModal('folder', _lastOpts);
    } catch (err) {
      scanBtn.disabled = false;
      scanBtn.textContent = 'Scan folder';
      _showError(err.message);
    }
  }

  scanBtn.addEventListener('click', _doScan);
  inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') _doScan(); });

  // Auto-focus
  setTimeout(() => inp.focus(), 0);
}

// ---------------------------------------------------------------------------
// Folder tab — review step
// ---------------------------------------------------------------------------

function _renderFolderReviewStep(body) {
  const scanResult = _folderState.scanResult || { discovered: 0, already: 0, files: [] };
  const selected = _folderState.selected;
  const summary = selectionSummary(scanResult.files, selected);
  const rows = scanRows(scanResult.files);
  const newTotal = summary.newCount;

  const summaryLine = `${summary.newCount + summary.alreadyCount} PDF${(summary.newCount + summary.alreadyCount) !== 1 ? 's' : ''} — `
    + `${summary.selectedCount} selected · ${summary.newCount} new · ${summary.alreadyCount} already in your library`;

  const rowsHtml = rows.map(row => `
    <div class="ingest-scan-row${row.already ? ' ingest-scan-row-locked' : ''}">
      <input type="checkbox" class="ingest-scan-checkbox"
        ${row.already ? 'disabled' : `data-path="${escapeHtml(row.path)}"`}
        ${!row.already && selected.has(row.path) ? 'checked' : ''}
        ${row.already ? 'title="Already in your library"' : ''}>
      <span class="ingest-scan-relpath" title="${escapeHtml(row.relPath)}">${escapeHtml(row.relPath)}</span>
      ${row.already
        ? '<span class="badge badge-muted">Already in library</span>'
        : '<span class="badge badge-ok">New</span>'}
    </div>
  `).join('');

  body.innerHTML = `
    <div class="ingest-form">
      <div class="ingest-scan-summary">${escapeHtml(summaryLine)}</div>
      ${newTotal > 0 ? `
        <div class="ingest-scan-selectall">
          <button class="btn btn-sm" id="ingest-folder-select-all-btn">Select all</button>
          <button class="btn btn-sm" id="ingest-folder-select-none-btn">Select none</button>
        </div>
      ` : ''}
      <div class="ingest-scan-list">${rowsHtml || '<div class="muted">No PDFs found.</div>'}</div>
      <div class="ingest-error-line" id="ingest-folder-review-error" style="display:none"></div>
      ${newTotal === 0
        ? '<div class="ingest-hint-line">All files are already in your library</div>'
        : ''}
      <div class="ingest-form-actions">
        <button class="btn" id="ingest-folder-back-btn">Back</button>
        <button class="btn btn-accent" id="ingest-folder-confirm-btn"${summary.selectedCount === 0 ? ' disabled' : ''}>
          Ingest ${summary.selectedCount} selected
        </button>
      </div>
    </div>
  `;

  const errLine    = body.querySelector('#ingest-folder-review-error');
  const backBtn    = body.querySelector('#ingest-folder-back-btn');
  const confirmBtn = body.querySelector('#ingest-folder-confirm-btn');
  const list       = body.querySelector('.ingest-scan-list');
  const selectAllBtn  = body.querySelector('#ingest-folder-select-all-btn');
  const selectNoneBtn = body.querySelector('#ingest-folder-select-none-btn');

  backBtn.addEventListener('click', () => {
    _folderState = { ..._folderState, step: 'scan' };
    _renderModal('folder', _lastOpts);
  });

  list.addEventListener('change', (e) => {
    const cb = e.target.closest('.ingest-scan-checkbox[data-path]');
    if (!cb) return;
    if (cb.checked) _folderState.selected.add(cb.dataset.path);
    else _folderState.selected.delete(cb.dataset.path);
    _renderModal('folder', _lastOpts);
  });

  if (selectAllBtn) {
    selectAllBtn.addEventListener('click', () => {
      for (const row of rows) {
        if (!row.already) _folderState.selected.add(row.path);
      }
      _renderModal('folder', _lastOpts);
    });
  }
  if (selectNoneBtn) {
    selectNoneBtn.addEventListener('click', () => {
      for (const row of rows) {
        if (!row.already) _folderState.selected.delete(row.path);
      }
      _renderModal('folder', _lastOpts);
    });
  }

  confirmBtn.addEventListener('click', async () => {
    errLine.style.display = 'none';
    confirmBtn.disabled = true;
    try {
      await api.ingest(_folderState.folder, [..._folderState.selected]);
      store.startIngestManifest(scanResult.files.filter(f => _folderState.selected.has(f.path)));
      closeModal();
    } catch (err) {
      confirmBtn.disabled = false;
      const kind = classifyIngestError(err);
      if (kind === 'conflict') {
        showToast('An ingest is already running', 'error');
        closeModal();
      } else {
        errLine.textContent = err.message;
        errLine.style.display = '';
      }
    }
  });
}

// ---------------------------------------------------------------------------
// Zotero tab — status, collection, Preview / Import, report
// ---------------------------------------------------------------------------

// Bumped to invalidate an in-flight poll when the tab changes or the modal
// closes, so a late reply never writes into a body that is gone.
let _zoteroPollToken = 0;
let _zoteroPollTimer = null;
const ZOTERO_POLL_MS = 1500;

function _stopZoteroPoll() {
  _zoteroPollToken += 1;
  if (_zoteroPollTimer !== null) {
    clearTimeout(_zoteroPollTimer);
    _zoteroPollTimer = null;
  }
}

async function _refreshLibraryPapers() {
  try {
    const fresh = await api.getPapers();
    if (!Array.isArray(fresh)) return;
    const s = store.getState();
    for (const p of fresh) {
      if (!p || !p.paper_id) continue;
      s.papers.set(p.paper_id, { ...s.papers.get(p.paper_id), ...p });
    }
    store.notify(['papers']);
  } catch (err) {
    console.warn('[ingest] papers refresh after Zotero import failed', err);
  }
}

function _renderZoteroReport(target, report) {
  const rows = reportRows(report);
  target.innerHTML = `
    <div class="ingest-scan-summary">${escapeHtml(reportSummary(report))}</div>
    ${rows.length ? `<div class="ingest-scan-list">${rows.map(r => `
      <div class="ingest-scan-row">
        <span class="ingest-scan-relpath" title="${escapeHtml(r.title)}">${escapeHtml(r.title)}</span>
        <span class="badge badge-${r.tone === 'ok' ? 'ok' : r.tone === 'warn' ? 'warn' : 'muted'}">${escapeHtml(r.text)}</span>
      </div>`).join('')}</div>` : ''}
  `;
}

function _renderZoteroTab(body) {
  body.innerHTML = `
    <div class="ingest-form">
      <div class="ingest-hint-line" id="zotero-status">Checking Zotero…</div>
      <div id="zotero-controls" style="display:none">
        <label class="ingest-label" for="zotero-collection">Collection</label>
        <select id="zotero-collection" class="add-input"></select>
        <div class="ingest-hint-line muted">Read-only: nothing is changed in Zotero.
          Papers are added by arXiv id or DOI when they have one, else from the PDF in
          Zotero, else as details only. Nothing is analysed until you ask.</div>
        <div class="ingest-form-actions">
          <button class="btn" id="zotero-preview-btn">Preview</button>
          <button class="btn btn-accent" id="zotero-import-btn" disabled
                  title="Preview first">Import</button>
        </div>
      </div>
      <div class="ingest-error-line" id="zotero-error" style="display:none"></div>
      <div class="muted" id="zotero-progress" style="display:none"></div>
      <div id="zotero-report"></div>
    </div>
  `;

  const statusLine = body.querySelector('#zotero-status');
  const controls   = body.querySelector('#zotero-controls');
  const select     = body.querySelector('#zotero-collection');
  const previewBtn = body.querySelector('#zotero-preview-btn');
  const importBtn  = body.querySelector('#zotero-import-btn');
  const errLine    = body.querySelector('#zotero-error');
  const progress   = body.querySelector('#zotero-progress');
  const reportBox  = body.querySelector('#zotero-report');
  const token = _zoteroPollToken;

  function _showError(msg) {
    errLine.textContent = msg;
    errLine.style.display = '';
  }

  function _setBusy(busy) {
    previewBtn.disabled = busy;
    select.disabled = busy;
    if (busy) importBtn.disabled = true;
  }

  function _watch(jobId, dryRun) {
    let failures = 0;
    const tick = async () => {
      if (token !== _zoteroPollToken) return;
      let job = null;
      let error = null;
      try { job = await api.getJob(jobId); } catch (e) { error = e; }
      if (token !== _zoteroPollToken) return;
      const next = nextPoll({ job, error, consecutiveFailures: failures });
      failures = error ? failures + 1 : 0;
      if (next === 'continue') {
        if (job) progress.textContent = progressText(job);
        _zoteroPollTimer = setTimeout(tick, ZOTERO_POLL_MS);
        return;
      }
      _zoteroPollTimer = null;
      progress.style.display = 'none';
      _setBusy(false);
      if (next === 'done') {
        _renderZoteroReport(reportBox, job.report);
        // A preview unlocks Import for the same choice; after an import the
        // preview is spent, so Import waits for the next one.
        importBtn.disabled = !dryRun;
        if (!dryRun) {
          _refreshLibraryPapers();
          showToast(reportSummary(job.report), 'info');
        }
      } else if (next === 'failed') {
        _showError((job && job.detail) || 'The Zotero import failed.');
      } else {
        _showError('Lost track of the Zotero import. It may still be running; '
          + 'check the activity indicator.');
      }
    };
    _zoteroPollTimer = setTimeout(tick, 300);
  }

  async function _start(dryRun) {
    errLine.style.display = 'none';
    reportBox.innerHTML = '';
    _setBusy(true);
    progress.textContent = dryRun ? 'Checking…' : 'Importing…';
    progress.style.display = '';
    try {
      const res = await api.importZotero(select.value, dryRun);
      if (token !== _zoteroPollToken) return;
      _watch(res.job_id, dryRun);
    } catch (err) {
      progress.style.display = 'none';
      _setBusy(false);
      _showError(String(err.message || '').includes('no_active_workspace')
        ? 'Open or create a research first.' : err.message);
    }
  }

  select.addEventListener('change', () => {
    importBtn.disabled = true;   // a preview is of one choice; re-preview on change
    reportBox.innerHTML = '';
  });
  previewBtn.addEventListener('click', () => _start(true));
  importBtn.addEventListener('click', () => _start(false));

  (async () => {
    let status;
    try {
      status = await api.getZoteroStatus();
    } catch (err) {
      status = { ok: false, state: 'error', message: err.message };
    }
    if (token !== _zoteroPollToken) return;
    const view = statusView(status);
    statusLine.textContent = view.message;
    statusLine.className = `ingest-hint-line${view.tone === 'ok' ? '' : ' ingest-error-line'}`;
    if (!view.ready) return;
    try {
      const cols = await api.getZoteroCollections();
      if (token !== _zoteroPollToken) return;
      select.innerHTML = collectionOptions(cols)
        .map(o => `<option value="${escapeHtml(o.value)}">${escapeHtml(o.label)}</option>`)
        .join('');
    } catch (err) {
      if (token !== _zoteroPollToken) return;
      select.innerHTML = collectionOptions(null)
        .map(o => `<option value="${escapeHtml(o.value)}">${escapeHtml(o.label)}</option>`)
        .join('');
      _showError(`Could not list collections: ${err.message}`);
    }
    controls.style.display = '';
  })();
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Open the add/ingest modal.
 * @param {'upload'|'single'|'folder'|'zotero'} [tab='upload']
 * @param {{draft?: boolean}} [opts] — draft:true pre-checks "This is my draft"
 */
export function openModal(tab = 'upload', opts = {}) {
  if (_autoCloseTimer !== null) {
    clearTimeout(_autoCloseTimer);
    _autoCloseTimer = null;
  }
  _resetFolderState();
  _stopZoteroPoll();
  _lastOpts = opts || {};
  _ensureDOM();
  _renderModal(tab, _lastOpts);
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
  _resetFolderState();
  _stopZoteroPoll();
  if (!_overlay) return;
  _overlay.classList.remove('open');
  document.body.style.overflow = '';
}
