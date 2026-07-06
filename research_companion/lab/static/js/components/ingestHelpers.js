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
