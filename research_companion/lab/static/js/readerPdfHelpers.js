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

export function readerTabs(hasPdf) {
  return hasPdf
    ? { tabs: ['original', 'text'], active: 'original' }
    : { tabs: ['text'], active: 'text' };
}

export function findMissState(events, timeoutFired) {
  for (const e of events || []) {
    if ((e.total ?? 0) > 0) return 'found';
  }
  const finalZero = (events || []).some(e => (e.total ?? 0) === 0 && e.final);
  if (finalZero || timeoutFired) return 'missed';
  return 'pending';
}
