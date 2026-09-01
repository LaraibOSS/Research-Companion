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

// Found on a live search for "KV cache compression": OpenAlex returned
// Scissorhands twice -- once under the proceedings DOI, once under the arXiv
// DOI -- and the two rows shared no identifier, so both were offered to the
// user.
test('dedupeDiscoverResults: collapses the proceedings and preprint records of one paper', () => {
  const title = 'Scissorhands: Exploiting the Persistence of Importance Hypothesis '
    + 'for LLM KV Cache Compression at Test Time';
  const out = dedupeDiscoverResults([
    { title, doi: '10.52202/075280-2279', arxiv_id: null, year: 2023, citation_count: 16 },
    { title, doi: '10.48550/arxiv.2305.17118', arxiv_id: '2305.17118', year: 2023, citation_count: 11 },
  ]);
  assert.equal(out.length, 1);
});

test('dedupeDiscoverResults: the surviving copy keeps an add target from the copy it replaced', () => {
  const title = 'Scissorhands';
  const out = dedupeDiscoverResults([
    { title, doi: '10.52202/075280-2279', year: 2023, citation_count: 16 },
    { title, arxiv_id: '2305.17118', year: 2023, citation_count: 11 },
  ]);
  assert.equal(out.length, 1);
  assert.equal(out[0].citation_count, 16, 'higher-cited copy still wins');
  assert.equal(out[0].arxiv_id, '2305.17118', 'but it adopts the id it lacked');
});

test('dedupeDiscoverResults: an arXiv DOI matches a bare arXiv id', () => {
  const out = dedupeDiscoverResults([
    { title: 'One', doi: '10.48550/arXiv.2305.17118', year: 2023 },
    { title: 'A differently worded record', arxiv_id: '2305.17118', year: 2024 },
  ]);
  assert.equal(out.length, 1);
});

test('dedupeDiscoverResults: DOIs differing only in case are one paper', () => {
  const out = dedupeDiscoverResults([
    { title: 'One', doi: '10.1/ABC', year: 2023 },
    { title: 'Two', doi: '10.1/abc', year: 2024 },
  ]);
  assert.equal(out.length, 1);
});

test('dedupeDiscoverResults: the same title in different years stays two papers', () => {
  const out = dedupeDiscoverResults([
    { title: 'Annual Report', year: 2023 },
    { title: 'Annual Report', year: 2024 },
  ]);
  assert.equal(out.length, 2, 'a title key without a year would over-merge');
});

test('dedupeDiscoverResults: untitled rows with no ids never merge into each other', () => {
  const out = dedupeDiscoverResults([{ title: '' }, { title: '' }]);
  assert.equal(out.length, 0, 'nothing to key on and nothing to show');
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
