/**
 * noteOriginHelpers.js — resolving a note's recorded origin to a route.
 *
 * A note stores three flat strings: `origin_kind`, `origin_id` and
 * `origin_label`. This module is the ONLY place that knows how a kind maps
 * to a route.
 *
 * The route is derived here rather than stored in the note on purpose.
 * Storing a route would freeze navigation into data, and a single route
 * rename would orphan every note ever written.
 *
 * A stale id is an expected state, not an error. `gap_id` is
 * content-addressed and stable, but a `theme_id` is derived from its member
 * gap_ids, so a re-clustering run can orphan one. That is exactly why an
 * origin carries a label as well as an id: when the link stops resolving the
 * note still reads "from ◇ Gap · Expand evaluations", it just stops being
 * clickable. An id-only origin would degrade to "from a gap", which is worse
 * than storing nothing.
 *
 * Pure and DOM-free (mirrors handoffHelpers.js); callers pass
 * `window.location.hash` in rather than this module reaching for it.
 */

/** True for a string with something in it. */
function _str(value) {
  return (typeof value === 'string' && value.trim()) ? value : null;
}

/**
 * How each origin kind is reached, and how it is labelled.
 *
 * Adding a kind is one row here plus a producer that writes it — no schema
 * change, no migration, and every note already on disk keeps working. A kind
 * with `route: null` is displayable but not navigable (an Ask origin has no
 * durable id — the question text is the only handle).
 */
const _KINDS = {
  gap: { badge: '◇ Gap', route: (id) => `#/gaps?theme=${encodeURIComponent(id)}` },
  ask: { badge: '? Question', route: null },
  brief: { badge: '§ Brief', route: null },
};

/**
 * Resolve a stored origin to something renderable.
 *
 * @param {object|null} origin — {kind, id, label}, as read off a note record
 *   (origin_kind / origin_id / origin_label).
 * @returns {{href: string|null, label: string, badge: string, canOpen: boolean}}
 *   `canOpen` false means render the label as plain text. Never throws.
 */
export function originLink(origin) {
  const o = (origin && typeof origin === 'object' && !Array.isArray(origin))
    ? origin
    : {};
  const kind = _str(o.kind);
  const id = _str(o.id);
  const label = _str(o.label) || '';
  const entry = kind ? _KINDS[kind] : null;

  if (!entry || !entry.route || !id) {
    return { href: null, label, badge: entry ? entry.badge : '', canOpen: false };
  }

  // Guard encodeURIComponent: an id with unpaired UTF-16 surrogates throws
  // URIError. Degrade to non-openable rather than propagating the error,
  // mirroring themeFromHash's treatment of malformed percent-escapes.
  let href = null;
  try {
    href = entry.route(id);
  } catch {
    // Malformed id: preserve label, return non-openable shape.
    return { href: null, label, badge: entry.badge, canOpen: false };
  }
  return { href, label, badge: entry.badge, canOpen: true };
}

/**
 * The `theme` a `#/gaps?theme=<id>` hash asks for.
 *
 * Mirrors `sectionFromHash` in handoffHelpers.js exactly, so the two cannot
 * disagree about what a route parameter means.
 *
 * @param {string|null} hash — normally `window.location.hash`
 * @returns {string|null} Never throws, including on a malformed escape.
 */
export function themeFromHash(hash) {
  if (typeof hash !== 'string' || !hash) return null;
  // `[?&]` so `subtheme=` cannot satisfy a request for `theme=`.
  const match = hash.match(/[?&]theme=([^&]*)/);
  if (!match) return null;
  let value = match[1];
  try {
    value = decodeURIComponent(value);
  } catch {
    // A malformed escape is not a reason to fail navigation; use it raw.
  }
  return _str(value);
}
