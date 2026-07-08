/**
 * placementHelpers.js — Pure, DOM-free helpers for the Citation Placement UI.
 *
 * Placement is a draft-quality check (separate from paper strength): it flags
 * whether cited papers sit in the section where the alignment engine judges them
 * most relevant. All functions here are stateless and DOM-free so they can be
 * tested with `node --test`.
 */

// Order: most-actionable first.
const STATUS_ORDER = ['misplaced', 'unknown', 'well_placed'];

/**
 * Extract the counts object from a placement response, zeroing missing fields.
 * Safe on null/undefined input.
 *
 * @param {object|null|undefined} placement
 * @returns {{ total, well_placed, misplaced, unknown }}
 */
export function placementCounts(placement) {
  const raw = placement && placement.counts ? placement.counts : {};
  return {
    total:       raw.total       || 0,
    well_placed: raw.well_placed || 0,
    misplaced:   raw.misplaced   || 0,
    unknown:     raw.unknown     || 0,
  };
}

/**
 * Map a placement status to a display chip.
 *
 * @param {string} status
 * @returns {{ label: string, cls: string }}
 */
export function statusChip(status) {
  switch (status) {
    case 'well_placed': return { label: 'Well placed ✓', cls: 'chip-ok' };
    case 'misplaced':   return { label: 'Misplaced ⚠',   cls: 'chip-warn' };
    case 'unknown':     return { label: 'Unknown',        cls: 'chip-muted' };
    default:            return { label: status || '',      cls: 'chip-muted' };
  }
}

/**
 * Return placements ordered by status group (misplaced, unknown, well_placed),
 * preserving the server's within-group order.
 *
 * @param {Array|null} placements
 * @returns {Array}
 */
export function groupByStatus(placements) {
  if (!Array.isArray(placements) || placements.length === 0) return [];
  const groups = {};
  for (const s of STATUS_ORDER) groups[s] = [];
  const other = [];
  for (const pl of placements) {
    if (STATUS_ORDER.includes(pl.status)) groups[pl.status].push(pl);
    else other.push(pl);
  }
  const result = [];
  for (const s of STATUS_ORDER) result.push(...groups[s]);
  result.push(...other);
  return result;
}

/**
 * Comma-joined titles of the sections a paper is cited in.
 *
 * @param {{cited_sections?: Array<{title: string}>}} placement
 * @returns {string}
 */
export function citedSectionTitles(placement) {
  const secs = placement && Array.isArray(placement.cited_sections)
    ? placement.cited_sections : [];
  return secs.map(s => s.title).filter(Boolean).join(', ');
}
