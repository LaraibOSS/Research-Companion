/**
 * oaLinkHelpers.js — Pure, DOM-free helpers for the "Find PDF" library
 * affordance (open-access PDF locator UI).
 *
 * All functions are stateless and have no DOM dependencies so they can be
 * tested with node --test.
 */

import { isMissingPdfFailure } from './libraryHelpers.js';

// Inline OA links are capped so a locator that returns a long list can't
// blow out the card/row layout.
const MAX_OA_LINKS = 5;

// Only http(s) links are ever rendered as clickable anchors — this also
// blocks javascript: and other unsafe schemes a malformed/malicious
// locator response might contain.
const HTTP_URL_RE = /^https?:\/\//;

/**
 * Decide which "Find PDF" affordance to render for a paper.
 *
 * - Anything other than a failed, missing-PDF-on-disk failure -> 'hidden'
 *   (done papers, still-processing papers, and OTHER failure classes like
 *   a parser/extraction crash — the locator can't fix those).
 * - A missing-PDF failure with no usable oa_links yet -> 'button' (offer to
 *   search).
 * - A missing-PDF failure that already carries usable oa_links (a prior
 *   search came back with a miss but found some links) -> 'button-with-links'
 *   (offer to search again, plus show what was found).
 *
 * @param {object|null|undefined} paper — paper summary from GET /api/papers
 * @returns {'hidden'|'button'|'button-with-links'}
 */
export function findPdfAffordance(paper) {
  if (!paper || paper.status !== 'failed') return 'hidden';
  if (!isMissingPdfFailure(paper.failure_reason)) return 'hidden';
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
