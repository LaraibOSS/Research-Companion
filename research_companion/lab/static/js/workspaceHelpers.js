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
