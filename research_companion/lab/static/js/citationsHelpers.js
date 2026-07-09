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
 * @param {object|null|undefined} coverage
 * @returns {{ total, in_library, available, unchecked, unresolved }}
 */
export function coverageCounts(coverage) {
  const raw = coverage && coverage.counts ? coverage.counts : {};
  return {
    total:      raw.total      || 0,
    in_library: raw.in_library || 0,
    available:  raw.available  || 0,
    unchecked:  raw.unchecked  || 0,
    unresolved: raw.unresolved || 0,
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
 * Generate the human-readable banner summary text.
 *
 * @param {{ total: number, in_library: number }} counts
 * @returns {string}
 */
export function bannerText(counts) {
  return `Analysis covers ${counts.in_library} of ${counts.total} cited papers`;
}

/**
 * Map a reference entry's status to a display chip.
 * If entry.downloading is true, shows a "Downloading…" loading chip.
 *
 * @param {{ status: string, downloading?: boolean }} entry
 * @returns {{ label: string, cls: string }}
 */
export function statusChip(entry) {
  if (entry.downloading) return { label: 'Downloading…', cls: 'chip-loading' };
  switch (entry.status) {
    case 'in_library': return { label: 'In library ✓', cls: 'chip-ok' };
    case 'available':  return { label: 'Add ↓',       cls: 'chip-add' };
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
 * @returns {Array<{ paperId: string, label: string }>}
 *   Papers still missing metadata (year == null OR no authors) come first,
 *   then complete papers; both groups sorted by title A–Z.
 *   label = "<title> (<year or —>)".
 */
export function linkTargetOptions(papers, draftId) {
  const list = papers instanceof Map
    ? [...papers.values()]
    : (Array.isArray(papers) ? papers : []);
  if (list.length === 0) return [];

  const decorated = list
    .filter(p => p && p.paper_id && p.paper_id !== draftId)
    .map(p => {
      const hasYear = p.year !== null && p.year !== undefined && p.year !== '';
      const hasAuthors = Array.isArray(p.authors) && p.authors.length > 0;
      const title = p.title || '';
      return {
        paperId: p.paper_id,
        label: `${title} (${hasYear ? p.year : '—'})`,
        needsMeta: !hasYear || !hasAuthors,
        title,
      };
    });

  decorated.sort((a, b) => {
    if (a.needsMeta !== b.needsMeta) return a.needsMeta ? -1 : 1;
    return a.title.localeCompare(b.title);
  });

  return decorated.map(({ paperId, label }) => ({ paperId, label }));
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
