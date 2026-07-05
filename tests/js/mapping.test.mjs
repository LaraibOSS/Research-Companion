/**
 * mapping.test.mjs — Table-driven tests for graph/mapping.js.
 * Run from repo root: node --test tests/js/
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, '..', '..');
const { KIND_COLORS, KIND_SHAPES, nodeToVis, edgeToVis } = await import(
  pathToFileURL(path.join(repoRoot, 'research_companion', 'lab', 'static', 'js', 'graph', 'mapping.js')).href
);

// --- KIND_COLORS ---
const expectedColors = {
  paper:   '#2b7cff',
  concept: '#3ec46d',
  method:  '#ff8a3d',
  dataset: '#9b59ff',
  claim:   '#9aa0a6',
  result:  '#e74c3c',
};

for (const [kind, color] of Object.entries(expectedColors)) {
  test(`KIND_COLORS.${kind} === ${color}`, () => {
    assert.equal(KIND_COLORS[kind], color);
  });
}

// --- KIND_SHAPES ---
const expectedShapes = {
  paper:   'box',
  concept: 'dot',
  method:  'triangle',
  dataset: 'diamond',
  claim:   'ellipse',
  result:  'star',
};

for (const [kind, shape] of Object.entries(expectedShapes)) {
  test(`KIND_SHAPES.${kind} === ${shape}`, () => {
    assert.equal(KIND_SHAPES[kind], shape);
  });
}

// --- nodeToVis ---
test('nodeToVis maps paper node correctly', () => {
  const node = { id: 'p1', kind: 'paper', label: 'My Paper', attrs: {} };
  const vis = nodeToVis(node);
  assert.equal(vis.id, 'p1');
  assert.equal(vis.label, 'My Paper');
  assert.equal(vis.color, '#2b7cff');
  assert.equal(vis.shape, 'box');
});

test('nodeToVis maps concept node correctly', () => {
  const node = { id: 'c1', kind: 'concept', label: 'Neural Network', attrs: {} };
  const vis = nodeToVis(node);
  assert.equal(vis.color, '#3ec46d');
  assert.equal(vis.shape, 'dot');
});

test('nodeToVis uses fallback for unknown kind', () => {
  const node = { id: 'x1', kind: 'unknown_kind', label: 'X', attrs: {} };
  const vis = nodeToVis(node);
  assert.ok(vis.color, 'should have a color fallback');
  assert.ok(vis.shape, 'should have a shape fallback');
});

test('nodeToVis preserves id and label', () => {
  const node = { id: 'my-id', kind: 'result', label: 'My Result', attrs: {} };
  const vis = nodeToVis(node);
  assert.equal(vis.id, 'my-id');
  assert.equal(vis.label, 'My Result');
});

// --- edgeToVis ---
test('edgeToVis maps edge correctly', () => {
  const edge = { from: 'p1', to: 'c1', relation: 'contains', weight: 2 };
  const vis = edgeToVis(edge);
  assert.equal(vis.from, 'p1');
  assert.equal(vis.to, 'c1');
  assert.equal(vis.label, 'contains');
});

test('edgeToVis handles missing relation gracefully', () => {
  const edge = { from: 'a', to: 'b' };
  const vis = edgeToVis(edge);
  assert.equal(vis.from, 'a');
  assert.equal(vis.to, 'b');
  assert.ok(typeof vis.label === 'string');
});
