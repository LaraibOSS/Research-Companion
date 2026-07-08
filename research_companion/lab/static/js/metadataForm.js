/**
 * metadataForm.js — Pure, DOM-free helpers for the manual metadata edit form.
 *
 * These build the PATCH /api/papers/{id} body from raw form-input strings,
 * obeying the backend contract:
 *   - title:  send trimmed string only when non-empty (never send title:null).
 *   - authors: comma-split, trim, drop blanks; always send the array ([] clears).
 *   - year:   blank -> null (clears); valid int in 1900-2100 -> int;
 *             otherwise an error (do not submit).
 *
 * Stateless / no DOM so they can be tested with node --test.
 */

/**
 * Parse a comma-separated authors string into a clean array.
 * Splits on commas, trims each, drops blanks.
 *
 * @param {string|null|undefined} str
 * @returns {string[]}
 */
export function parseAuthorsInput(str) {
  if (str == null) return [];
  return String(str)
    .split(',')
    .map(s => s.trim())
    .filter(Boolean);
}

/**
 * Parse a year input string.
 *   blank/whitespace         -> { ok: true, value: null }   (clear)
 *   integer in 1900..2100    -> { ok: true, value: <int> }
 *   non-numeric / out-range  -> { ok: false, error: <msg> }
 *
 * @param {string|number|null|undefined} str
 * @returns {{ ok: true, value: number|null } | { ok: false, error: string }}
 */
export function parseYearInput(str) {
  const t = (str == null ? '' : String(str)).trim();
  if (t === '') return { ok: true, value: null };
  if (!/^\d+$/.test(t)) {
    return { ok: false, error: 'Year must be a whole number between 1900 and 2100' };
  }
  const n = parseInt(t, 10);
  if (n < 1900 || n > 2100) {
    return { ok: false, error: 'Year must be between 1900 and 2100' };
  }
  return { ok: true, value: n };
}

/**
 * Assemble the PATCH body from raw form inputs.
 * Returns { body } on success or { error } when the year is invalid.
 *
 * @param {{ title?: string, authorsStr?: string, yearStr?: string }} inputs
 * @returns {{ body: object } | { error: string }}
 */
export function buildPaperPatch({ title, authorsStr, yearStr } = {}) {
  const yr = parseYearInput(yearStr);
  if (!yr.ok) return { error: yr.error };

  const body = {};

  const t = (title == null ? '' : String(title)).trim();
  if (t !== '') body.title = t; // never send title:null (silent no-op)

  body.authors = parseAuthorsInput(authorsStr); // [] clears authors
  body.year = yr.value;                          // null clears year

  return { body };
}
