/**
 * tests/js/discoverHelpers.test.mjs — pure Brainstorm/discover display helpers.
 * Run: node --test tests/js/discoverHelpers.test.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  discoverResultModel,
  dedupeDiscoverResults,
  sortDiscoverResults,
} from '../../research_companion/lab/static/js/discoverHelpers.js';

// ---------------------------------------------------------------------------
// discoverResultModel
// ---------------------------------------------------------------------------

test('discoverResultModel: maps a full raw result to a display row', () => {
  const raw = {
    title: 'GraphRAG: Graph Retrieval-Augmented Generation',
    authors: ['A. One', 'B. Two'],
    year: 2024,
    citation_count: 42,
    arxiv_id: '2404.16130',
    doi: null,
    s2_id: 'abc123',
    url: 'https://arxiv.org/abs/2404.16130',
    abstract: 'A short abstract about graph retrieval.',
    source: 'search',
    pmid: null,
    pmcid: null,
    add_cmd: 'research-companion add 2404.16130',
    in_library: false,
  };
  const row = discoverResultModel(raw, null);
  assert.equal(row.title, 'GraphRAG: Graph Retrieval-Augmented Generation');
  assert.equal(row.authorsText, 'A. One, B. Two');
  assert.equal(row.year, 2024);
  assert.equal(row.citationCount, 42);
  assert.equal(row.source, 'search');
  assert.equal(row.sourceLabel, 'Semantic Scholar');
  assert.equal(row.abstractShort, 'A short abstract about graph retrieval.');
  assert.equal(row.inLibrary, false);
  assert.equal(row.addTarget, '2404.16130');
  assert.equal(row.arxivId, '2404.16130');
});

test('discoverResultModel: in_library true from the raw payload', () => {
  const row = discoverResultModel({ title: 'T', in_library: true }, null);
  assert.equal(row.inLibrary, true);
});

test('discoverResultModel: inLibrary true from an injected libraryIds set', () => {
  const raw = { title: 'T', arxiv_id: '2401.00001', in_library: false };
  const row = discoverResultModel(raw, new Set(['arxiv:2401.00001']));
  assert.equal(row.inLibrary, true);
});

test('discoverResultModel: addTarget precedence pmid > arxiv > doi > s2 > url', () => {
  assert.equal(discoverResultModel({ title: 'T', pmid: '999', arxiv_id: 'x', doi: 'y', s2_id: 'z' }).addTarget, 'pmid:999');
  assert.equal(discoverResultModel({ title: 'T', arxiv_id: 'x', doi: 'y', s2_id: 'z' }).addTarget, 'x');
  assert.equal(discoverResultModel({ title: 'T', doi: 'y', s2_id: 'z' }).addTarget, 'y');
  assert.equal(discoverResultModel({ title: 'T', s2_id: 'z' }).addTarget, 'z');
  assert.equal(discoverResultModel({ title: 'T', url: 'https://x' }).addTarget, 'https://x');
});

test('discoverResultModel: missing fields default safely', () => {
  const row = discoverResultModel({}, null);
  assert.equal(row.title, 'Untitled');
  assert.equal(row.authorsText, 'Unknown authors');
  assert.equal(row.year, null);
  assert.equal(row.citationCount, 0);
  assert.equal(row.sourceLabel, 'Unknown source');
  assert.equal(row.abstractShort, '');
  assert.equal(row.inLibrary, false);
  assert.equal(row.addTarget, '');
});

test('discoverResultModel: never throws on null/undefined/non-object input', () => {
  assert.doesNotThrow(() => discoverResultModel(null, null));
  assert.doesNotThrow(() => discoverResultModel(undefined, undefined));
  assert.doesNotThrow(() => discoverResultModel('not an object', null));
  assert.doesNotThrow(() => discoverResultModel({ authors: 'not an array' }, null));
});

test('discoverResultModel: escapes HTML-unsafe title and author strings', () => {
  const row = discoverResultModel({
    title: '<script>alert(1)</script>',
    authors: ['<b>Evil</b>'],
  }, null);
  assert.ok(!row.title.includes('<script>'));
  assert.ok(row.title.includes('&lt;script&gt;'));
  assert.ok(!row.authorsText.includes('<b>'));
});

test('discoverResultModel: long abstract is truncated with an ellipsis', () => {
  const row = discoverResultModel({ title: 'T', abstract: 'x'.repeat(300) }, null);
  assert.ok(row.abstractShort.length < 300);
  assert.ok(row.abstractShort.endsWith('…'));
});

// ---------------------------------------------------------------------------
// dedupeDiscoverResults
// ---------------------------------------------------------------------------

test('dedupeDiscoverResults: merges by identity, keeps the higher-citation copy', () => {
  const list = [
    { title: 'Paper A', arxiv_id: '2401.00001', citation_count: 5 },
    { title: 'Paper A dup', arxiv_id: '2401.00001', citation_count: 50 },
    { title: 'Paper B', doi: '10.1/xyz', citation_count: 3 },
  ];
  const out = dedupeDiscoverResults(list);
  assert.equal(out.length, 2);
  const a = out.find(r => r.arxiv_id === '2401.00001');
  assert.equal(a.citation_count, 50);
});

test('dedupeDiscoverResults: no shared identity keeps every result, order preserved', () => {
  const list = [
    { title: 'One', arxiv_id: 'a' },
    { title: 'Two', doi: 'b' },
    { title: 'Three', s2_id: 'c' },
  ];
  const out = dedupeDiscoverResults(list);
  assert.deepEqual(out.map(r => r.title), ['One', 'Two', 'Three']);
});

test('dedupeDiscoverResults: falls back to title token when no namespaced id', () => {
  const list = [
    { title: 'Same Title', citation_count: 1 },
    { title: 'same title', citation_count: 9 },
  ];
  const out = dedupeDiscoverResults(list);
  assert.equal(out.length, 1);
  assert.equal(out[0].citation_count, 9);
});

test('dedupeDiscoverResults: never throws on malformed input', () => {
  assert.doesNotThrow(() => dedupeDiscoverResults(null));
  assert.doesNotThrow(() => dedupeDiscoverResults(undefined));
  assert.deepEqual(dedupeDiscoverResults([null, undefined, {}]).length >= 0, true);
});

// ---------------------------------------------------------------------------
// sortDiscoverResults
// ---------------------------------------------------------------------------

test('sortDiscoverResults: sorts by citations descending by default', () => {
  const rows = [{ citationCount: 5, title: 'a' }, { citationCount: 50, title: 'b' }, { citationCount: 1, title: 'c' }];
  const out = sortDiscoverResults(rows, 'citations');
  assert.deepEqual(out.map(r => r.title), ['b', 'a', 'c']);
});

test('sortDiscoverResults: sorts by year ascending when dir=asc', () => {
  const rows = [{ year: 2022, title: 'a' }, { year: 2018, title: 'b' }, { year: 2024, title: 'c' }];
  const out = sortDiscoverResults(rows, 'year', 'asc');
  assert.deepEqual(out.map(r => r.title), ['b', 'a', 'c']);
});

test('sortDiscoverResults: relevance is a no-op (preserves input/API order)', () => {
  const rows = [{ citationCount: 1, title: 'first' }, { citationCount: 99, title: 'second' }];
  const out = sortDiscoverResults(rows, 'relevance');
  assert.deepEqual(out.map(r => r.title), ['first', 'second']);
});

test('sortDiscoverResults: nulls sort last, stable ties keep original order', () => {
  const rows = [
    { citationCount: null, title: 'no-count-1' },
    { citationCount: 5, title: 'has-count' },
    { citationCount: null, title: 'no-count-2' },
  ];
  const out = sortDiscoverResults(rows, 'citations');
  assert.deepEqual(out.map(r => r.title), ['has-count', 'no-count-1', 'no-count-2']);
});

test('sortDiscoverResults: never throws and never mutates the input array', () => {
  const rows = [{ citationCount: 1 }, { citationCount: 2 }];
  const copy = rows.slice();
  assert.doesNotThrow(() => sortDiscoverResults(null, 'citations'));
  sortDiscoverResults(rows, 'citations');
  assert.deepEqual(rows, copy);
});
