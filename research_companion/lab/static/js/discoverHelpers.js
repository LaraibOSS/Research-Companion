/**
 * discoverHelpers.js — Pure, DOM-free helpers for the Brainstorm view's
 * discovery surface (GET /api/discover). Mirrors the shape convention of
 * gapHelpers.js / workspaceHelpers.js.
 *
 * Testable with node --test (tests/js/discoverHelpers.test.mjs).
 */
import { escapeHtml } from './format.js';

const _SOURCE_LABELS = {
  search: 'Semantic Scholar',
  openalex: 'OpenAlex',
  reference: 'Reference',
  citation: 'Citation',
};

function _sourceLabel(source) {
  if (!source || typeof source !== 'string') return 'Unknown source';
  if (_SOURCE_LABELS[source]) return _SOURCE_LABELS[source];
  return source.charAt(0).toUpperCase() + source.slice(1);
}

/** Namespaced "prefix:id" identifiers present on a raw result/row. */
function _identifiers(r) {
  const ids = [];
  if (r.doi) ids.push(`doi:${r.doi}`);
  if (r.arxiv_id) ids.push(`arxiv:${r.arxiv_id}`);
  if (r.s2_id) ids.push(`s2:${r.s2_id}`);
  if (r.pmid) ids.push(`pmid:${r.pmid}`);
  if (r.pmcid) ids.push(`pmcid:${r.pmcid}`);
  return ids;
}

/**
 * The bare identifier POST /api/papers's `target` expects, using the same
 * pmid > arXiv > DOI > S2 > URL precedence as DiscoveredPaper.add_cmd
 * (research_companion/discover.py). Unescaped — the caller must escapeHtml
 * this before writing it into a DOM attribute.
 */
function _addTarget(r) {
  if (r.pmid) return `pmid:${r.pmid}`;
  if (r.arxiv_id) return String(r.arxiv_id);
  if (r.doi) return String(r.doi);
  if (r.s2_id) return String(r.s2_id);
  return typeof r.url === 'string' ? r.url : '';
}

const _ABSTRACT_MAX = 240;

function _shortAbstract(abstract) {
  const a = typeof abstract === 'string' ? abstract : '';
  if (a.length <= _ABSTRACT_MAX) return escapeHtml(a);
  return escapeHtml(a.slice(0, _ABSTRACT_MAX).trim()) + '…';
}

/**
 * Map one raw GET /api/discover result item to a display model for the
 * Brainstorm view. Never throws; every field defaults safely for a partial
 * or malformed item.
 *
 * @param {object} raw — one item from GET /api/discover `results[]`:
 *   {title, authors, year, citation_count, arxiv_id, doi, s2_id, url,
 *    abstract, source, pmid, pmcid, add_cmd, in_library}
 * @param {Set<string>|null|undefined} [libraryIds] — optional extra set of
 *   "prefix:id" identifiers (e.g. "arxiv:1234.5678") the caller already
 *   knows are in the library (used right after an Add, before the next
 *   full refetch) — ORed with raw.in_library.
 * @returns {{title:string, authorsText:string, year:(number|null),
 *   citationCount:number, source:string, sourceLabel:string,
 *   venue:string, topVenue:string, isTopVenue:boolean,
 *   abstractShort:string, inLibrary:boolean, addTarget:string, url:string,
 *   arxivId:(string|null), doi:(string|null), s2Id:(string|null),
 *   pmid:(string|null), pmcid:(string|null)}}
 *
 * ESCAPING CONTRACT: `title`, `authorsText`, `sourceLabel`, and `abstractShort`
 * are ALREADY HTML-escaped — interpolate them directly, do NOT re-escape (that
 * would double-escape). `addTarget`, `url`, `source`, and the raw ids are NOT
 * escaped — the caller must escapeHtml them before writing into the DOM.
 */
export function discoverResultModel(raw, libraryIds) {
  const r = (raw && typeof raw === 'object') ? raw : {};
  const authors = Array.isArray(r.authors) ? r.authors.filter(a => typeof a === 'string' && a) : [];
  const title = (typeof r.title === 'string' && r.title) ? r.title : 'Untitled';

  const ids = _identifiers(r);
  const libSet = (libraryIds && typeof libraryIds.has === 'function') ? libraryIds : null;
  const inLibrary = r.in_library === true || (libSet ? ids.some(id => libSet.has(id)) : false);

  return {
    title: escapeHtml(title),
    authorsText: escapeHtml(authors.length ? authors.join(', ') : 'Unknown authors'),
    year: typeof r.year === 'number' ? r.year : null,
    citationCount: typeof r.citation_count === 'number' ? r.citation_count : 0,
    source: typeof r.source === 'string' ? r.source : '',
    sourceLabel: escapeHtml(_sourceLabel(r.source)),
    // Venue as reported by the source, plus whether it matched the curated
    // venue KB server-side. Pre-escaped, like the other display fields.
    venue: escapeHtml(String(r.venue || '')),
    topVenue: escapeHtml(String(r.top_venue || '')),
    isTopVenue: !!r.is_top_venue,
    abstractShort: _shortAbstract(r.abstract),
    inLibrary: Boolean(inLibrary),
    addTarget: _addTarget(r),
    url: typeof r.url === 'string' ? r.url : '',
    arxivId: r.arxiv_id || null,
    doi: r.doi || null,
    s2Id: r.s2_id || null,
    pmid: r.pmid || null,
    pmcid: r.pmcid || null,
  };
}

/**
 * Merge discovery results across multiple expanded queries (a second,
 * defensive dedup pass over the raw results[] from GET /api/discover — the
 * backend already dedups, but this keeps the view correct against an
 * older server too). Dedups by identity (doi/arxiv_id/s2_id/pmid/pmcid),
 * falling back to a lowercased-title token. When two results share an
 * identity, keeps whichever has the higher citation_count. Never throws;
 * non-array input -> []. Order-preserving over first occurrence.
 *
 * @param {Array|null|undefined} list — raw result objects (snake_case)
 * @returns {Array}
 */
export function dedupeDiscoverResults(list) {
  const arr = Array.isArray(list) ? list : [];
  const idToToken = new Map();
  const chosen = new Map();
  const order = [];

  for (const raw of arr) {
    if (!raw || typeof raw !== 'object') continue;
    const ids = _identifiers(raw);
    let token = null;
    for (const id of ids) {
      if (idToToken.has(id)) { token = idToToken.get(id); break; }
    }
    if (token === null) {
      token = ids[0] || `title:${String(raw.title || '').toLowerCase().trim()}`;
    }
    for (const id of ids) idToToken.set(id, token);

    if (!chosen.has(token)) {
      chosen.set(token, raw);
      order.push(token);
    } else {
      const existing = chosen.get(token);
      const existingCount = typeof existing.citation_count === 'number' ? existing.citation_count : 0;
      const newCount = typeof raw.citation_count === 'number' ? raw.citation_count : 0;
      if (newCount > existingCount) chosen.set(token, raw);
    }
  }

  return order.map(t => chosen.get(t));
}

// Column accessors for sortDiscoverResults. Each returns a comparable value
// or null/undefined when the row model lacks that field. 'relevance' has no
// accessor: the incoming array order already IS the relevance order the
// search API returned, so it is deliberately a no-reorder no-op.
const _SORT_ACCESSORS = {
  citations: r => (r && typeof r.citationCount === 'number') ? r.citationCount : null,
  year: r => (r && r.year != null) ? r.year : null,
};

/**
 * Sort discoverResultModel rows by a column, nulls always last. Stable
 * (ties and null-groups keep their original relative order) and never
 * mutates the input; returns a new array. `'relevance'` (or any column not
 * in _SORT_ACCESSORS) returns a shallow copy with no reordering.
 *
 * @param {Array|null|undefined} rows — row models from discoverResultModel
 * @param {'citations'|'year'|'relevance'} col
 * @param {'asc'|'desc'} [dir='desc']
 * @returns {Array}
 */
export function sortDiscoverResults(rows, col, dir = 'desc') {
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
