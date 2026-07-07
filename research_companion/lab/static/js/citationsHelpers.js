/**
 * citationsHelpers.js — Pure, DOM-free helpers for the Citation Coverage UI (W5-C3).
 *
 * All functions are stateless and have no DOM dependencies
 * so they can be tested with node --test.
 */

// ---------------------------------------------------------------------------
// Status ordering for groupByStatus
// ---------------------------------------------------------------------------

const STATUS_ORDER = ['available', 'unchecked', 'unresolved', 'in_library'];

// ---------------------------------------------------------------------------
// Exported helpers
// ---------------------------------------------------------------------------

/**
 * Extract the counts object from a coverage response, zeroing any missing fields.
 * Safe on null/undefined input.
 *
 * @param {object|null|undefined} coverage
 * @returns {{ total, in_library, available, unchecked, unresolved }}
 */
export function coverageCounts(coverage) {
  const raw = coverage && coverage.counts ? coverage.counts : {};
  return {
    total:      raw.total      || 0,
    in_library: raw.in_library || 0,
    available:  raw.available  || 0,
    unchecked:  raw.unchecked  || 0,
    unresolved: raw.unresolved || 0,
  };
}

/**
 * Total number of cited papers that are not yet in the library.
 *
 * @param {{ total: number, in_library: number }} counts
 * @returns {number}
 */
export function missingCount(counts) {
  return (counts.total || 0) - (counts.in_library || 0);
}

/**
 * Generate the human-readable banner summary text.
 *
 * @param {{ total: number, in_library: number }} counts
 * @returns {string}
 */
export function bannerText(counts) {
  return `Analysis covers ${counts.in_library} of ${counts.total} cited papers`;
}

/**
 * Map a reference entry's status to a display chip.
 *
 * @param {{ status: string }} entry
 * @returns {{ label: string, cls: string }}
 */
export function statusChip(entry) {
  switch (entry.status) {
    case 'in_library': return { label: 'In library ✓', cls: 'chip-ok' };
    case 'available':  return { label: 'Add ↓',       cls: 'chip-add' };
    case 'unchecked':  return { label: 'Not checked',      cls: 'chip-muted' };
    case 'unresolved': return { label: 'Unresolved ?',     cls: 'chip-warn' };
    default:           return { label: entry.status || '', cls: 'chip-muted' };
  }
}

/**
 * Return the subset of references that are available AND have an add_target.
 * These are the rows that can be added in the "Add all" bulk action.
 *
 * @param {object|null} coverage
 * @returns {Array}
 */
export function availableEntries(coverage) {
  if (!coverage) return [];
  const refs = Array.isArray(coverage.references) ? coverage.references : [];
  return refs.filter(r => r.status === 'available' && r.add_target);
}

/**
 * Return a flat array of references ordered by group:
 *   available, unchecked, unresolved, in_library
 * Within each group, entries appear in their original bibliography index order.
 *
 * @param {Array|null} references
 * @returns {Array}
 */
export function groupByStatus(references) {
  if (!Array.isArray(references) || references.length === 0) return [];

  const groups = {};
  for (const status of STATUS_ORDER) groups[status] = [];
  const other = [];

  for (const ref of references) {
    if (STATUS_ORDER.includes(ref.status)) {
      groups[ref.status].push(ref);
    } else {
      other.push(ref);
    }
  }

  const result = [];
  for (const status of STATUS_ORDER) {
    result.push(...groups[status]);
  }
  result.push(...other);
  return result;
}
