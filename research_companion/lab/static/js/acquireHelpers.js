/**
 * acquireHelpers.js — display model for a paper waiting on the user, plus
 * the DOM-free poll loop that drives GET /api/acquire/status while armed.
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

import { pollDecision, HTTP_URL_RE } from './oaLinkHelpers.js';

// Host-class rank, lowest first — the SAME order Python ranks candidates in
// (research_companion/acquire/hosts.py's _ORDER). An unrecognised class
// sorts last rather than throwing.
const HOST_CLASS_ORDER = ['native', 'repository', 'preprint', 'publisher'];

// The DOI resolver is §7.2's FALLBACK, not a candidate: for a DOI paper it
// is always attempt 0 (acquire() tries it before asking any index), so
// taking attempts[0] sent the user to doi.org every time instead of to the
// copy an index actually found — the dl.acm.org URL that 403'd the robot
// and opens fine for a person.
const DOI_RESOLVER_RE = /^https?:\/\/(?:dx\.)?doi\.org\//i;

/**
 * §7.2's "the highest-ranked candidate from Acquisition.attempts that a
 * browser can use", then the DOI resolver, else ''.
 *
 * Every URL is validated against HTTP_URL_RE — the same guard oaLinksLine
 * applies before rendering an anchor — because this one is handed to
 * window.open, where a javascript:/data: URL from a malformed or hostile
 * index response would execute rather than merely render.
 *
 * @param {Array|null|undefined} attempts — acquisition.attempts
 * @returns {string}
 */
export function browserOpenUrl(attempts) {
  const usable = [];
  for (const a of Array.isArray(attempts) ? attempts : []) {
    if (!a || typeof a !== 'object') continue;
    const url = a.url;
    if (typeof url !== 'string' || !HTTP_URL_RE.test(url)) continue;
    const rank = HOST_CLASS_ORDER.indexOf(String(a.host_class || ''));
    usable.push({
      url,
      rank: rank === -1 ? HOST_CLASS_ORDER.length : rank,
      resolver: DOI_RESOLVER_RE.test(url) ? 1 : 0,
    });
  }
  // Array.prototype.sort is stable (ES2019), so two candidates of the same
  // class keep the order acquire() tried them in.
  usable.sort((a, b) => (a.resolver - b.resolver) || (a.rank - b.rank));
  return usable.length > 0 ? usable[0].url : '';
}

export function queueRowModel(paper) {
  const blank = { show: false, headline: '', detail: '', canOpen: false, openUrl: '' };
  const acq = paper && typeof paper === 'object' ? paper.acquisition : null;
  if (!acq || typeof acq !== 'object') return blank;
  if (acq.human_can_help !== true) return blank;

  const openUrl = browserOpenUrl(acq.attempts);
  return {
    show: true,
    headline: String(acq.headline || ''),
    detail: String(acq.detail || ''),
    canOpen: Boolean(openUrl),
    openUrl,
  };
}

/**
 * Papers still genuinely needing a person's help, EXCLUDING any whose
 * paper_id is in `matchedPaperIds` — a caught file the watcher already
 * matched this session (GET /api/acquire/status's `matched`), even before
 * the eventual 'papers' SSE refresh lands and the stored acquisition
 * itself catches up. Membership is still `queueRowModel(p).show` (the
 * backend flag) first; `matchedPaperIds` only narrows it further, it never
 * widens it. This is the only place the chip count / filter should read
 * queue membership from — nothing else re-derives it.
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
 * Bound how long a paper_id may stay in the caller's "just matched, hide it
 * optimistically" set. Two rules, either one enough on its own to prevent a
 * paper staying invisibly missing from the queue forever:
 *
 *   1. Once the arming window is over (`model.armed` false -- expired, given
 *      up, or disarmed) EVERY id is forgotten unconditionally. A paper can
 *      therefore never be hidden longer than the current arming window,
 *      which the user can see counting down -- not "until the next reload".
 *   2. While still armed, an id is dropped as soon as `isStillQueued(id)`
 *      says that paper is no longer a queue member at all -- the ordinary,
 *      expected case where the re-ingest succeeded and the eventual
 *      'papers' refresh caught up.
 *
 * Deliberately does NOT try to distinguish "still mid-re-ingest" from "the
 * re-ingest failed and re-armed the SAME paper for a genuinely new reason"
 * while still armed -- both look identical from here (`isStillQueued` true
 * either way). Rule 1 is what bounds that ambiguity: at worst, the paper
 * reappears once the window ends rather than staying hidden indefinitely.
 * A paper briefly reappearing while its re-ingest finishes is the safer
 * failure than one silently vanishing with no expiry at all.
 *
 * @param {Set<string>|string[]|null|undefined} currentMatchedIds
 * @param {{armed: boolean}|null|undefined} model — latest statusBannerModel result
 * @param {(paperId: string) => boolean} isStillQueued — queueRowModel(paper).show
 *   for the CURRENT store state of that paper_id. The caller looks this up
 *   (this function never reads any store) — so this stays DOM/store-free.
 * @returns {Set<string>}
 */
export function nextMatchedIds(currentMatchedIds, model, isStillQueued) {
  if (!model || model.armed !== true) return new Set();
  const ids = currentMatchedIds instanceof Set
    ? currentMatchedIds
    : new Set(Array.isArray(currentMatchedIds) ? currentMatchedIds : []);
  const check = typeof isStillQueued === 'function' ? isStillQueued : () => true;
  const next = new Set();
  for (const id of ids) {
    let keep = true;
    try { keep = check(id) !== false; } catch { keep = true; }
    if (keep) next.add(id);
  }
  return next;
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

// ---------------------------------------------------------------------------
// The poll loop itself (Task 10D fix round 1)
//
// This is deliberately NOT wrapped in a class or anything view-specific: it
// is a plain factory over injectable `fetchStatus`/`schedule`/`cancel`, so a
// node test can drive it with a fake timer and a fake fetch — no DOM, no
// real setTimeout, no real network. The default `schedule`/`cancel` are the
// real timer functions, so production code gets real polling for free.
// ---------------------------------------------------------------------------

/**
 * Build a poller that repeatedly calls `fetchStatus()` on `intervalMs`,
 * stopping itself when the status comes back disarmed, or when repeated
 * fetch failures cross pollDecision's bounded give-up threshold (the SAME
 * continue/retry/give-up state machine _watchFindPdfJob uses for find-pdf
 * polling, in oaLinkHelpers.js) — so a request that never resolves, or a
 * server that never answers, cannot leave this looping forever.
 *
 * @param {object} opts
 * @param {() => Promise<object>} opts.fetchStatus — normally api.getAcquireStatus
 * @param {(model: {armed:boolean, countdownText:string,
 *   matchedPaperIds:string[], messages:Array}) => void} [opts.onUpdate] —
 *   called with statusBannerModel(status) after every SUCCESSFUL fetch,
 *   including the final one that reports armed:false.
 * @param {() => void} [opts.onGiveUp] — called once, when polling stops due
 *   to repeated fetch failures (pollDecision's 'stop-404'/'give-up') rather
 *   than a normal disarm/expiry.
 * @param {number} [opts.intervalMs=5000]
 * @param {(fn: () => void, ms: number) => any} [opts.schedule] — defaults to
 *   the real setTimeout; a test passes a fake that records the call instead
 *   of actually waiting.
 * @param {(id: any) => void} [opts.cancel] — defaults to the real
 *   clearTimeout; pairs with `schedule`.
 * @returns {{ start: () => Promise<void>, stop: () => void,
 *   isPolling: () => boolean }}
 */
export function createAcquirePoller(opts) {
  const {
    fetchStatus,
    onUpdate,
    onGiveUp,
    intervalMs = 5000,
    schedule = (fn, ms) => setTimeout(fn, ms),
    cancel = (id) => clearTimeout(id),
  } = opts || {};

  let polling = false;
  let timerId = null;
  let consecutiveFailures = 0;
  let elapsedPolls = 0;

  function _clearTimer() {
    if (timerId != null) {
      cancel(timerId);
      timerId = null;
    }
  }

  async function _tick() {
    if (!polling) return;
    elapsedPolls += 1;

    let status = null;
    let err = null;
    try {
      status = await fetchStatus();
    } catch (e) {
      err = e;
    }

    if (!polling) return; // stopped while the fetch was in flight

    if (!err) {
      consecutiveFailures = 0;
      const model = statusBannerModel(status);
      if (onUpdate) onUpdate(model);
      if (!model.armed) {
        stop();
        return;
      }
      if (polling) timerId = schedule(_tick, intervalMs);
      return;
    }

    const decision = pollDecision({ error: err, consecutiveFailures, elapsedPolls });
    if (decision === 'retry-transient') {
      consecutiveFailures += 1;
      if (polling) timerId = schedule(_tick, intervalMs);
      return;
    }
    // 'stop-404' or 'give-up' — bounded, so this loop cannot run forever
    // against a status endpoint that never stops answering the way this
    // caller expects.
    stop();
    if (onGiveUp) onGiveUp();
  }

  function start() {
    if (polling) return Promise.resolve();
    polling = true;
    consecutiveFailures = 0;
    elapsedPolls = 0;
    return _tick();
  }

  function stop() {
    polling = false;
    _clearTimer();
  }

  return { start, stop, isPolling: () => polling };
}
