/**
 * acquireHelpers.js — display model for a paper waiting on the user.
 *
 * THE RULE THIS MODULE FOLLOWS (same as signalHelpers.js): it does not decide
 * who can help. `human_can_help` is computed in Python
 * (Acquisition.human_can_help, research_companion/acquire/types.py) and
 * consumed here. A second implementation would drift, and the drift would be
 * silent.
 *
 * Pure and DOM-free. Returns RAW strings; the caller escapes at the
 * interpolation site.
 */

export function queueRowModel(paper) {
  const blank = { show: false, headline: '', detail: '', canOpen: false, openUrl: '' };
  const acq = paper && typeof paper === 'object' ? paper.acquisition : null;
  if (!acq || typeof acq !== 'object') return blank;
  if (acq.human_can_help !== true) return blank;

  const attempts = Array.isArray(acq.attempts) ? acq.attempts : [];
  const openUrl = (attempts.find(a => a && a.url) || {}).url || '';
  return {
    show: true,
    headline: String(acq.headline || ''),
    detail: String(acq.detail || ''),
    canOpen: Boolean(openUrl),
    openUrl,
  };
}

export function needsYouCount(papers) {
  if (!Array.isArray(papers)) return 0;
  return papers.filter(p => queueRowModel(p).show).length;
}
