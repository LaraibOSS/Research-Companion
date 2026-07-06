/**
 * viewsHelpers.test.mjs — Table-driven tests for the W3-F6 pure helpers:
 *   truncateName, viewRowModel, canSave (js/viewsHelpers.js)
 *
 * Run from repo root:
 *   node --test tests/js/viewsHelpers.test.mjs
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot  = path.resolve(__dirname, '..', '..');

const { truncateName, viewRowModel, canSave } = await import(
  pathToFileURL(path.join(repoRoot, 'research_companion', 'lab', 'static', 'js', 'viewsHelpers.js')).href
);

// ---------------------------------------------------------------------------
// truncateName
// ---------------------------------------------------------------------------

test('truncateName: short string unchanged', () => {
  assert.equal(truncateName('hello', 60), 'hello');
});

test('truncateName: exactly max length unchanged', () => {
  const s = 'a'.repeat(60);
  assert.equal(truncateName(s, 60), s);
});

test('truncateName: longer than max truncates with ellipsis', () => {
  const s = 'a'.repeat(61);
  const result = truncateName(s, 60);
  assert.ok(result.endsWith('…'), `should end with ellipsis: ${result}`);
  assert.ok(result.length <= 61, `should not exceed max+1: ${result.length}`);
});

test('truncateName: breaks on word boundary', () => {
  const q = 'What are the main contributions of transformer models in NLP research areas?';
  const result = truncateName(q, 60);
  assert.ok(result.endsWith('…'), `should end with ellipsis: ${result}`);
  // Should not cut inside a word — the last char before ellipsis should not be mid-word
  const withoutEllipsis = result.slice(0, -1);
  const lastChar = withoutEllipsis[withoutEllipsis.length - 1];
  assert.notEqual(lastChar, ' ', 'should trim trailing space');
});

test('truncateName: long word with no space falls back to hard cut', () => {
  const s = 'x'.repeat(80);
  const result = truncateName(s, 60);
  assert.ok(result.endsWith('…'), `should end with ellipsis: ${result}`);
  assert.equal(result.length, 61); // 60 chars + ellipsis
});

test('truncateName: default max is 60', () => {
  const q = 'a'.repeat(65);
  const result = truncateName(q);
  assert.ok(result.endsWith('…'));
  assert.ok(result.length <= 61);
});

test('truncateName: null/undefined coerced to empty string', () => {
  assert.equal(truncateName(null), '');
  assert.equal(truncateName(undefined), '');
});

test('truncateName: word boundary example', () => {
  const q = 'What are the main contributions';
  const result = truncateName(q, 20);
  // "What are the main" = 17 chars (with "contributions" would be 31)
  assert.ok(result.endsWith('…'), `should end with ellipsis: ${result}`);
  assert.ok(!result.includes('contributions'), 'should truncate before "contributions"');
});

// ---------------------------------------------------------------------------
// viewRowModel
// ---------------------------------------------------------------------------

const SAMPLE_VIEWS = [
  { view_id: 'v1', name: 'Transformers in NLP', node_ids: ['n1', 'n2', 'n3'], pinned: true },
  { view_id: 'v2', name: 'Vision models',       node_ids: ['n4', 'n5'],       pinned: false },
  { view_id: 'v3', name: 'Empty view',           node_ids: [],                 pinned: false },
];

test('viewRowModel: returns correct number of rows', () => {
  const rows = viewRowModel(SAMPLE_VIEWS, null);
  assert.equal(rows.length, 3);
});

test('viewRowModel: maps id, label, count, pinned, active correctly', () => {
  const rows = viewRowModel(SAMPLE_VIEWS, 'v1');
  assert.equal(rows[0].id, 'v1');
  assert.equal(rows[0].label, 'Transformers in NLP');
  assert.equal(rows[0].count, 3);
  assert.equal(rows[0].pinned, true);
  assert.equal(rows[0].active, true);
});

test('viewRowModel: non-active rows have active=false', () => {
  const rows = viewRowModel(SAMPLE_VIEWS, 'v1');
  assert.equal(rows[1].active, false);
  assert.equal(rows[2].active, false);
});

test('viewRowModel: count is 0 for empty node_ids', () => {
  const rows = viewRowModel(SAMPLE_VIEWS, null);
  assert.equal(rows[2].count, 0);
});

test('viewRowModel: activeId=null means no row is active', () => {
  const rows = viewRowModel(SAMPLE_VIEWS, null);
  assert.ok(rows.every(r => !r.active));
});

test('viewRowModel: missing node_ids treated as count 0', () => {
  const rows = viewRowModel([{ view_id: 'x', name: 'X', pinned: false }], null);
  assert.equal(rows[0].count, 0);
});

test('viewRowModel: non-array input returns empty array', () => {
  assert.deepEqual(viewRowModel(null, null), []);
  assert.deepEqual(viewRowModel(undefined, null), []);
  assert.deepEqual(viewRowModel('oops', null), []);
});

test('viewRowModel: missing view_id becomes empty string', () => {
  const rows = viewRowModel([{ name: 'No ID', node_ids: [] }], null);
  assert.equal(rows[0].id, '');
});

// ---------------------------------------------------------------------------
// canSave
// ---------------------------------------------------------------------------

test('canSave: true when node_ids is a non-empty array', () => {
  assert.equal(canSave({ node_ids: ['n1', 'n2'] }), true);
});

test('canSave: false when node_ids is empty', () => {
  assert.equal(canSave({ node_ids: [] }), false);
});

test('canSave: false when node_ids is missing', () => {
  assert.equal(canSave({ paper_ids: ['p1'] }), false);
});

test('canSave: false when grounding is null', () => {
  assert.equal(canSave(null), false);
});

test('canSave: false when grounding is undefined', () => {
  assert.equal(canSave(undefined), false);
});

test('canSave: false when node_ids is not an array', () => {
  assert.equal(canSave({ node_ids: 'n1' }), false);
  assert.equal(canSave({ node_ids: 1 }), false);
});

test('canSave: true with single node', () => {
  assert.equal(canSave({ node_ids: ['single'] }), true);
});
