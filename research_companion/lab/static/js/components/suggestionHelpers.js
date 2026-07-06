/**
 * components/suggestionHelpers.js — Pure helpers for the suggestions panel.
 * DOM-free: no document/window references. Node-testable.
 *
 * Exports:
 *   groupSuggestions(list, mode) -> [{key, label, items}]
 *   countOpen(list) -> number
 *   highestOpenSeverity(list) -> 'high'|'medium'|'low'|null
 *   severityRank(s) -> number
 *   diffStatuses(prev, next) -> {addressed: [ids]}
 */

// ---------------------------------------------------------------------------
// Severity helpers
// ---------------------------------------------------------------------------

const _SEV_RANK = { high: 3, medium: 2, low: 1 };
const _SEV_ORDER = ['high', 'medium', 'low'];

/**
 * Return numeric rank for a severity string. Unknown = 0.
 * @param {string} s
 * @returns {number}
 */
export function severityRank(s) {
  return _SEV_RANK[s] || 0;
}

// ---------------------------------------------------------------------------
// countOpen
// ---------------------------------------------------------------------------

/**
 * Count suggestions with status === 'open'.
 * @param {Array} list
 * @returns {number}
 */
export function countOpen(list) {
  if (!Array.isArray(list)) return 0;
  return list.filter(s => s.status === 'open').length;
}

// ---------------------------------------------------------------------------
// highestOpenSeverity
// ---------------------------------------------------------------------------

/**
 * Return the highest severity among open suggestions, or null if none open.
 * @param {Array} list
 * @returns {'high'|'medium'|'low'|null}
 */
export function highestOpenSeverity(list) {
  if (!Array.isArray(list)) return null;
  let best = 0;
  for (const s of list) {
    if (s.status !== 'open') continue;
    const rank = severityRank(s.severity);
    if (rank > best) best = rank;
  }
  if (best === 0) return null;
  if (best >= 3) return 'high';
  if (best >= 2) return 'medium';
  return 'low';
}

// ---------------------------------------------------------------------------
// groupSuggestions
// ---------------------------------------------------------------------------

/**
 * Group a suggestion list by mode.
 * @param {Array} list
 * @param {'severity'|'kind'|'section'} mode
 * @returns {Array<{key: string, label: string, items: Array}>}
 */
export function groupSuggestions(list, mode) {
  if (!Array.isArray(list)) return [];

  if (mode === 'severity') {
    return _groupBySeverity(list);
  }
  if (mode === 'kind') {
    return _groupByKind(list);
  }
  // default: section
  return _groupBySection(list);
}

function _groupBySeverity(list) {
  const buckets = { high: [], medium: [], low: [] };
  for (const s of list) {
    const sev = s.severity in buckets ? s.severity : 'low';
    buckets[sev].push(s);
  }
  const labels = { high: 'High', medium: 'Medium', low: 'Low' };
  return _SEV_ORDER
    .filter(sev => buckets[sev].length > 0)
    .map(sev => ({ key: sev, label: labels[sev], items: buckets[sev] }));
}

function _groupByKind(list) {
  const buckets = new Map();
  for (const s of list) {
    const k = s.kind || 'other';
    if (!buckets.has(k)) buckets.set(k, []);
    buckets.get(k).push(s);
  }
  return [...buckets.entries()]
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([key, items]) => ({
      key,
      label: _kindLabel(key),
      items,
    }));
}

function _groupBySection(list) {
  const buckets = new Map();
  for (const s of list) {
    const k = s.section_id || '__general__';
    if (!buckets.has(k)) buckets.set(k, []);
    buckets.get(k).push(s);
  }
  // Sort: non-null section_ids alphabetically, null last
  const entries = [...buckets.entries()];
  entries.sort(([a], [b]) => {
    if (a === '__general__' && b !== '__general__') return 1;
    if (b === '__general__' && a !== '__general__') return -1;
    return a.localeCompare(b);
  });
  return entries.map(([key, items]) => ({
    key,
    label: key === '__general__' ? 'General' : key,
    items,
  }));
}

function _kindLabel(kind) {
  const MAP = {
    citation:     'Citation',
    novelty:      'Novelty',
    evidence:     'Evidence',
    benchmark:    'Benchmark',
    related_work: 'Related Work',
    gap:          'Gap',
    structure:    'Structure',
  };
  return MAP[kind] || kind.charAt(0).toUpperCase() + kind.slice(1);
}

// ---------------------------------------------------------------------------
// diffStatuses
// ---------------------------------------------------------------------------

/**
 * Compare prev and next lists; return IDs that transitioned open -> addressed.
 * Dismissed->addressed and new IDs are NOT reported.
 * @param {Array} prev
 * @param {Array} next
 * @returns {{ addressed: string[] }}
 */
export function diffStatuses(prev, next) {
  const prevMap = new Map();
  for (const s of (prev || [])) prevMap.set(s.id, s.status);

  const addressed = [];
  for (const s of (next || [])) {
    const prevStatus = prevMap.get(s.id);
    // Only report open -> addressed (id must exist in prev AND was open)
    if (prevStatus === 'open' && s.status === 'addressed') {
      addressed.push(s.id);
    }
  }
  return { addressed };
}
