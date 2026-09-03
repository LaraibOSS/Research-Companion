/**
 * handoffHelpers.js — navigating to another surface and carrying an argument.
 *
 * The Lab moves the reader between surfaces in three ways: a `rc:*` custom
 * event, a `#/route?param=` hash, and a `window.__rcPending*` handoff for the
 * case where the event lands before the receiving view has mounted. Each of
 * those was hand-rolled at every call site, and two of them drifted:
 *
 *   - `views/library.js` read `detail.paperId` while gaps, report, timeline
 *     and brainstorm dispatched `detail.paper_id`. Five of seven "open this
 *     paper" edges were dead through the event path and survived only on the
 *     `__rcPendingPaper` fallback — which is drained on mount, so from Library
 *     itself the click did nothing at all.
 *   - `views/suggestions.js` linked to `#/draft?section=<id>` and
 *     `views/draft.js` never read the hash, so the link always landed on the
 *     first section.
 *
 * Parsing lives here so there is one place to be right, and one place to test.
 * Pure and DOM-free; callers pass `window.location.hash` in rather than this
 * module reaching for it.
 */

/** True for a string with something in it. */
function _id(value) {
  return (typeof value === 'string' && value.trim()) ? value : null;
}

/**
 * The paper id carried by a `rc:open-paper` detail, in either spelling.
 *
 * Both are accepted on purpose. Normalising every caller and trusting it to
 * stay normalised is precisely what failed across five files; a reader that
 * takes either cannot break that way again.
 *
 * @param {object|null} detail — a CustomEvent's `detail`
 * @returns {string|null} Never throws.
 */
export function paperIdFromDetail(detail) {
  if (!detail || typeof detail !== 'object') return null;
  return _id(detail.paperId) || _id(detail.paper_id);
}

/**
 * The paper ids carried by a handoff, as a list.
 *
 * Compare hands over two at once ("open both in library"); everything else
 * hands over one. Blanks, non-strings and duplicates are dropped — opening the
 * same paper twice is one drawer, not two.
 *
 * @param {object|null} detail
 * @returns {string[]} Possibly empty. Never throws.
 */
export function paperIdsFromDetail(detail) {
  if (!detail || typeof detail !== 'object') return [];
  const many = Array.isArray(detail.paperIds) ? detail.paperIds : null;
  const raw = many || [detail.paperId, detail.paper_id];
  const out = [];
  for (const value of raw) {
    const id = _id(value);
    if (id && !out.includes(id)) out.push(id);
  }
  return out;
}

/**
 * The `section` a `#/route?section=<id>` hash asks for.
 *
 * Mirrors what `views/graph.js` already does for its own route, so the two
 * cannot disagree about what a section link means.
 *
 * @param {string|null} hash — normally `window.location.hash`
 * @returns {string|null} Never throws, including on a malformed escape.
 */
export function sectionFromHash(hash) {
  if (typeof hash !== 'string' || !hash) return null;
  // `[?&]` so `subsection=` cannot satisfy a request for `section=`.
  const match = hash.match(/[?&]section=([^&]*)/);
  if (!match) return null;
  let value = match[1];
  try {
    value = decodeURIComponent(value);
  } catch {
    // A malformed escape is not a reason to fail navigation; use it raw.
  }
  return _id(value);
}
