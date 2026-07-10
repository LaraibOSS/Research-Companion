/**
 * components/ingestHelpers.js — Pure, DOM-free helpers for the ingest modal.
 * Exported separately so they can be tested with node --test without a DOM.
 */

/**
 * Classify an ingest API error to drive the folder-tab error handler.
 *
 * @param {Error & {status?: number}} err
 * @returns {'conflict'|'inline'}
 *   'conflict' → HTTP 409: show toast "An ingest is already running" and close modal
 *   'inline'   → any other error: show message in the inline error line
 */
export function classifyIngestError(err) {
  return err.status === 409 ? 'conflict' : 'inline';
}

/** Upload size cap — mirrors the backend's _MAX_UPLOAD_BYTES. */
export const MAX_UPLOAD_BYTES = 50 * 1024 * 1024;

/**
 * Validate a picked/dropped file before upload.
 *
 * @param {string} name  file name (extension checked case-insensitively)
 * @param {number} size  file size in bytes
 * @returns {{ok: true} | {ok: false, reason: 'not-pdf'|'empty'|'too-large', message: string}}
 */
export function validateUploadFile(name, size) {
  if (!/\.pdf$/i.test(name || '')) {
    return { ok: false, reason: 'not-pdf', message: 'Please choose a PDF file.' };
  }
  if (!size) {
    return { ok: false, reason: 'empty', message: 'That file is empty.' };
  }
  if (size > MAX_UPLOAD_BYTES) {
    return { ok: false, reason: 'too-large', message: 'PDF exceeds the 50 MB upload limit.' };
  }
  return { ok: true };
}

// ---------------------------------------------------------------------------
// Folder scan-preview helpers (POST /api/ingest/scan review step)
// ---------------------------------------------------------------------------

/**
 * Summarize a scan result's file list for the review-step headline.
 *
 * @param {Array<{already_in_library?: boolean}>} [files]
 * @returns {{total: number, newCount: number, alreadyCount: number}}
 */
export function scanSummary(files) {
  const list = Array.isArray(files) ? files : [];
  const total = list.length;
  const alreadyCount = list.filter(f => !!(f && f.already_in_library)).length;
  return { total, newCount: total - alreadyCount, alreadyCount };
}

/**
 * Normalize scan-result file objects into rows for the review-step list.
 * New files are sorted first (so the actionable ones are on top), each group
 * sorted by relPath. Tolerates missing fields.
 *
 * @param {Array<{name?, path?, rel_path?, already_in_library?}>} [files]
 * @returns {Array<{name: string, relPath: string, path: string, already: boolean}>}
 */
export function scanRows(files) {
  const list = Array.isArray(files) ? files : [];
  const rows = list.map(f => ({
    name:    (f && f.name) || '',
    relPath: (f && (f.rel_path || f.name || f.path)) || '',
    path:    (f && f.path) || '',
    already: !!(f && f.already_in_library),
  }));
  rows.sort((a, b) => {
    if (a.already !== b.already) return a.already ? 1 : -1;
    return a.relPath.localeCompare(b.relPath);
  });
  return rows;
}

/**
 * Compute the default selection for the review-step checkboxes: every New
 * (not-already-in-library) file's absolute path.
 *
 * @param {Array<{path?, already_in_library?}>} [files]
 * @returns {Set<string>}
 */
export function initialSelection(files) {
  const list = Array.isArray(files) ? files : [];
  const sel = new Set();
  for (const f of list) {
    if (f && !f.already_in_library) sel.add(f.path || '');
  }
  return sel;
}

/**
 * Summarize the current checkbox selection alongside the scan file list for
 * the review-step summary line.
 *
 * @param {Array<{already_in_library?: boolean}>} [files]
 * @param {Set<string>} [selectedSet]
 * @returns {{selectedCount: number, newCount: number, alreadyCount: number}}
 */
export function selectionSummary(files, selectedSet) {
  const { newCount, alreadyCount } = scanSummary(files);
  const selectedCount = selectedSet instanceof Set ? selectedSet.size : 0;
  return { selectedCount, newCount, alreadyCount };
}

// ---------------------------------------------------------------------------
// Progress-dock manifest row -> status chip mapper
// ---------------------------------------------------------------------------

const _MANIFEST_STATUS_VIEW = {
  queued:     { cls: 'lib-status-pill-queued',     icon: '',  chipLabel: 'Queued' },
  processing: { cls: 'lib-status-pill-processing', icon: '',  chipLabel: 'Reading…' },
  done:       { cls: 'lib-status-pill-ingested',    icon: '✓', chipLabel: 'Added ✓' },
  failed:     { cls: 'lib-status-pill-failed',      icon: '✗', chipLabel: 'Failed ✗' },
  skipped:    { cls: 'lib-status-pill-skipped',     icon: '',  chipLabel: 'Skipped' },
};

/**
 * Map an ingest-manifest row (or dock item) to its status-chip view.
 *
 * @param {{status?: string}} row
 * @returns {{cls: string, icon: string, chipLabel: string}}
 */
export function manifestItemView(row) {
  const status = (row && row.status) || 'queued';
  const view = _MANIFEST_STATUS_VIEW[status] || _MANIFEST_STATUS_VIEW.queued;
  return { cls: view.cls, icon: view.icon, chipLabel: view.chipLabel };
}
