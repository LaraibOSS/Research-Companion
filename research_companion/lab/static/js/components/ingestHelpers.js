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
