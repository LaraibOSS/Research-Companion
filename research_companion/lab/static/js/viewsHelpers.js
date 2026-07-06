/**
 * viewsHelpers.js — Pure, DOM-free helpers for the saved-views feature.
 * Node-testable (no browser globals required).
 * W3-F6.
 */

/**
 * Truncate a query string to at most `max` characters, breaking on a word
 * boundary where possible, and appending '…' when truncated.
 *
 * @param {string} q    — input string
 * @param {number} max  — maximum character count (default 60)
 * @returns {string}
 */
export function truncateName(q, max = 60) {
  if (typeof q !== 'string') q = String(q == null ? '' : q);
  if (q.length <= max) return q;

  // Try to break on the last space at or before max
  const slice = q.slice(0, max);
  const lastSpace = slice.lastIndexOf(' ');
  const cut = lastSpace > 0 ? lastSpace : max;
  return q.slice(0, cut) + '…';
}

/**
 * Map an array of raw view objects from the server into display-ready row models.
 * Pinned rows are expected to already be sorted first by the server.
 *
 * @param {Array<{view_id:string, name:string, node_ids:Array, pinned:boolean}>} views
 * @param {string|null} activeId — currently-active view_id (or null for live mode)
 * @returns {Array<{id:string, label:string, count:number, pinned:boolean, active:boolean}>}
 */
export function viewRowModel(views, activeId) {
  if (!Array.isArray(views)) return [];
  return views.map(v => ({
    id: v.view_id || '',
    label: v.name || '',
    count: Array.isArray(v.node_ids) ? v.node_ids.length : 0,
    pinned: Boolean(v.pinned),
    active: v.view_id === activeId,
  }));
}

/**
 * Determine whether a grounding object has enough data to offer saving.
 * Returns true iff grounding.node_ids is a non-empty array.
 *
 * @param {object|null|undefined} grounding
 * @returns {boolean}
 */
export function canSave(grounding) {
  if (!grounding) return false;
  return Array.isArray(grounding.node_ids) && grounding.node_ids.length > 0;
}
