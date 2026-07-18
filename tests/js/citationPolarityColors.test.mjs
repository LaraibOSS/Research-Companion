// tests/js/citationPolarityColors.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { edgeToVis, CITATION_POLARITY_COLORS } from '../../research_companion/lab/static/js/graph/mapping.js';

test('cites edge colored by polarity', () => {
  const vis = edgeToVis({ from: 'a', to: 'b', relation: 'cites', polarity: 'contrast' });
  assert.equal(vis.color.color, CITATION_POLARITY_COLORS.contrast);
});

test('untyped cites keeps the default color', () => {
  const vis = edgeToVis({ from: 'a', to: 'b', relation: 'cites' });
  assert.equal(vis.color.color, 'rgba(110,118,129,0.35)');
});

test('all five polarities have colors', () => {
  for (const p of ['based_on', 'support', 'contrast', 'refutation', 'mention']) {
    assert.ok(CITATION_POLARITY_COLORS[p]);
  }
});
