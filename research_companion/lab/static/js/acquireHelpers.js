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

/**
 * Papers still genuinely needing a person's help, EXCLUDING any whose
 * paper_id is in `matchedPaperIds` — a caught file the watcher already
 * matched this session (GET /api/acquire/status's `matched`), even before
 * the eventual 'papers' SSE refresh lands and the stored acquisition
 * itself catches up. Membership is still `queueRowModel(p).show` (the
 * backend flag) first; `matchedPaperIds` only narrows it further, it never
 * widens it.
 *
 * @param {Array|null|undefined} papers
 * @param {Set<string>|string[]|null|undefined} matchedPaperIds
 * @returns {Array}
 */
export function queueAfterMatches(papers, matchedPaperIds) {
  const matched = matchedPaperIds instanceof Set
    ? matchedPaperIds
    : new Set(Array.isArray(matchedPaperIds) ? matchedPaperIds : []);
  const list = Array.isArray(papers) ? papers : [];
  return list.filter(p => queueRowModel(p).show && !matched.has(p && p.paper_id));
}

/**
 * Format a countdown in m:ss for the arming window. Never negative, never
 * throws on a bad input.
 *
 * @param {number} secondsLeft
 * @returns {string} e.g. "9:59", "0:07"
 */
export function formatCountdown(secondsLeft) {
  const total = Math.max(0, Math.floor(Number(secondsLeft) || 0));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}

/**
 * Turn one GET /api/acquire/status response into what the Library should
 * show. `matched`/`unmatched`/`unreadable` are each reported by the server
 * exactly once per caught file (research_companion/watcher.py's
 * ArmedWatcher never re-offers a claimed path — see poll()/release()), so
 * every message produced here is new; the caller does not need to dedupe
 * against a previous poll.
 *
 * @param {object|null|undefined} status — raw GET /api/acquire/status body:
 *   { armed, seconds_left, paper_ids, matched, unmatched, unreadable }
 * @returns {{ armed: boolean, countdownText: string,
 *   matchedPaperIds: string[],
 *   messages: Array<{ type: 'success'|'warning', text: string }> }}
 */
export function statusBannerModel(status) {
  const s = status && typeof status === 'object' ? status : {};
  const armed = s.armed === true;
  const matched = Array.isArray(s.matched) ? s.matched : [];
  const unmatched = Array.isArray(s.unmatched) ? s.unmatched : [];
  const unreadable = Array.isArray(s.unreadable) ? s.unreadable : [];

  const matchedPaperIds = matched
    .map(m => (m && typeof m === 'object' ? m.paper_id : null))
    .filter(Boolean);

  const messages = [
    ...matched.map(m => ({
      type: 'success',
      text: `Caught "${(m && m.filename) || 'a file'}" — matched to `
        + `${(m && m.paper_id) || 'a paper'}, re-ingesting…`,
    })),
    ...unmatched.map(filename => ({
      type: 'warning',
      text: `Downloaded "${filename}" didn't match any paper you're watching for — wrong file?`,
    })),
    ...unreadable.map(u => ({
      type: 'warning',
      text: `Couldn't read "${(u && u.filename) || 'a file'}" yet`
        + `${u && u.error ? ` (${u.error})` : ''} — will try again`,
    })),
  ];

  return {
    armed,
    countdownText: formatCountdown(s.seconds_left),
    matchedPaperIds,
    messages,
  };
}
