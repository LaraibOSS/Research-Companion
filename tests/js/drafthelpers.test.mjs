/**
 * drafthelpers.test.mjs — tests for the pure draftSectionModel() helper
 * (research_companion/lab/static/js/draftHelpers.js), which decides whether the
 * Draft view renders per-paper alignment or falls back to the draft's own
 * outline when no alignment exists yet.
 *
 * Run from repo root:
 *   node --test tests/js/drafthelpers.test.mjs
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, '..', '..');

const { draftSectionModel } = await import(
  pathToFileURL(path.join(repoRoot, 'research_companion', 'lab', 'static', 'js', 'draftHelpers.js')).href
);

test('draftSectionModel: uses alignment sections verbatim when present', () => {
  const aligned = [{ section_id: 's1', title: 'Intro', alignments: [{ paper_id: 'p1' }] }];
  const m = draftSectionModel(aligned, [{ section_id: 'sx', title: 'X' }]);
  assert.equal(m.fromOutline, false);
  assert.equal(m.sections, aligned); // same array, untouched
});

test('draftSectionModel: falls back to outline (empty alignments) when no alignment', () => {
  const outline = [
    { section_id: 's1', title: 'Introduction', level: 1, node_count: 0 },
    { section_id: 's2', title: 'Method', level: 2 },
  ];
  const m = draftSectionModel([], outline);
  assert.equal(m.fromOutline, true);
  assert.equal(m.sections.length, 2);
  assert.deepEqual(m.sections[0], { section_id: 's1', title: 'Introduction', level: 1, alignments: [] });
  assert.deepEqual(m.sections[1].alignments, []);
  assert.equal(m.sections[1].title, 'Method');
});

test('draftSectionModel: title falls back to section_id; missing fields tolerated', () => {
  const m = draftSectionModel([], [{ section_id: 's9' }, {}]);
  assert.equal(m.fromOutline, true);
  assert.equal(m.sections[0].title, 's9');
  assert.equal(m.sections[0].level, 1);
  assert.equal(m.sections[1].section_id, '');
});

test('draftSectionModel: both empty -> empty sections, not fromOutline', () => {
  const m = draftSectionModel([], []);
  assert.deepEqual(m.sections, []);
  assert.equal(m.fromOutline, false);
});

test('draftSectionModel: never throws on absent/non-array input', () => {
  assert.doesNotThrow(() => draftSectionModel(undefined, undefined));
  assert.doesNotThrow(() => draftSectionModel(null, null));
  assert.doesNotThrow(() => draftSectionModel(5, 'x'));
  const m = draftSectionModel(null, null);
  assert.deepEqual(m, { sections: [], fromOutline: false });
});
