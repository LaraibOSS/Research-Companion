/**
 * Pure helpers for the Reader's "Original (PDF)" tab — viewer URL building,
 * quote→phrase normalization, tab defaults, and find-miss state. DOM-free so
 * they run under node:test.
 */
import { paperPdfUrl } from './api.js';   // pure id-encoding builder, no import-time side effects

const VIEWER_PATH = '/static/vendor/pdfjs/web/viewer.html';
const MAX_PHRASE_WORDS = 12;

export function normalizeQuoteForSearch(quote) {
  if (typeof quote !== 'string') return '';
  let q = quote
    .replace(/(\w)-\s*\n\s*(\w)/g, '$1$2')   // heal line-break hyphenation
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/^["'“”‘’…\s]+|["'“”‘’…\s]+$/g, '');
  if (!q) return '';
  return q.split(' ').slice(0, MAX_PHRASE_WORDS).join(' ');
}

export function buildViewerUrl(paperId, opts = {}) {
  const file = encodeURIComponent(paperPdfUrl(paperId));
  let url = `${VIEWER_PATH}?file=${file}`;
  const phrase = normalizeQuoteForSearch(opts.quote || '');
  if (phrase) url += `#search=${encodeURIComponent(phrase)}&phrase=true`;
  return url;
}

export function findDispatchParams(phrase) {
  // Payload contract of the vendored viewer's `find` eventBus event
  // (see onFindFromUrlHash in web/viewer.mjs): a STRING query means phrase
  // search (an array would mean individual words); type '' with an unchanged
  // query still forces a full re-search, which is what lets the reader
  // re-dispatch after subscribing without losing events to the #search
  // fragment's earlier find.
  return {
    source: null,
    type: '',
    query: phrase,
    caseSensitive: false,
    entireWord: false,
    highlightAll: true,
    findPrevious: false,
    matchDiacritics: true,
  };
}

export function readerTabs(hasPdf, hasSimplified = false) {
  if (hasPdf) return { tabs: ['original', 'simplified', 'text'], active: 'original' };
  return {
    tabs: ['simplified', 'text'],
    active: hasSimplified ? 'simplified' : 'text',
  };
}

export function findMissState(events, timeoutFired) {
  for (const e of events || []) {
    if ((e.total ?? 0) > 0) return 'found';
  }
  const finalZero = (events || []).some(e => (e.total ?? 0) === 0 && e.final);
  if (finalZero || timeoutFired) return 'missed';
  return 'pending';
}
