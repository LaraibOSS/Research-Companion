/**
 * libraryHelpers.js — Pure, DOM-free helpers for the library list view (W4-F2).
 *
 * All functions are stateless and have no DOM dependencies
 * so they can be tested with node --test.
 */

/**
 * Map a paper's raw store status to the UI status label.
 * failed -> 'failed', processing -> 'processing', done -> 'ingested', else -> 'queued'
 *
 * @param {object} paper
 * @returns {'failed'|'processing'|'ingested'|'queued'}
 */
export function deriveStatus(paper) {
  const s = paper && paper.status;
  if (s === 'failed')     return 'failed';
  if (s === 'processing') return 'processing';
  if (s === 'done')       return 'ingested';
  return 'queued';
}

/**
 * True when a paper is missing authors or year — i.e. it needs manual
 * metadata so it appears on the timeline and matches citations.
 * Missing = year is null/undefined OR authors is empty/absent.
 *
 * @param {object|null|undefined} paper
 * @returns {boolean}
 */
export function needsMetadata(paper) {
  if (!paper) return false;
  const noYear    = paper.year == null;
  const noAuthors = !(Array.isArray(paper.authors) && paper.authors.length > 0);
  return noYear || noAuthors;
}

// Tie-break priority: strengthens > challenges > alternative
const RELATION_PRIORITY = ['strengthens', 'challenges', 'alternative'];

/**
 * Return the dominant stance relation (highest count wins; tie-break
 * strengthens > challenges > alternative; all-zero/missing -> null).
 *
 * @param {object|null|undefined} stanceCounts  — {strengthens, challenges, alternative}
 * @returns {'strengthens'|'challenges'|'alternative'|null}
 */
export function dominantRelation(stanceCounts) {
  if (!stanceCounts || typeof stanceCounts !== 'object') return null;

  const s = stanceCounts.strengthens  || 0;
  const c = stanceCounts.challenges   || 0;
  const a = stanceCounts.alternative  || 0;

  if (s === 0 && c === 0 && a === 0) return null;

  // Sort by count descending, then by priority for tie-breaking
  const counts = [
    { rel: 'strengthens',  n: s, pri: 0 },
    { rel: 'challenges',   n: c, pri: 1 },
    { rel: 'alternative',  n: a, pri: 2 },
  ];
  counts.sort((x, y) => {
    if (y.n !== x.n) return y.n - x.n;
    return x.pri - y.pri;
  });

  return counts[0].rel;
}

/**
 * Build row objects for the library table.
 * The draft row (matching draftId) is placed first; all others follow.
 *
 * @param {Map|Array} papersMapOrArray  — papers from the store
 * @param {string|null} draftId         — current draft paper_id (or null)
 * @returns {Array<{paperId, title, year, status, strengthBand, strengthScore,
 *                  relation, addedAt, isDraft, failureReason}>}
 */
export function buildRows(papersMapOrArray, draftId) {
  // Normalise to array
  let papers;
  if (papersMapOrArray instanceof Map) {
    papers = [...papersMapOrArray.values()];
  } else if (Array.isArray(papersMapOrArray)) {
    papers = papersMapOrArray;
  } else {
    return [];
  }

  const toRow = (paper) => ({
    paperId:       paper.paper_id,
    title:         paper.title || '',
    authors:       Array.isArray(paper.authors) ? paper.authors : [],
    year:          paper.year  || null,
    status:        deriveStatus(paper),
    strengthBand:  paper.strength ? (paper.strength.band || null) : null,
    strengthScore: paper.strength && paper.strength.score != null ? paper.strength.score : null,
    relation:      dominantRelation(paper.stance_counts),
    addedAt:       paper.added_at || null,
    isDraft:       draftId != null && paper.paper_id === draftId,
    failureReason: paper.failure_reason || null,
    needsMetadata: needsMetadata(paper),
  });

  const draftRow  = papers.filter(p => draftId != null && p.paper_id === draftId).map(toRow);
  const otherRows = papers.filter(p => draftId == null || p.paper_id !== draftId).map(toRow);

  return [...draftRow, ...otherRows];
}

/**
 * Decide the drawer draft-action for a paper given the current draft.
 * If the paper IS the draft, the action unsets it; otherwise it sets it.
 *
 * @param {string} paperId
 * @param {string|null|undefined} draftId — current draft paper_id from the store
 * @returns {{label: string, next: string|null, toast: string}}
 */
export function draftActionFor(paperId, draftId) {
  if (draftId != null && paperId === draftId) {
    return { label: 'Unset draft', next: null, toast: 'Draft cleared' };
  }
  return { label: 'Set as draft', next: paperId, toast: 'Draft updated' };
}

// Strength sort order: strong=0, moderate=1, weak=2, null/unscored=3
const STRENGTH_ORDER = { strong: 0, moderate: 1, weak: 2 };

// Status sort order: processing=0, queued=1, ingested=2, failed=3
const STATUS_ORDER = { processing: 0, queued: 1, ingested: 2, failed: 3 };

/**
 * Stable-sort rows by column and direction, keeping the draft row pinned at top.
 *
 * @param {Array}  rows  — row objects from buildRows
 * @param {string} col   — 'title'|'year'|'status'|'strength'|'relation'|'added'
 * @param {'asc'|'desc'} dir
 * @returns {Array}  new array
 */
export function sortRows(rows, col, dir) {
  // Separate draft from the rest
  const draft    = rows.filter(r => r.isDraft);
  const nonDraft = rows.filter(r => !r.isDraft);

  // Tag with original index for stability
  const tagged = nonDraft.map((r, i) => ({ r, i }));

  tagged.sort((a, b) => {
    let cmp = 0;

    if (col === 'title') {
      cmp = (a.r.title || '').localeCompare(b.r.title || '');
    } else if (col === 'year') {
      const ay = a.r.year ?? 0;
      const by = b.r.year ?? 0;
      cmp = ay - by;
    } else if (col === 'status') {
      const ao = STATUS_ORDER[a.r.status]   ?? 99;
      const bo = STATUS_ORDER[b.r.status]   ?? 99;
      cmp = ao - bo;
    } else if (col === 'strength') {
      const ao = STRENGTH_ORDER[a.r.strengthBand] ?? 3;
      const bo = STRENGTH_ORDER[b.r.strengthBand] ?? 3;
      cmp = ao - bo;
    } else if (col === 'relation') {
      cmp = (a.r.relation || '').localeCompare(b.r.relation || '');
    } else if (col === 'added') {
      const at = a.r.addedAt || '';
      const bt = b.r.addedAt || '';
      cmp = at < bt ? -1 : at > bt ? 1 : 0;
    }

    if (dir === 'desc') cmp = -cmp;

    // Stable: fall back to original index when equal
    return cmp !== 0 ? cmp : a.i - b.i;
  });

  return [...draft, ...tagged.map(t => t.r)];
}
