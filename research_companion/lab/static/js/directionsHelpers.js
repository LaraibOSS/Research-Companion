/**
 * directionsHelpers.js — Pure, DOM-free helpers for the Brainstorm view's
 * Research Directions section (POST /api/directions). Mirrors the shape
 * convention of discoverHelpers.js.
 *
 * Testable with node --test (tests/js/directionsHelpers.test.mjs).
 *
 * ESCAPING CONTRACT (identical to discoverHelpers.js): `title`, `rationale`,
 * `typeBadge.label`, and every citation's `label` are returned ALREADY
 * HTML-escaped — interpolate them directly, do NOT re-escape (that would
 * double-escape). `directionId` and each citation's raw `paperId`/
 * `themeId`/`name`/`title` are NOT escaped — the caller must escapeHtml
 * them before writing into a DOM attribute.
 */
import { escapeHtml } from './format.js';

const _TYPE_LABELS = {
  extend_method: 'Extend a method',
  new_application: 'New application',
  underexplored_concept: 'Underexplored concept',
  open_gap: 'Open gap',
  cross_pollination: 'Cross-pollination',
  other: 'Other',
};

function _typeBadge(t) {
  const slug = _TYPE_LABELS[t] ? t : 'other';
  return { slug, label: escapeHtml(_TYPE_LABELS[slug]) };
}

/**
 * Map one raw POST /api/directions citation to a display model. Never
 * throws; a malformed/unknown-kind citation degrades to an informational
 * concept-style chip.
 *
 * ESCAPING: `label` is pre-escaped. `paperId`/`themeId`/`name`/`title` are
 * raw — escapeHtml them before writing into a DOM attribute.
 */
function _citationModel(raw) {
  const c = (raw && typeof raw === 'object') ? raw : {};
  const kind = ['paper', 'concept', 'gap'].includes(c.kind) ? c.kind : 'concept';

  if (kind === 'paper') {
    const title = (typeof c.title === 'string' && c.title) ? c.title : 'Untitled';
    const year = typeof c.year === 'number' ? c.year : null;
    const label = year != null ? `${title} (${year})` : title;
    return {
      kind: 'paper',
      label: escapeHtml(label),
      paperId: c.paper_id || null, // raw; null = not yet in the library, chip is informational
      title,
      year,
    };
  }
  if (kind === 'gap') {
    const title = (typeof c.title === 'string' && c.title) ? c.title : 'Untitled theme';
    return { kind: 'gap', label: escapeHtml(title), themeId: c.theme_id || null, title };
  }
  const name = (typeof c.name === 'string' && c.name) ? c.name : 'Untitled concept';
  return { kind: 'concept', label: escapeHtml(name), name };
}

/**
 * Map one raw POST /api/directions `directions[]` item to a display model
 * for the Brainstorm view's Research Directions section. Never throws;
 * every field defaults safely for a partial or malformed item.
 *
 * @param {object} raw — {direction_id, title, rationale, direction_type,
 *   citations, grounding_count, recency, score}
 * @returns {{directionId:string, title:string, rationale:string,
 *   typeBadge:{slug:string,label:string}, citations:Array, groundingCount:number,
 *   recency:number, score:number}}
 */
export function directionResultModel(raw) {
  const r = (raw && typeof raw === 'object') ? raw : {};
  const title = (typeof r.title === 'string' && r.title) ? r.title : 'Untitled direction';
  const rationale = typeof r.rationale === 'string' ? r.rationale : '';
  const citations = Array.isArray(r.citations) ? r.citations.map(_citationModel) : [];

  return {
    directionId: r.direction_id || '',
    title: escapeHtml(title),
    rationale: escapeHtml(rationale),
    typeBadge: _typeBadge(r.direction_type),
    citations,
    groundingCount: typeof r.grounding_count === 'number' ? r.grounding_count : 0,
    recency: typeof r.recency === 'number' ? r.recency : 0,
    score: typeof r.score === 'number' ? r.score : 0,
  };
}

// Column accessors for sortDirections. 'score' is the default/primary
// ranking column (the backend already returns directions ranked by score,
// so this normally only matters when the user picks a different column).
const _SORT_ACCESSORS = {
  score: r => (r && typeof r.score === 'number') ? r.score : null,
  recency: r => (r && typeof r.recency === 'number') ? r.recency : null,
};

/**
 * Sort directionResultModel rows by a column, nulls always last. Stable
 * (ties and null-groups keep their original relative order) and never
 * mutates the input; returns a new array. Any column not in
 * _SORT_ACCESSORS (including no column) returns a shallow copy with no
 * reordering.
 *
 * @param {Array|null|undefined} rows — row models from directionResultModel
 * @param {'score'|'recency'} col
 * @param {'asc'|'desc'} [dir='desc']
 * @returns {Array}
 */
export function sortDirections(rows, col, dir = 'desc') {
  const arr = Array.isArray(rows) ? rows : [];
  const accessor = _SORT_ACCESSORS[col];
  if (!accessor) return arr.slice();

  const mult = dir === 'asc' ? 1 : -1;
  const indexed = arr.map((row, idx) => ({ row, idx, val: accessor(row) }));

  indexed.sort((a, b) => {
    const aNull = a.val === null || a.val === undefined;
    const bNull = b.val === null || b.val === undefined;
    if (aNull && bNull) return a.idx - b.idx;
    if (aNull) return 1;
    if (bNull) return -1;
    const cmp = a.val < b.val ? -1 : a.val > b.val ? 1 : 0;
    if (cmp === 0) return a.idx - b.idx;
    return cmp * mult;
  });

  return indexed.map(x => x.row);
}
