/**
 * tests/js/directionsHelpers.test.mjs — pure Research Directions (Brainstorm
 * 2b) display helpers.
 * Run: node --test tests/js/directionsHelpers.test.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { directionResultModel, sortDirections } from '../../research_companion/lab/static/js/directionsHelpers.js';

// ---------------------------------------------------------------------------
// directionResultModel
// ---------------------------------------------------------------------------

test('directionResultModel: maps a full raw direction to a display row', () => {
  const raw = {
    direction_id: 'dir_abc123',
    title: 'Extend GraphRAG to code',
    rationale: 'Apply graph retrieval to source-code search.',
    direction_type: 'new_application',
    citations: [
      { kind: 'paper', paper_id: 'arxiv:2401.00001', title: 'GraphRAG', year: 2024 },
      { kind: 'concept', name: 'Sparse concept' },
      { kind: 'gap', theme_id: 'theme_aaa', title: 'Missing benchmark' },
    ],
    grounding_count: 1,
    recency: 2024,
    score: 8.4,
  };
  const row = directionResultModel(raw);
  assert.equal(row.directionId, 'dir_abc123');
  assert.equal(row.title, 'Extend GraphRAG to code');
  assert.equal(row.rationale, 'Apply graph retrieval to source-code search.');
  assert.equal(row.typeBadge.slug, 'new_application');
  assert.equal(row.typeBadge.label, 'New application');
  assert.equal(row.groundingCount, 1);
  assert.equal(row.recency, 2024);
  assert.equal(row.score, 8.4);
  assert.equal(row.citations.length, 3);
});

test('directionResultModel: paper citation with paper_id is clickable (raw paperId present)', () => {
  const row = directionResultModel({
    title: 'T', citations: [{ kind: 'paper', paper_id: 'arxiv:2401.00001', title: 'P', year: 2020 }],
  });
  const c = row.citations[0];
  assert.equal(c.kind, 'paper');
  assert.equal(c.paperId, 'arxiv:2401.00001');
  assert.equal(c.label, 'P (2020)');
});

test('directionResultModel: paper citation without paper_id is informational (paperId null)', () => {
  const row = directionResultModel({
    title: 'T', citations: [{ kind: 'paper', paper_id: null, title: 'Seed Paper', year: null }],
  });
  const c = row.citations[0];
  assert.equal(c.kind, 'paper');
  assert.equal(c.paperId, null);
  assert.equal(c.label, 'Seed Paper');
});

test('directionResultModel: concept citation label uses name', () => {
  const row = directionResultModel({ title: 'T', citations: [{ kind: 'concept', name: 'Graph sparsity' }] });
  assert.equal(row.citations[0].kind, 'concept');
  assert.equal(row.citations[0].label, 'Graph sparsity');
  assert.equal(row.citations[0].name, 'Graph sparsity');
});

test('directionResultModel: gap citation label uses title, carries themeId', () => {
  const row = directionResultModel({
    title: 'T', citations: [{ kind: 'gap', theme_id: 'theme_aaa', title: 'Missing benchmark' }],
  });
  assert.equal(row.citations[0].kind, 'gap');
  assert.equal(row.citations[0].label, 'Missing benchmark');
  assert.equal(row.citations[0].themeId, 'theme_aaa');
});

test('directionResultModel: unknown direction_type falls back to "other" badge', () => {
  const row = directionResultModel({ title: 'T', direction_type: 'not_a_real_type' });
  assert.equal(row.typeBadge.slug, 'other');
  assert.equal(row.typeBadge.label, 'Other');
});

test('directionResultModel: missing fields default safely', () => {
  const row = directionResultModel({});
  assert.equal(row.title, 'Untitled direction');
  assert.equal(row.rationale, '');
  assert.equal(row.citations.length, 0);
  assert.equal(row.groundingCount, 0);
  assert.equal(row.recency, 0);
  assert.equal(row.score, 0);
});

test('directionResultModel: never throws on null/undefined/non-object/malformed citations', () => {
  assert.doesNotThrow(() => directionResultModel(null));
  assert.doesNotThrow(() => directionResultModel(undefined));
  assert.doesNotThrow(() => directionResultModel('not an object'));
  assert.doesNotThrow(() => directionResultModel({ citations: 'not-an-array' }));
  assert.doesNotThrow(() => directionResultModel({ citations: [null, 'x', {}] }));
});

test('directionResultModel: escapes HTML-unsafe title, rationale, and citation label', () => {
  const row = directionResultModel({
    title: '<script>alert(1)</script>',
    rationale: '<b>bold</b> claim',
    citations: [{ kind: 'concept', name: '<i>evil</i>' }],
  });
  assert.ok(!row.title.includes('<script>'));
  assert.ok(row.title.includes('&lt;script&gt;'));
  assert.ok(!row.rationale.includes('<b>'));
  assert.ok(!row.citations[0].label.includes('<i>'));
});

// ---------------------------------------------------------------------------
// sortDirections
// ---------------------------------------------------------------------------

test('sortDirections: sorts by score descending by default', () => {
  const rows = [{ score: 3, title: 'a' }, { score: 9, title: 'b' }, { score: 1, title: 'c' }];
  const out = sortDirections(rows, 'score');
  assert.deepEqual(out.map(r => r.title), ['b', 'a', 'c']);
});

test('sortDirections: sorts by recency ascending when dir=asc', () => {
  const rows = [{ recency: 2022, title: 'a' }, { recency: 2018, title: 'b' }, { recency: 2024, title: 'c' }];
  const out = sortDirections(rows, 'recency', 'asc');
  assert.deepEqual(out.map(r => r.title), ['b', 'a', 'c']);
});

test('sortDirections: unknown column is a stable no-op copy', () => {
  const rows = [{ score: 1, title: 'first' }, { score: 99, title: 'second' }];
  const out = sortDirections(rows, 'not_a_column');
  assert.deepEqual(out.map(r => r.title), ['first', 'second']);
});

test('sortDirections: nulls sort last, stable ties keep original order', () => {
  const rows = [
    { score: null, title: 'no-score-1' },
    { score: 5, title: 'has-score' },
    { score: null, title: 'no-score-2' },
  ];
  const out = sortDirections(rows, 'score');
  assert.deepEqual(out.map(r => r.title), ['has-score', 'no-score-1', 'no-score-2']);
});

test('sortDirections: never throws and never mutates the input array', () => {
  const rows = [{ score: 1 }, { score: 2 }];
  const copy = rows.slice();
  assert.doesNotThrow(() => sortDirections(null, 'score'));
  sortDirections(rows, 'score');
  assert.deepEqual(rows, copy);
});
