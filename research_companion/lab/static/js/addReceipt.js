/**
 * addReceipt.js — pure model for the "what just happened when I clicked Add"
 * receipt shown in Brainstorm.
 *
 * Adding papers is asynchronous and silent: a toast fires and the papers land
 * in a library the user may not be looking at. This builds an explicit receipt
 * — how many were queued, how many were already there, where they went, and
 * what to do about the ones that fail to download — so nothing about the
 * outcome has to be inferred.
 *
 * Dependency-free (no DOM, no store) and node-testable. Returns RAW strings;
 * the caller escapes at the interpolation site.
 */

/** Shown on every add: downloads are best-effort and can legitimately fail. */
export const MANUAL_ADD_DISCLAIMER =
  'We try to download each paper\'s PDF automatically, but some publishers block '
  + 'it. Any paper that fails shows as "failed" in your Library — download that '
  + 'PDF yourself and add it manually, and it works exactly like the others.';

/**
 * Build the receipt for an add action.
 * @param {{queued: number, skipped: number, failed: number, researchName: string}} r
 * @returns {{title: string, detail: string, disclaimer: string, hasContent: boolean}}
 *   Never throws.
 */
export function addReceiptModel(r) {
  const o = (r && typeof r === 'object') ? r : {};
  const queued = Math.max(0, Number(o.queued) || 0);
  const skipped = Math.max(0, Number(o.skipped) || 0);
  const failed = Math.max(0, Number(o.failed) || 0);
  const research = String(o.researchName || '').trim();

  let title;
  if (queued > 0) {
    title = `Adding ${queued} paper${queued === 1 ? '' : 's'}`
      + (research ? ` to “${research}”` : '');
  } else if (skipped > 0) {
    title = `Nothing to add`;
  } else {
    title = 'No papers selected';
  }

  const bits = [];
  if (queued > 0) {
    bits.push('They are downloading and being analyzed in the background — '
      + 'you can keep working, and track them in the Library.');
  }
  if (skipped > 0) {
    bits.push(`${skipped} ${skipped === 1 ? 'was' : 'were'} already in this research, `
      + `so ${skipped === 1 ? 'it was' : 'they were'} skipped.`);
  }
  if (failed > 0) {
    bits.push(`${failed} could not be added.`);
  }

  return {
    title,
    detail: bits.join(' '),
    disclaimer: MANUAL_ADD_DISCLAIMER,
    hasContent: queued > 0 || skipped > 0 || failed > 0,
  };
}
