/**
 * gapHelpers.js — Pure, DOM-free helpers for the dedicated Gaps view
 * (gap-analysis-section). Mirrors the shape convention of workspaceHelpers.js.
 *
 * Testable with node --test (tests/js/gapHelpers.test.mjs).
 */

const STATUS_LABELS = {
  open: 'Open',
  partial: 'Partially addressed',
  addressed: 'Addressed',
};

const FWS_LABELS = {
  method: 'Method',
  resources: 'Resources',
  evaluation: 'Evaluation',
  application: 'Application',
  problem: 'Problem',
  other: 'Other',
};

/**
 * Flatten a theme record (GET /api/gaps `themes[]` shape) into a display
 * model for the Gaps view. Never throws — every field defaults safely when
 * the payload is partial (e.g. an older cached synthesis).
 *
 * @param {object} theme — {theme_id, title, bullet, fws_type, type,
 *   citations, status, frequency, recency, score, gap_ids}
 * @param {string[]|null|undefined} draftAddresses — GET /api/gaps
 *   `draft_addresses` (gap_ids the current draft resolves). A theme is
 *   `addressedByDraft` when one of its own member gap_ids appears there.
 * @returns {{ id, title, bullet, typeLabel, typeKey, fwsLabel, fwsKey,
 *   statusLabel, statusKey, citations, frequency, recency, score,
 *   addressedByDraft }}
 */
export function gapThemeRowModel(theme, draftAddresses) {
  const t = theme || {};
  const statusKey = STATUS_LABELS[t.status] ? t.status : 'open';
  const addresses = Array.isArray(draftAddresses) ? draftAddresses : [];
  const gapIds = Array.isArray(t.gap_ids) ? t.gap_ids : [];
  const addressedByDraft = gapIds.some(gid => addresses.includes(gid));

  const citations = Array.isArray(t.citations) ? t.citations.map(c => ({
    paperId: (c && c.paper_id) || '',
    title: (c && c.title) || (c && c.paper_id) || 'Untitled',
    year: (c && c.year) != null ? c.year : null,
  })) : [];

  const typeKey = t.type === 'future_work' ? 'future_work' : 'limitation';
  const fwsKey = FWS_LABELS[t.fws_type] ? t.fws_type : 'other';

  return {
    id: t.theme_id || '',
    title: t.title || 'Untitled theme',
    bullet: t.bullet || '',
    typeLabel: typeKey === 'future_work' ? 'Future work' : 'Limitation',
    typeKey,
    fwsLabel: FWS_LABELS[fwsKey],
    fwsKey,
    statusLabel: STATUS_LABELS[statusKey],
    statusKey,
    citations,
    frequency: typeof t.frequency === 'number' ? t.frequency : citations.length,
    recency: t.recency != null ? t.recency : null,
    score: typeof t.score === 'number' ? t.score : 0,
    addressedByDraft,
  };
}

// Column accessors for sortGapThemes. Each returns a comparable value or
// null/undefined when the row model lacks that field.
const _SORT_ACCESSORS = {
  score: r => (r && typeof r.score === 'number') ? r.score : null,
  recency: r => (r && r.recency != null) ? r.recency : null,
  frequency: r => (r && typeof r.frequency === 'number') ? r.frequency : null,
  title: r => (r && r.title) || '',
};

/**
 * Sort gap-theme row models by a column, nulls always last. Stable (ties and
 * null-groups keep their original relative order) and never mutates the
 * input; returns a new array.
 *
 * @param {Array|null|undefined} rows — row models from gapThemeRowModel
 * @param {'score'|'recency'|'frequency'|'title'} col
 * @param {'asc'|'desc'} dir
 * @returns {Array}
 */
export function sortGapThemes(rows, col, dir) {
  if (!Array.isArray(rows)) return [];
  const accessor = _SORT_ACCESSORS[col] || _SORT_ACCESSORS.score;
  const mult = dir === 'desc' ? -1 : 1;

  const indexed = rows.map((row, idx) => ({ row, idx, val: accessor(row) }));

  indexed.sort((a, b) => {
    const aNull = a.val === null || a.val === undefined;
    const bNull = b.val === null || b.val === undefined;
    if (aNull && bNull) return a.idx - b.idx;
    if (aNull) return 1;
    if (bNull) return -1;

    let cmp;
    if (typeof a.val === 'string' || typeof b.val === 'string') {
      const av = String(a.val).toLowerCase();
      const bv = String(b.val).toLowerCase();
      cmp = av < bv ? -1 : av > bv ? 1 : 0;
    } else {
      cmp = a.val < b.val ? -1 : a.val > b.val ? 1 : 0;
    }
    if (cmp === 0) return a.idx - b.idx;
    return cmp * mult;
  });

  return indexed.map(x => x.row);
}

/**
 * Filter gap-theme row models by type and/or status. `'all'` (or a falsy
 * value) means "no filter" for that dimension. Never mutates the input;
 * returns a new array.
 *
 * @param {Array|null|undefined} rows
 * @param {{type?: 'limitation'|'future_work'|'all', status?: 'open'|'partial'|'addressed'|'all'}|null|undefined} filters
 * @returns {Array}
 */
export function filterGapThemes(rows, filters) {
  const arr = Array.isArray(rows) ? rows : [];
  const f = filters || {};
  const typeFilter = f.type && f.type !== 'all' ? f.type : null;
  const statusFilter = f.status && f.status !== 'all' ? f.status : null;

  return arr.filter(r => {
    if (typeFilter && r.typeKey !== typeFilter) return false;
    if (statusFilter && r.statusKey !== statusFilter) return false;
    return true;
  });
}
