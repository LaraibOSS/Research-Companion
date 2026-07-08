/**
 * placementHelpers.test.mjs — tests for the pure Citation Placement helpers.
 *   placementCounts, statusChip, groupByStatus, citedSectionTitles
 *
 * Run from repo root:
 *   node --test tests/js/placementHelpers.test.mjs
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, '..', '..');

const {
  placementCounts,
  statusChip,
  groupByStatus,
  citedSectionTitles,
} = await import(
  pathToFileURL(path.join(repoRoot, 'research_companion', 'lab', 'static', 'js', 'placementHelpers.js')).href
);

// -----------------------------------------------------------------------
// placementCounts
// -----------------------------------------------------------------------

test('placementCounts: null returns zeros', () => {
  const c = placementCounts(null);
  assert.deepEqual(c, { total: 0, well_placed: 0, misplaced: 0, unknown: 0 });
});

test('placementCounts: reads counts field', () => {
  const c = placementCounts({ counts: { total: 5, well_placed: 2, misplaced: 1, unknown: 2 } });
  assert.equal(c.total, 5);
  assert.equal(c.misplaced, 1);
});

// -----------------------------------------------------------------------
// statusChip
// -----------------------------------------------------------------------

test('statusChip: well_placed is ok', () => {
  assert.equal(statusChip('well_placed').cls, 'chip-ok');
});

test('statusChip: misplaced is warn', () => {
  assert.equal(statusChip('misplaced').cls, 'chip-warn');
});

test('statusChip: unknown is muted', () => {
  assert.equal(statusChip('unknown').cls, 'chip-muted');
});

test('statusChip: unrecognized falls back to muted', () => {
  assert.equal(statusChip('weird').cls, 'chip-muted');
});

// -----------------------------------------------------------------------
// groupByStatus — misplaced first, then unknown, then well_placed
// -----------------------------------------------------------------------

test('groupByStatus: null/empty returns []', () => {
  assert.deepEqual(groupByStatus(null), []);
  assert.deepEqual(groupByStatus([]), []);
});

test('groupByStatus: orders misplaced, unknown, well_placed', () => {
  const input = [
    { paper_id: 'a', status: 'well_placed' },
    { paper_id: 'b', status: 'unknown' },
    { paper_id: 'c', status: 'misplaced' },
  ];
  const out = groupByStatus(input).map(p => p.status);
  assert.deepEqual(out, ['misplaced', 'unknown', 'well_placed']);
});

test('groupByStatus: preserves within-group order', () => {
  const input = [
    { paper_id: 'm1', status: 'misplaced' },
    { paper_id: 'm2', status: 'misplaced' },
  ];
  const out = groupByStatus(input).map(p => p.paper_id);
  assert.deepEqual(out, ['m1', 'm2']);
});

// -----------------------------------------------------------------------
// citedSectionTitles
// -----------------------------------------------------------------------

test('citedSectionTitles: joins titles', () => {
  const pl = { cited_sections: [{ title: 'Introduction' }, { title: 'Methods' }] };
  assert.equal(citedSectionTitles(pl), 'Introduction, Methods');
});

test('citedSectionTitles: safe on missing field', () => {
  assert.equal(citedSectionTitles({}), '');
  assert.equal(citedSectionTitles(null), '');
});
