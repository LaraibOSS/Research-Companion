/**
 * citationsHelpers.js — Pure, DOM-free helpers for the Citation Coverage UI (W5-C3).
 *
 * All functions are stateless and have no DOM dependencies
 * so they can be tested with node --test.
 */

// ---------------------------------------------------------------------------
// Status ordering for groupByStatus
// ---------------------------------------------------------------------------

const STATUS_ORDER = ['available', 'unchecked', 'unresolved', 'in_library'];

// ---------------------------------------------------------------------------
// Exported helpers
// ---------------------------------------------------------------------------

/**
 * Extract the counts object from a coverage response, zeroing any missing fields.
 * Safe on null/undefined input.
 *
 * `usable` (in_library minus ingest-failed) falls back to `in_library` when the
 * backend payload predates the field, so stale/cached payloads don't regress.
 *
 * @param {object|null|undefined} coverage
 * @returns {{ total, in_library, available, unchecked, unresolved, usable }}
 */
export function coverageCounts(coverage) {
  const raw = coverage && coverage.counts ? coverage.counts : {};
  const in_library = raw.in_library || 0;
  return {
    total:      raw.total      || 0,
    in_library,
    available:  raw.available  || 0,
    unchecked:  raw.unchecked  || 0,
    unresolved: raw.unresolved || 0,
    usable: raw.usable !== undefined ? raw.usable : in_library,
  };
}

/**
 * Total number of cited papers that are not yet in the library.
 *
 * @param {{ total: number, in_library: number }} counts
 * @returns {number}
 */
export function missingCount(counts) {
  return (counts.total || 0) - (counts.in_library || 0);
}

/**
 * The coverage payload's source, defaulting to 'none'.
 * 'bibliography' = parsed from the draft's reference list; 'related_work' =
 * fell back to the LLM's related-work mentions (bibliography not detected).
 *
 * @param {object|null|undefined} coverage
 * @returns {string}
 */
export function coverageSource(coverage) {
  return (coverage && coverage.source) || 'none';
}

/**
 * Generate the human-readable banner summary text.
 *
 * When the coverage did NOT come from a parsed bibliography (source is
 * 'related_work' or 'none'), the count is the LLM's related-work mentions, not
 * the reference list — so it must not be labelled "cited papers".
 *
 * Uses `counts.usable` (in_library minus ingest-failed) as the analysis-ready
 * count, falling back to `counts.in_library` when `usable` is undefined
 * (backward compat with stale payloads). When some in-library papers are
 * unusable (ingest failed), appends a clarifying suffix so the banner doesn't
 * overclaim coverage.
 *
 * @param {{ total: number, in_library: number, usable?: number }} counts
 * @param {string} [source] — coverage source ('bibliography' | 'related_work' | 'none')
 * @returns {string}
 */
export function bannerText(counts, source) {
  if (source && source !== 'bibliography') {
    return `Based on ${counts.total} related-work mentions (full bibliography not detected)`;
  }
  const inLibrary = counts.in_library || 0;
  const usable = counts.usable !== undefined ? counts.usable : inLibrary;
  const unreadable = inLibrary - usable;
  const suffix = unreadable > 0 ? ` (${unreadable} in library but unreadable)` : '';
  // "cited references" (not "papers") so this reads as draft-bibliography
  // coverage, distinct from the Library's paper total.
  return `Analysis covers ${usable} of ${counts.total} cited references${suffix}`;
}

/**
 * Map a reference entry's status to a display chip.
 * If entry.downloading is true, shows a "Downloading…" loading chip.
 * If status is 'in_library' but entry.ingest_failed is true, the matched
 * paper exists but its ingest failed — it's unusable for analysis, so the
 * chip must say so (warn-styled, not the green "in library" ok chip).
 *
 * @param {{ status: string, downloading?: boolean, ingest_failed?: boolean }} entry
 * @returns {{ label: string, cls: string }}
 */
export function statusChip(entry) {
  if (entry.downloading) return { label: 'Downloading…', cls: 'chip-loading' };
  switch (entry.status) {
    case 'in_library':
      return entry.ingest_failed
        ? { label: 'In library — ingest failed', cls: 'chip-warn' }
        : { label: 'In library ✓', cls: 'chip-ok' };
    // 'available' status means a fetchable match was found but is NOT yet in
    // the library — "Missing" avoids reading as a second Add button next to
    // the row's real Add action.
    case 'available':  return { label: 'Missing',          cls: 'chip-add' };
    case 'unchecked':  return { label: 'Not checked',      cls: 'chip-muted' };
    case 'unresolved': return { label: 'Unresolved ?',     cls: 'chip-warn' };
    default:           return { label: entry.status || '', cls: 'chip-muted' };
  }
}

/**
 * Return the subset of references that are available AND have an add_target.
 * These are the rows that can be added in the "Add all" bulk action.
 *
 * @param {object|null} coverage
 * @returns {Array}
 */
export function availableEntries(coverage) {
  if (!coverage) return [];
  const refs = Array.isArray(coverage.references) ? coverage.references : [];
  return refs.filter(r => r.status === 'available' && r.add_target);
}

/**
 * Return a flat array of references ordered by group:
 *   available, unchecked, unresolved, in_library
 * Within each group, entries appear in their original bibliography index order.
 *
 * @param {Array|null} references
 * @returns {Array}
 */
export function groupByStatus(references) {
  if (!Array.isArray(references) || references.length === 0) return [];

  const groups = {};
  for (const status of STATUS_ORDER) groups[status] = [];
  const other = [];

  for (const ref of references) {
    if (STATUS_ORDER.includes(ref.status)) {
      groups[ref.status].push(ref);
    } else {
      other.push(ref);
    }
  }

  const result = [];
  for (const status of STATUS_ORDER) {
    result.push(...groups[status]);
  }
  result.push(...other);
  return result;
}

/**
 * Build the option list for the citations panel "Link…" picker: every library
 * paper the user could link a cited reference to.
 *
 * @param {Array|Map|null} papers  — store paper objects (array or the papers Map)
 * @param {string|null} draftId    — the current draft paper_id (excluded)
 * @param {Set<string>|Array<string>|null} [matchedPaperIds] — paper_ids already
 *   `matched_paper_id` of some OTHER in_library reference in the current
 *   coverage (see matchedPaperIdSet). Omit/null for the old, unannotated
 *   behavior — matched papers are still selectable (a draft can legitimately
 *   cite the same work twice), just flagged and demoted so linking a paper
 *   that's already matched elsewhere is a visible choice, not an accident.
 * @returns {Array<{ paperId: string, label: string }>}
 *   Order: unmatched papers first (needs-metadata sub-group before complete,
 *   each A–Z by title), then matched papers last (same needs-metadata/title
 *   sub-order). label = "<title> (<year or —>)", with a
 *   " (already matched to another reference)" suffix for matched papers.
 */
export function linkTargetOptions(papers, draftId, matchedPaperIds = null) {
  const list = papers instanceof Map
    ? [...papers.values()]
    : (Array.isArray(papers) ? papers : []);
  if (list.length === 0) return [];

  const matchedSet = matchedPaperIds instanceof Set
    ? matchedPaperIds
    : new Set(Array.isArray(matchedPaperIds) ? matchedPaperIds : []);

  const decorated = list
    .filter(p => p && p.paper_id && p.paper_id !== draftId)
    .map(p => {
      const hasYear = p.year !== null && p.year !== undefined && p.year !== '';
      const hasAuthors = Array.isArray(p.authors) && p.authors.length > 0;
      const title = p.title || '';
      const matched = matchedSet.has(p.paper_id);
      const baseLabel = `${title} (${hasYear ? p.year : '—'})`;
      return {
        paperId: p.paper_id,
        label: matched ? `${baseLabel} (already matched to another reference)` : baseLabel,
        needsMeta: !hasYear || !hasAuthors,
        matched,
        title,
      };
    });

  decorated.sort((a, b) => {
    if (a.matched !== b.matched) return a.matched ? 1 : -1;
    if (a.needsMeta !== b.needsMeta) return a.needsMeta ? -1 : 1;
    return a.title.localeCompare(b.title);
  });

  return decorated.map(({ paperId, label }) => ({ paperId, label }));
}

/**
 * The set of paper_ids that are already `matched_paper_id` of an in_library
 * reference in *references*, excluding the reference at *excludeIndex* (the
 * row currently being linked — its own existing match, if any, doesn't count
 * as "another reference").
 *
 * @param {Array|null} references — coverage.references
 * @param {number|null} [excludeIndex]
 * @returns {Set<string>}
 */
export function matchedPaperIdSet(references, excludeIndex = null) {
  const set = new Set();
  if (!Array.isArray(references)) return set;
  for (const ref of references) {
    if (!ref || ref.status !== 'in_library' || !ref.matched_paper_id) continue;
    if (excludeIndex != null && ref.index === excludeIndex) continue;
    set.add(ref.matched_paper_id);
  }
  return set;
}

/**
 * Build the option list for the library-drawer reverse picker ("This is a cited
 * reference…"): every cited reference the user could still link this paper to —
 * i.e. any reference NOT already resolved to a library paper.
 *
 * Titles & years here come from the DRAFT's citations, not the papers
 * themselves, so labels use the draft-side title/raw + year only.
 *
 * @param {object|null} coverage — GET /api/draft/citations payload (or null)
 * @returns {Array<{ index: number, label: string }>}
 *   label = "<title|raw truncated ~70> (<year>)" — the " (year)" suffix is
 *   appended only when a year is present. Preserves entry.index (the coverage
 *   index the link endpoint expects). Returns [] for null/empty/no-references.
 */
export function unlinkedCitationOptions(coverage) {
  const refs = coverage && Array.isArray(coverage.references) ? coverage.references : [];
  const out = [];
  for (const entry of refs) {
    if (!entry || entry.status === 'in_library') continue;
    const base = entry.title || entry.raw || '';
    const text = base.length > 70 ? base.slice(0, 69) + '…' : base;
    const hasYear = entry.year !== null && entry.year !== undefined && entry.year !== '';
    out.push({
      index: entry.index,
      label: hasYear ? `${text} (${entry.year})` : text,
    });
  }
  return out;
}
