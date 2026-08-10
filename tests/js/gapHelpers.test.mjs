import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  gapThemeRowModel,
  sortGapThemes,
  filterGapThemes,
} from '../../research_companion/lab/static/js/gapHelpers.js';

// ---------------------------------------------------------------------------
// gapThemeRowModel
// ---------------------------------------------------------------------------

test('gapThemeRowModel: maps a full theme to a display row', () => {
  const theme = {
    theme_id: 'theme_abc',
    title: 'Scaling limitations',
    bullet: 'Scaling to large datasets remains unaddressed.',
    fws_type: 'method',
    type: 'limitation',
    citations: [{ paper_id: 'arxiv:2001.00001', title: 'Paper A', year: 2020 }],
    status: 'open',
    frequency: 1,
    recency: 2020,
    score: 3.0,
    gap_ids: ['gap_x'],
  };
  const row = gapThemeRowModel(theme, []);
  assert.equal(row.id, 'theme_abc');
  assert.equal(row.title, 'Scaling limitations');
  assert.equal(row.bullet, 'Scaling to large datasets remains unaddressed.');
  assert.equal(row.typeLabel, 'Limitation');
  assert.equal(row.typeKey, 'limitation');
  assert.equal(row.fwsLabel, 'Method');
  assert.equal(row.fwsKey, 'method');
  assert.equal(row.statusLabel, 'Open');
  assert.equal(row.statusKey, 'open');
  assert.equal(row.citations.length, 1);
  assert.equal(row.citations[0].paperId, 'arxiv:2001.00001');
  assert.equal(row.citations[0].title, 'Paper A');
  assert.equal(row.citations[0].year, 2020);
  assert.equal(row.frequency, 1);
  assert.equal(row.recency, 2020);
  assert.equal(row.score, 3.0);
  assert.equal(row.addressedByDraft, false);
});

test('gapThemeRowModel: future_work type and partial/addressed status labels', () => {
  const base = {
    theme_id: 't', title: 'T', bullet: 'B', fws_type: 'evaluation',
    type: 'future_work', citations: [], frequency: 0, recency: null, score: 0, gap_ids: [],
  };
  assert.equal(gapThemeRowModel({ ...base, status: 'open' }, []).statusLabel, 'Open');
  assert.equal(gapThemeRowModel({ ...base, status: 'partial' }, []).statusLabel, 'Partially addressed');
  assert.equal(gapThemeRowModel({ ...base, status: 'addressed' }, []).statusLabel, 'Addressed');
  assert.equal(gapThemeRowModel(base, []).typeLabel, 'Future work');
  assert.equal(gapThemeRowModel(base, []).fwsLabel, 'Evaluation');
});

test('gapThemeRowModel: addressedByDraft true when a member gap_id is in draftAddresses', () => {
  const theme = {
    theme_id: 't', title: 'T', bullet: 'B', fws_type: 'other', type: 'limitation',
    citations: [], status: 'open', frequency: 1, recency: 2020, score: 1,
    gap_ids: ['gap_x', 'gap_y'],
  };
  assert.equal(gapThemeRowModel(theme, ['gap_y']).addressedByDraft, true);
  assert.equal(gapThemeRowModel(theme, ['gap_z']).addressedByDraft, false);
  assert.equal(gapThemeRowModel(theme, []).addressedByDraft, false);
  assert.equal(gapThemeRowModel(theme, null).addressedByDraft, false);
  assert.equal(gapThemeRowModel(theme, undefined).addressedByDraft, false);
});

test('gapThemeRowModel: never throws on missing/partial fields (safe defaults)', () => {
  assert.doesNotThrow(() => gapThemeRowModel({}, undefined));
  assert.doesNotThrow(() => gapThemeRowModel(null, undefined));
  assert.doesNotThrow(() => gapThemeRowModel(undefined, undefined));
  const row = gapThemeRowModel({}, undefined);
  assert.equal(row.id, '');
  assert.equal(row.title, 'Untitled theme');
  assert.equal(row.bullet, '');
  assert.deepEqual(row.citations, []);
  assert.equal(row.frequency, 0);
  assert.equal(row.recency, null);
  assert.equal(row.score, 0);
  assert.equal(row.addressedByDraft, false);
});

test('gapThemeRowModel: unknown status/fws_type/type default safely', () => {
  const row = gapThemeRowModel({
    theme_id: 't', title: 'T', bullet: 'B', fws_type: 'not_real',
    type: 'not_real', status: 'not_real', citations: [], frequency: 0,
    recency: null, score: 0, gap_ids: [],
  }, []);
  assert.equal(row.statusKey, 'open');
  assert.equal(row.statusLabel, 'Open');
  assert.equal(row.fwsKey, 'other');
  assert.equal(row.fwsLabel, 'Other');
  assert.equal(row.typeKey, 'limitation');
  assert.equal(row.typeLabel, 'Limitation');
});

test('gapThemeRowModel: derives frequency from citations length when frequency missing', () => {
  const row = gapThemeRowModel({
    theme_id: 't', title: 'T', bullet: 'B', fws_type: 'other', type: 'limitation',
    citations: [{ paper_id: 'a', title: 'A', year: 2020 }, { paper_id: 'b', title: 'B', year: 2021 }],
    status: 'open', recency: 2021, score: 1, gap_ids: [],
  }, []);
  assert.equal(row.frequency, 2);
});

// ---------------------------------------------------------------------------
// sortGapThemes
// ---------------------------------------------------------------------------

function _row(overrides) {
  return { id: 'x', title: 'X', bullet: '', typeLabel: 'Limitation', typeKey: 'limitation',
    fwsLabel: 'Other', fwsKey: 'other', statusLabel: 'Open', statusKey: 'open',
    citations: [], frequency: 1, recency: 2020, score: 1, addressedByDraft: false, ...overrides };
}

test('sortGapThemes: sorts by score descending by default direction', () => {
  const rows = [_row({ id: 'low', score: 1 }), _row({ id: 'high', score: 5 })];
  const sorted = sortGapThemes(rows, 'score', 'desc');
  assert.deepEqual(sorted.map(r => r.id), ['high', 'low']);
});

test('sortGapThemes: ascending direction reverses order', () => {
  const rows = [_row({ id: 'low', score: 1 }), _row({ id: 'high', score: 5 })];
  const sorted = sortGapThemes(rows, 'score', 'asc');
  assert.deepEqual(sorted.map(r => r.id), ['low', 'high']);
});

test('sortGapThemes: sorts by recency, nulls last regardless of direction', () => {
  const rows = [_row({ id: 'no_year', recency: null }), _row({ id: '2020', recency: 2020 }), _row({ id: '2023', recency: 2023 })];
  const desc = sortGapThemes(rows, 'recency', 'desc');
  assert.deepEqual(desc.map(r => r.id), ['2023', '2020', 'no_year']);
  const asc = sortGapThemes(rows, 'recency', 'asc');
  assert.deepEqual(asc.map(r => r.id), ['2020', '2023', 'no_year']);
});

test('sortGapThemes: sorts by frequency', () => {
  const rows = [_row({ id: 'a', frequency: 1 }), _row({ id: 'b', frequency: 3 })];
  assert.deepEqual(sortGapThemes(rows, 'frequency', 'desc').map(r => r.id), ['b', 'a']);
});

test('sortGapThemes: sorts by title case-insensitively', () => {
  const rows = [_row({ id: 'z', title: 'zebra' }), _row({ id: 'a', title: 'Apple' })];
  assert.deepEqual(sortGapThemes(rows, 'title', 'asc').map(r => r.id), ['a', 'z']);
});

test('sortGapThemes: stable for equal scores', () => {
  const rows = [_row({ id: 'a', score: 1 }), _row({ id: 'b', score: 1 }), _row({ id: 'c', score: 1 })];
  assert.deepEqual(sortGapThemes(rows, 'score', 'desc').map(r => r.id), ['a', 'b', 'c']);
});

test('sortGapThemes: never mutates input, handles non-array input', () => {
  const rows = [_row({ id: 'a' })];
  const copy = [...rows];
  sortGapThemes(rows, 'score', 'desc');
  assert.deepEqual(rows, copy);
  assert.deepEqual(sortGapThemes(null, 'score', 'desc'), []);
  assert.deepEqual(sortGapThemes(undefined, 'score', 'desc'), []);
});

// ---------------------------------------------------------------------------
// filterGapThemes
// ---------------------------------------------------------------------------

test('filterGapThemes: filters by type', () => {
  const rows = [_row({ id: 'lim', typeKey: 'limitation' }), _row({ id: 'fw', typeKey: 'future_work' })];
  assert.deepEqual(filterGapThemes(rows, { type: 'limitation' }).map(r => r.id), ['lim']);
});

test('filterGapThemes: filters by status', () => {
  const rows = [_row({ id: 'open', statusKey: 'open' }), _row({ id: 'closed', statusKey: 'addressed' })];
  assert.deepEqual(filterGapThemes(rows, { status: 'addressed' }).map(r => r.id), ['closed']);
});

test('filterGapThemes: combines type and status filters', () => {
  const rows = [
    _row({ id: 'a', typeKey: 'limitation', statusKey: 'open' }),
    _row({ id: 'b', typeKey: 'limitation', statusKey: 'addressed' }),
    _row({ id: 'c', typeKey: 'future_work', statusKey: 'open' }),
  ];
  assert.deepEqual(
    filterGapThemes(rows, { type: 'limitation', status: 'open' }).map(r => r.id),
    ['a'],
  );
});

test("filterGapThemes: 'all' or missing filter means no filtering on that dimension", () => {
  const rows = [_row({ id: 'a' }), _row({ id: 'b' })];
  assert.equal(filterGapThemes(rows, { type: 'all', status: 'all' }).length, 2);
  assert.equal(filterGapThemes(rows, {}).length, 2);
  assert.equal(filterGapThemes(rows, null).length, 2);
});

test('filterGapThemes: never mutates input, handles non-array input', () => {
  assert.deepEqual(filterGapThemes(null, {}), []);
  assert.deepEqual(filterGapThemes(undefined, {}), []);
});
