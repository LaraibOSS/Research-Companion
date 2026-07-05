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
const { KIND_COLORS, KIND_SHAPES, KIND_SIZES, nodeToVis, edgeToVis } = await import(
  pathToFileURL(path.join(repoRoot, 'research_companion', 'lab', 'static', 'js', 'graph', 'mapping.js')).href
);

// --- KIND_COLORS (premium desaturated palette) ---
const expectedColors = {
  paper:   '#6c8cff',
  concept: '#3fb6a8',
  method:  '#d9a13d',
  dataset: '#a78bfa',
  claim:   '#7d8590',
  result:  '#e5697f',
};

for (const [kind, color] of Object.entries(expectedColors)) {
  test(`KIND_COLORS.${kind} === ${color}`, () => {
    assert.equal(KIND_COLORS[kind], color);
  });
}

// --- KIND_SHAPES: papers are cards, all entities are dots ---
test('KIND_SHAPES.paper === box', () => {
  assert.equal(KIND_SHAPES.paper, 'box');
});

for (const kind of ['concept', 'method', 'dataset', 'claim', 'result']) {
  test(`KIND_SHAPES.${kind} === dot`, () => {
    assert.equal(KIND_SHAPES[kind], 'dot');
  });
}

// --- KIND_SIZES: entities differentiated by size ---
test('KIND_SIZES orders concept >= method/dataset > result > claim', () => {
  assert.ok(KIND_SIZES.concept >= KIND_SIZES.method);
  assert.ok(KIND_SIZES.method > KIND_SIZES.claim);
  assert.ok(KIND_SIZES.result > KIND_SIZES.claim);
});

// --- nodeToVis ---
test('nodeToVis maps paper node correctly', () => {
  const node = { id: 'p1', kind: 'paper', label: 'My Paper', attrs: {} };
  const vis = nodeToVis(node);
  assert.equal(vis.id, 'p1');
  assert.equal(vis.label, 'My Paper');
  assert.equal(vis.color, '#6c8cff');
  assert.equal(vis.shape, 'box');
  assert.equal(vis.font.color, '#e6edf3');
});

test('nodeToVis paper with strength gets a band-colored border', () => {
  const node = { id: 'p2', kind: 'paper', label: 'Strong Paper', attrs: {},
                 strength: { band: 'strong', color: '#3fb950' } };
  const vis = nodeToVis(node);
  assert.equal(vis.color.background, '#6c8cff');
  assert.equal(vis.color.border, '#3fb950');
  assert.equal(vis.borderWidth, 2);
});

test('nodeToVis maps concept node correctly', () => {
  const node = { id: 'c1', kind: 'concept', label: 'Neural Network', attrs: {} };
  const vis = nodeToVis(node);
  assert.equal(vis.color, '#3fb6a8');
  assert.equal(vis.shape, 'dot');
  assert.equal(vis.size, KIND_SIZES.concept);
  assert.equal(vis.font.color, '#9aa4b2');
});

test('nodeToVis truncates long entity labels but keeps full text in title', () => {
  const long = 'A very long claim label that keeps going well past the truncation threshold for dots';
  const vis = nodeToVis({ id: 'cl1', kind: 'claim', label: long, attrs: {} });
  assert.ok(vis.label.length <= 42);
  assert.ok(vis.label.endsWith('…'));
  assert.equal(vis.title, long);
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

// --- edgeToVis: quiet edges, no always-on labels ---
test('edgeToVis maps edge with relation on title, never a text label', () => {
  const edge = { from: 'p1', to: 'c1', relation: 'contains', weight: 2 };
  const vis = edgeToVis(edge);
  assert.equal(vis.from, 'p1');
  assert.equal(vis.to, 'c1');
  assert.equal(vis.title, 'contains');
  assert.equal(vis.relation, 'contains');
  assert.equal(vis.label, undefined);
});

test('edgeToVis dashes co_mentioned edges only', () => {
  assert.deepEqual(edgeToVis({ from: 'a', to: 'b', relation: 'co_mentioned' }).dashes, [4, 4]);
  assert.equal(edgeToVis({ from: 'a', to: 'b', relation: 'contains' }).dashes, false);
});

test('edgeToVis handles missing relation gracefully', () => {
  const edge = { from: 'a', to: 'b' };
  const vis = edgeToVis(edge);
  assert.equal(vis.from, 'a');
  assert.equal(vis.to, 'b');
  assert.equal(vis.title, '');
});
