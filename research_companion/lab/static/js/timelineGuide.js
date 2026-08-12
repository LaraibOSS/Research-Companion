/**
 * timelineGuide.js — on-page orientation for the Timeline view.
 *
 * The Timeline had a legend for the gap diamonds but nothing explaining the
 * grid itself: what a row is, what a column is, what a dot means, or what a
 * reader is supposed to take away. Without that, the page reads as decoration.
 *
 * Pure and dependency-free (no DOM, no store) so it is node-testable. Returns
 * RAW strings; the caller escapes at the interpolation site.
 */

/** One line explaining the grid, in reading order: row, column, dot, meaning. */
export const TIMELINE_HOWTO =
  'Each row is one concept, method or dataset from your papers. Each column is a '
  + 'publication year. A dot means that idea appears in a paper you have from that '
  + 'year — so a long row is an idea the field kept using, a row starting recently '
  + 'is an emerging one, and an empty stretch is a period your library does not cover.';

/** Colour key labels, paired with the kinds the view already colours. */
export const TIMELINE_KINDS = [
  { kind: 'concept', label: 'Concept' },
  { kind: 'method', label: 'Method' },
  { kind: 'dataset', label: 'Dataset' },
];

/**
 * Papers that cannot be placed on the timeline because they have no year.
 * Silently dropping them makes the page look broken ("where are my papers?"),
 * so the view states the count and how to fix it.
 *
 * Takes the count the server already computes
 * (`skipped_papers_without_year`) rather than recounting client-side, so the
 * number can never disagree with what the timeline actually plotted.
 *
 * @param {number} count
 * @returns {{count: number, note: string}} — note is '' when nothing is
 *   hidden. Never throws.
 */
export function hiddenPapersNote(count) {
  const n = Math.max(0, Number(count) || 0);
  if (n === 0) return { count: 0, note: '' };
  return {
    count: n,
    note: `${n} paper${n === 1 ? '' : 's'} cannot be placed here — `
      + `${n === 1 ? 'it has' : 'they have'} no publication year. `
      + `Add the year from the Library to see ${n === 1 ? 'it' : 'them'}.`,
  };
}
