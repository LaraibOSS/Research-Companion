/**
 * workspaceHelpers.js — Pure, DOM-free helpers for the Researches screen
 * and the topbar workspace switcher (W4-F1).
 *
 * Testable with node --test (tests/js/workspaceHelpers.test.mjs).
 */

const MAX_NAME_LENGTH = 80;

/**
 * Split a workspace list into active (non-archived) and archived buckets.
 * Active bucket is sorted: current-active workspace first, then by
 * stats.last_activity descending (never-active last), then by name
 * (case-insensitive) as a stable tie-breaker.
 *
 * Does not mutate the input list.
 *
 * @param {Array|null|undefined} list      — GET /api/workspaces records
 * @param {string|null} activeId           — currently active workspace id
 * @returns {{ active: Array, archived: Array }}
 */
export function splitWorkspaces(list, activeId) {
  const arr = Array.isArray(list) ? list : [];
  const active = arr.filter(w => !w.archived);
  const archived = arr.filter(w => !!w.archived);

  active.sort((a, b) => {
    // 1. Current-active workspace first
    const aCur = a.id === activeId ? 0 : 1;
    const bCur = b.id === activeId ? 0 : 1;
    if (aCur !== bCur) return aCur - bCur;

    // 2. last_activity desc; null/missing sorts last
    const aAct = (a.stats && a.stats.last_activity) || null;
    const bAct = (b.stats && b.stats.last_activity) || null;
    if (aAct !== bAct) {
      if (aAct === null) return 1;
      if (bAct === null) return -1;
      return aAct > bAct ? -1 : 1; // ISO strings compare lexicographically
    }

    // 3. Name asc (case-insensitive)
    const aName = String(a.name || a.id || '').toLowerCase();
    const bName = String(b.name || b.id || '').toLowerCase();
    return aName < bName ? -1 : aName > bName ? 1 : 0;
  });

  return { active, archived };
}

/**
 * Validate a proposed workspace name.
 *   - must be non-empty after trimming
 *   - must be <= 80 chars after trimming
 *   - must not duplicate an existing name (case-insensitive, trim-compared)
 *
 * @param {string|null|undefined} name
 * @param {string[]} [existingNames=[]]
 * @returns {{ ok: true, name: string } | { ok: false, error: string }}
 */
export function validateWorkspaceName(name, existingNames = []) {
  const trimmed = typeof name === 'string' ? name.trim() : '';
  if (!trimmed) {
    return { ok: false, error: 'Name is required' };
  }
  if (trimmed.length > MAX_NAME_LENGTH) {
    return { ok: false, error: `Name must be ${MAX_NAME_LENGTH} characters or fewer` };
  }
  const lower = trimmed.toLowerCase();
  const names = Array.isArray(existingNames) ? existingNames : [];
  for (const existing of names) {
    if (String(existing || '').trim().toLowerCase() === lower) {
      return { ok: false, error: 'A research with this name already exists' };
    }
  }
  return { ok: true, name: trimmed };
}

/**
 * Flatten a workspace record into a display model for cards and menus.
 *
 * @param {object} ws        — workspace record from GET /api/workspaces
 * @param {string|null} activeId
 * @returns {{ id, name, isActive, draftTitle, paperCount, openSuggestions,
 *             lastActivityIso, archived }}
 */
/**
 * Build the native-confirm() message for deleting a research.
 *
 * @param {string} name          — workspace display name
 * @param {number|null} paperCount — paper count, or null/non-number when unknown
 * @returns {string}
 */
export function deleteConfirmMessage(name, paperCount) {
  const n = Number(paperCount);
  if (paperCount === null || paperCount === undefined || Number.isNaN(n)) {
    return `Delete research "${name}"? This cannot be undone.`;
  }
  const papers = n === 1 ? 'paper' : 'papers';
  return `Delete research "${name}" and its ${n} ${papers}? This cannot be undone.`;
}

export function workspaceCardModel(ws, activeId) {
  const stats = (ws && ws.stats) || {};
  return {
    id: ws.id,
    name: ws.name || ws.id,
    isActive: ws.id === activeId,
    draftTitle: stats.draft_title || null,
    paperCount: Number(stats.papers) || 0,
    openSuggestions: Number(stats.open_suggestions) || 0,
    lastActivityIso: stats.last_activity || null,
    archived: !!ws.archived,
  };
}

/**
 * Flatten a workspace record into a row model for the Researches table.
 * Never throws — every field defaults safely when stats are missing/partial.
 *
 * @param {object} ws        — workspace record from GET /api/workspaces
 * @param {string|null} activeId
 * @returns {{ id, name, isActive, hasDraft, draftTitle, papers, analyzed,
 *             failed, draftVersions, coveragePct, coverageLabel,
 *             strengthSegments, openSuggestions, draftUpdatedIso,
 *             lastActivityIso, createdAtIso, archived }}
 */
export function researchRowModel(ws, activeId) {
  const w = ws || {};
  const stats = w.stats || {};

  const papers = Number(stats.papers) || 0;
  const failed = Number(stats.failed) || 0;
  const analyzed = Math.max(0, papers - failed);
  const draftTitle = stats.draft_title || null;

  const coverage = stats.coverage || null;
  const coverageLabel = coverage ? `${coverage.in_library}/${coverage.total}` : '—';
  const coveragePct = coverage && coverage.total
    ? Math.round((100 * coverage.in_library) / coverage.total)
    : null;

  const strength = stats.strength || {};
  const strengthSegments = [
    { band: 'strong', count: Number(strength.strong) || 0 },
    { band: 'moderate', count: Number(strength.moderate) || 0 },
    { band: 'weak', count: Number(strength.weak) || 0 },
  ];

  return {
    id: w.id,
    name: w.name || w.id,
    isActive: w.id === activeId,
    hasDraft: !!draftTitle,
    draftTitle,
    papers,
    analyzed,
    failed,
    draftVersions: Number(stats.draft_versions) || 0,
    coveragePct,
    coverageLabel,
    strengthSegments,
    openSuggestions: Number(stats.open_suggestions) || 0,
    draftUpdatedIso: stats.draft_updated || null,
    lastActivityIso: stats.last_activity || null,
    createdAtIso: w.created_at || null,
    archived: !!w.archived,
  };
}

// Column accessors for sortResearchRows. Each returns a comparable value
// (string/number) or null/undefined when the row lacks that field.
const _SORT_ACCESSORS = {
  name: r => (r && r.name) || '',
  papers: r => (r && typeof r.papers === 'number') ? r.papers : null,
  coverage: r => (r && r.coveragePct != null) ? r.coveragePct : null,
  lastActivity: r => (r && r.lastActivityIso) || null,
  created: r => (r && r.createdAtIso) || null,
  draftUpdated: r => (r && r.draftUpdatedIso) || null,
};

/**
 * Sort research row models by a column, nulls always last.
 * Stable (ties and null-groups keep their original relative order) and
 * never mutates the input; returns a new array.
 *
 * @param {Array|null|undefined} rows
 * @param {'name'|'papers'|'coverage'|'lastActivity'|'created'|'draftUpdated'} col
 * @param {'asc'|'desc'} dir
 * @returns {Array}
 */
export function sortResearchRows(rows, col, dir) {
  if (!Array.isArray(rows)) return [];
  const accessor = _SORT_ACCESSORS[col] || _SORT_ACCESSORS.name;
  const mult = dir === 'desc' ? -1 : 1;

  const indexed = rows.map((row, idx) => ({ row, idx, val: accessor(row) }));

  indexed.sort((a, b) => {
    const aNull = a.val === null || a.val === undefined;
    const bNull = b.val === null || b.val === undefined;
    if (aNull && bNull) return a.idx - b.idx;
    if (aNull) return 1;   // nulls sort last regardless of dir
    if (bNull) return -1;

    let cmp;
    if (typeof a.val === 'string' || typeof b.val === 'string') {
      const av = String(a.val).toLowerCase();
      const bv = String(b.val).toLowerCase();
      cmp = av < bv ? -1 : av > bv ? 1 : 0;
    } else {
      cmp = a.val < b.val ? -1 : a.val > b.val ? 1 : 0;
    }
    if (cmp === 0) return a.idx - b.idx; // stable tie-break
    return cmp * mult;
  });

  return indexed.map(x => x.row);
}
