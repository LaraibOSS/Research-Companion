/**
 * oaLinkHelpers.js — Pure, DOM-free helpers for the "Find PDF" library
 * affordance (open-access PDF locator UI).
 *
 * All functions are stateless and have no DOM dependencies so they can be
 * tested with node --test.
 */

// Inline OA links are capped so a locator that returns a long list can't
// blow out the card/row layout.
const MAX_OA_LINKS = 5;

// Only http(s) links are ever rendered as clickable anchors — this also
// blocks javascript: and other unsafe schemes a malformed/malicious
// locator response might contain.
const HTTP_URL_RE = /^https?:\/\//;

/**
 * Whether a person can do something about a paper's failure -- shared by
 * findPdfAffordance below and the "Upload PDF" button (components/paperCard.js,
 * views/library.js). Mirrors research_companion/lab_api.py's
 * _failure_human_can_help: reads the SAME acquisition.human_can_help flag
 * (Acquisition.human_can_help, research_companion/acquire/types.py) rather
 * than re-deriving it.
 *
 * A failure recorded with NO acquisition at all -- a stage that never went
 * through acquire(), e.g. a stale "no PDF on disk" (extract.py) or "PDF not
 * found" (fetch.py's add_local_pdf, the retry path) record from before
 * every acquisition attempt carried a typed Acquisition -- falls back to
 * `hasPdf`, computed in Python (`has_pdf` on the paper summary,
 * research_companion/lab_api.py's _build_paper_summary) from
 * store.pdf_path(paper_id). This module never guesses at what's on disk:
 * helpable only when Python says there is genuinely no PDF there (hasPdf
 * === false). A parse/OCR/graph failure on a PDF that IS present must not
 * get this affordance -- re-running acquisition and saving a hit would
 * silently overwrite a file the user already has.
 *
 * @param {object|null|undefined} acquisition
 * @param {boolean|null|undefined} hasPdf — paper.has_pdf / row.hasPdf
 * @returns {boolean}
 */
export function acquisitionAllowsHelp(acquisition, hasPdf) {
  if (acquisition && typeof acquisition === 'object') {
    return acquisition.human_can_help !== false;
  }
  return hasPdf === false;
}

/**
 * Decide which "Find PDF" affordance to render for a paper.
 *
 * - Anything other than a failed paper a person can help with -> 'hidden'
 *   (done papers, still-processing papers, and OTHER failure classes like
 *   a parser/extraction crash or a transient source-unavailable retry —
 *   the locator can't fix those; see acquisitionAllowsHelp above).
 * - A helpable failure with no usable oa_links yet -> 'button' (offer to
 *   search).
 * - A helpable failure that already carries usable oa_links (a prior
 *   search came back with a miss but found some links) -> 'button-with-links'
 *   (offer to search again, plus show what was found).
 *
 * @param {object|null|undefined} paper — paper summary from GET /api/papers
 * @returns {'hidden'|'button'|'button-with-links'}
 */
export function findPdfAffordance(paper) {
  if (!paper || paper.status !== 'failed') return 'hidden';
  if (!acquisitionAllowsHelp(paper.acquisition, paper.has_pdf)) return 'hidden';
  return oaLinksLine(paper.oa_links).show ? 'button-with-links' : 'button';
}

/**
 * Filter/validate a paper's oa_links for display: both label and url must be
 * non-empty strings, the url must be http(s), and the list is capped at
 * MAX_OA_LINKS entries.
 *
 * @param {Array<{label?: string, url?: string}>|null|undefined} links
 * @returns {{show: boolean, items: Array<{label: string, url: string}>}}
 */
export function oaLinksLine(links) {
  if (!Array.isArray(links) || links.length === 0) return { show: false, items: [] };

  const items = [];
  for (const link of links) {
    if (items.length >= MAX_OA_LINKS) break;
    if (!link || typeof link !== 'object') continue;
    const { label, url } = link;
    if (typeof label !== 'string' || label === '') continue;
    if (typeof url !== 'string' || !HTTP_URL_RE.test(url)) continue;
    items.push({ label, url });
  }

  return { show: items.length > 0, items };
}

// ---------------------------------------------------------------------------
// Find-PDF job poll state machine
// ---------------------------------------------------------------------------

// A find-pdf job's GET /api/jobs/{id} status is polled roughly once a
// second (views/library.js) until it leaves "running" — this bounds that
// loop to ~2 minutes of wall-clock time so a job that never reaches a
// terminal status (e.g. it wedged server-side) can't leave the poll running
// forever.
const MAX_POLLS = 120;

// A run of consecutive polling failures this deep (e.g. a network blip)
// gives up rather than retrying indefinitely; any successful poll resets
// this counter back to zero (see views/library.js).
const MAX_CONSECUTIVE_FAILURES = 5;

/**
 * Decide what a find-pdf job poll loop should do next, given the outcome of
 * the CURRENT poll attempt.
 *
 * Only call this for an attempt that is still "in flight" from the caller's
 * point of view: either the GET succeeded and the job is still 'running',
 * or the GET itself failed. A GET that succeeds with a TERMINAL job status
 * ('done'/'failed'/etc.) is normal completion, not this function's
 * concern — the caller should stop and do its final refresh directly
 * without consulting this decision.
 *
 * Precedence: a definitive 404 (job unknown — e.g. the server lost the job
 * record) always stops the loop immediately, even if the poll-count cap has
 * also been reached. Short of that, the poll-count cap is checked before
 * classifying any error, so it bounds BOTH the "still running" path and
 * repeated non-404 failures — otherwise a failure pattern that never quite
 * hits MAX_CONSECUTIVE_FAILURES (because occasional polls succeed) could
 * keep the loop alive indefinitely.
 *
 * @param {object} args
 * @param {string|undefined} args.status - job.status from a successful GET
 *   (expected 'running' here per the note above — not otherwise consulted;
 *   accepted for shape parity with the caller's poll result and to make
 *   test fixtures read naturally), or undefined when the GET failed.
 * @param {{status?: number}|Error|null|undefined} args.error - the thrown
 *   error from a failed GET (api.js sets `.status` from the HTTP response
 *   status when available), or falsy when the GET succeeded.
 * @param {number} [args.consecutiveFailures] - consecutive prior failures
 *   BEFORE this attempt (the caller resets this to 0 on any successful poll).
 * @param {number} [args.elapsedPolls] - total poll attempts made so far,
 *   INCLUDING this one.
 * @returns {'continue'|'stop-404'|'retry-transient'|'give-up'}
 */
export function pollDecision({ status, error, consecutiveFailures = 0, elapsedPolls = 0 } = {}) {
  if (error && error.status === 404) return 'stop-404';
  if (elapsedPolls >= MAX_POLLS) return 'give-up';
  if (error) {
    return (consecutiveFailures + 1 >= MAX_CONSECUTIVE_FAILURES) ? 'give-up' : 'retry-transient';
  }
  return 'continue';
}
