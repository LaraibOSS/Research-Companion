/**
 * libraryGapsHelpers.js — one answer to "what is missing from my library?"
 *
 * There were two answers, on two surfaces, counting two different things: a
 * top banner for works cited but not held, and a chip inside Library for
 * papers that could not be downloaded. A researcher does not experience those
 * as two problems. They experience one — the library is incomplete — and they
 * want a number they can act on.
 *
 * THE RULE THIS MODULE FOLLOWS: it groups by what the reader can DO, not by
 * what went wrong internally. A publisher's bot filter and a login page are
 * different failures and the same errand: open it in your browser. A paywall
 * and an unindexed work are different failures and the same dead end: no free
 * copy exists. Grouping by internal reason would be honest and useless.
 *
 * Transient failures are deliberately absent. `SOURCE_UNAVAILABLE` is the
 * machine's problem; putting it here would be asking a person to fix a
 * timeout.
 *
 * Pure and DOM-free (node-testable). Returns RAW strings; the caller escapes
 * at the interpolation site.
 */

/** Reasons a person can clear by opening the article themselves. */
const _FETCHABLE = new Set(['blocked_by_host', 'not_a_pdf']);

/** Reasons where no free copy was found at all. */
const _UNAVAILABLE = new Set(['paywalled', 'no_location_found']);

/**
 * Count what is missing, by what the reader can do about it.
 *
 * @param {Array|null} papers — GET /api/papers payload
 * @param {object|null} coverage — the draft's citation-coverage payload
 * @returns {{fetchable:number, unavailable:number, uncited:number, total:number}}
 *   Never throws.
 */
export function libraryGaps(papers, coverage) {
  let fetchable = 0;
  let unavailable = 0;

  const list = Array.isArray(papers) ? papers : [];
  for (const p of list) {
    if (!p || typeof p !== 'object') continue;
    const acq = p.acquisition;
    if (!acq || typeof acq !== 'object') continue;
    const reason = typeof acq.reason === 'string' ? acq.reason : '';
    if (_FETCHABLE.has(reason)) fetchable += 1;
    else if (_UNAVAILABLE.has(reason)) unavailable += 1;
    // Anything else — transient, not-attempted, an unrecognised code from a
    // newer backend — is deliberately not counted rather than guessed at.
  }

  const cov = (coverage && typeof coverage === 'object') ? coverage : {};
  const counts = (cov.counts && typeof cov.counts === 'object') ? cov.counts : {};
  const total = Number(counts.total) || 0;
  const held = Number(counts.in_library) || 0;
  // Only a detected bibliography gives a denominator worth reporting. When
  // coverage was derived from related-work MENTIONS instead, the difference is
  // not a set of missing citations, and counting it as one would manufacture a
  // gap out of a weaker signal. An absent `source` is not a denial -- some
  // payload paths omit it -- so only an explicit non-bibliography source opts out.
  const fromBibliography = !cov.source || cov.source === 'bibliography';
  const uncited = fromBibliography ? Math.max(0, total - held) : 0;

  return { fetchable, unavailable, uncited, total: fetchable + unavailable + uncited };
}

/**
 * Display model for the gaps notice.
 *
 * A line with a zero count is omitted rather than shown as a zero — "0 papers
 * have no free copy" is noise dressed as information.
 *
 * `summary` is what the top bar shows: one line, because that bar is a thin
 * strip and a four-line block there would shout. `lines` carries the same
 * breakdown for a surface with room to lay it out.
 *
 * @param {{fetchable:number, unavailable:number, uncited:number, total:number}} gaps
 * @returns {{show:boolean, headline:string, summary:string,
 *            lines:Array<{count:number, text:string}>}}
 *   `show` false when nothing is missing. Never throws.
 */
export function gapsBannerModel(gaps) {
  const g = (gaps && typeof gaps === 'object') ? gaps : {};
  const total = Number(g.total) || 0;
  if (total <= 0) return { show: false, headline: '', summary: '', lines: [] };

  //                       [ count,  full wording,                                        compact ]
  const candidates = [
    [Number(g.fetchable) || 0,
     'your browser can fetch — the publisher blocks automated downloads',
     'your browser can fetch'],
    [Number(g.unavailable) || 0,
     'no free copy exists anywhere we searched',
     'with no free copy'],
    [Number(g.uncited) || 0,
     'cited in your draft, not in your library',
     'cited but not held'],
  ];
  const present = candidates.filter(([n]) => n > 0);

  const headline = `${total} gap${total === 1 ? '' : 's'} in your library`;
  const breakdown = present.map(([count, , compact]) => `${count} ${compact}`).join(', ');

  return {
    show: true,
    headline,
    summary: `${headline} — ${breakdown}`,
    lines: present.map(([count, text]) => ({ count, text })),
  };
}
