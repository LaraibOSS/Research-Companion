/**
 * brainstormSessionHelpers.js — pure (de)serialization for the persisted
 * Brainstorm session. Dependency-free and node-testable (no DOM, no store).
 *
 * The Brainstorm tab kept all state in memory, so it reset to empty on every
 * revisit. These helpers turn the serializable slice of that state into a
 * versioned blob for GET/PUT /api/brainstorm/session and back, tolerating
 * missing or older-shaped payloads. Loading/error/UI-only flags are never
 * persisted.
 */

export const BRAINSTORM_SESSION_VERSION = 1;

function _arr(x) { return Array.isArray(x) ? x : []; }
function _str(x) { return typeof x === 'string' ? x : ''; }
function _obj(x) { return (x && typeof x === 'object' && !Array.isArray(x)) ? x : {}; }

/**
 * Build the persistable blob from the tab's live state.
 * @param {object} state — {topic, queriesUsed, expandedFlag, rawResults,
 *   rawDirections, hasSearched, directionsHasGenerated, novelty (dirId->result),
 *   libraryIds (array), brief}
 * @returns {object} versioned payload. Never throws.
 */
export function serializeSession(state) {
  const s = _obj(state);
  return {
    v: BRAINSTORM_SESSION_VERSION,
    topic: _str(s.topic),
    queriesUsed: _arr(s.queriesUsed),
    expandedFlag: !!s.expandedFlag,
    rawResults: _arr(s.rawResults),
    rawDirections: _arr(s.rawDirections),
    hasSearched: !!s.hasSearched,
    directionsHasGenerated: !!s.directionsHasGenerated,
    // novelty: dirId -> verdict result only (drop loading/error UI flags)
    novelty: _obj(s.novelty),
    libraryIds: _arr(s.libraryIds),
    // brief: added in slice 2; carried through verbatim when present
    brief: (s.brief && typeof s.brief === 'object') ? s.brief : null,
  };
}

/**
 * Reconstitute the tab's serializable state from a stored blob. Tolerant of
 * null / missing fields / an unknown version (fields default to empty).
 * @param {object|null} payload
 * @returns {object} normalized state. Never throws.
 */
export function hydrateSession(payload) {
  const p = _obj(payload);
  return {
    topic: _str(p.topic),
    queriesUsed: _arr(p.queriesUsed),
    expandedFlag: !!p.expandedFlag,
    rawResults: _arr(p.rawResults),
    rawDirections: _arr(p.rawDirections),
    hasSearched: !!p.hasSearched,
    directionsHasGenerated: !!p.directionsHasGenerated,
    novelty: _obj(p.novelty),
    libraryIds: _arr(p.libraryIds),
    brief: (p.brief && typeof p.brief === 'object') ? p.brief : null,
  };
}

/**
 * True when a session blob carries anything worth restoring — so hydrate can
 * skip a no-op paint for a brand-new, empty research.
 * @param {object|null} payload
 * @returns {boolean}
 */
export function sessionHasContent(payload) {
  const s = hydrateSession(payload);
  return !!(s.topic || s.rawResults.length || s.rawDirections.length
    || Object.keys(s.novelty).length || s.brief);
}
