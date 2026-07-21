import test from 'node:test';
import assert from 'node:assert/strict';
import {
  buildViewerUrl,
  normalizeQuoteForSearch,
  readerTabs,
  findMissState,
} from '../../research_companion/lab/static/js/readerPdfHelpers.js';

test('normalizeQuoteForSearch collapses whitespace and heals hyphenation', () => {
  assert.equal(
    normalizeQuoteForSearch('adaptive compu-\ntation   time\nfor RNNs'),
    'adaptive computation time for RNNs');
});

test('normalizeQuoteForSearch strips wrapping quotes/ellipses and caps at 12 words', () => {
  const long = '"' + Array.from({length: 20}, (_, i) => 'w' + i).join(' ') + '…"';
  const out = normalizeQuoteForSearch(long);
  assert.equal(out.split(' ').length, 12);
  assert.ok(!out.includes('"') && !out.includes('…'));
});

test('normalizeQuoteForSearch empty input', () => {
  assert.equal(normalizeQuoteForSearch('   '), '');
  assert.equal(normalizeQuoteForSearch(null), '');
});

test('buildViewerUrl without quote has no search fragment', () => {
  const url = buildViewerUrl('arxiv:1603.08983');
  assert.ok(url.startsWith('/static/vendor/pdfjs/web/viewer.html?file='));
  assert.ok(!url.includes('#search='));
  assert.ok(url.includes(encodeURIComponent('arxiv')));  // id encoded inside file param
});

test('buildViewerUrl with quote appends encoded phrase search', () => {
  const url = buildViewerUrl('arxiv:1', { quote: 'state  transition\nmodel' });
  assert.ok(url.includes('#search=' + encodeURIComponent('state transition model')));
  assert.ok(url.includes('&phrase=true'));
});

test('readerTabs matrix', () => {
  assert.deepEqual(readerTabs(true), { tabs: ['original', 'text'], active: 'original' });
  assert.deepEqual(readerTabs(false), { tabs: ['text'], active: 'text' });
});

test('findMissState transitions', () => {
  assert.equal(findMissState([], false), 'pending');
  assert.equal(findMissState([{ total: 3 }], false), 'found');
  assert.equal(findMissState([{ total: 0, final: true }], false), 'missed');
  assert.equal(findMissState([], true), 'missed');
  assert.equal(findMissState([{ total: 0, final: false }], false), 'pending');
});
