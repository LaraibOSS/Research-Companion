import test from 'node:test';
import assert from 'node:assert/strict';
import { simplifiedModel, simplifiedDisplayState } from '../../research_companion/lab/static/js/readerSimplifiedHelpers.js';

const EXTRACTION = {
  concepts: [{ name: 'adaptive computation time', definition: 'lets RNNs adjust steps per input.', section: 's1' }],
  methods: [{ name: 'ACT', description: 'learns the number of updates per input.', section: 's1' }],
  datasets: [{ name: 'hutter prize wikipedia', description: 'raw unicode text.', section: 's4.5' }],
  claims: [{ text: 'ACT adapts computation to task complexity.', section: 's1' }],
  results: [{ metric: 'sequence error rate', value: 'below 5%', dataset: 'parity task', section: 's4.1' }],
  related_work: ['Bahdanau et al. 2014'],
};

test('simplifiedModel groups in fixed order with section ids', () => {
  const m = simplifiedModel(EXTRACTION);
  assert.deepEqual(m.groups.map(g => g.title), [
    'What this paper is about', 'Key claims', 'How they did it', 'What they found']);
  assert.equal(m.groups[0].bullets[0].text,
    'adaptive computation time — lets RNNs adjust steps per input.');
  assert.equal(m.groups[0].bullets[0].sectionId, 's1');
  assert.equal(m.groups[2].bullets[1].text, 'Dataset: hutter prize wikipedia — raw unicode text.');
  assert.equal(m.groups[3].bullets[0].text, 'sequence error rate: below 5% (parity task)');
});

test('simplifiedModel omits empty groups, ignores related_work, never throws', () => {
  assert.deepEqual(simplifiedModel(null), { groups: [] });
  assert.deepEqual(simplifiedModel({ nonsense: 1 }), { groups: [] });
  const m = simplifiedModel({ claims: [{ text: 'only claim' }] });
  assert.deepEqual(m.groups.map(g => g.title), ['Key claims']);
  assert.equal(m.groups[0].bullets[0].sectionId, null);
});

test('simplifiedModel result without dataset omits the parenthetical', () => {
  const m = simplifiedModel({ results: [{ metric: 'accuracy', value: '91%' }] });
  assert.equal(m.groups[0].bullets[0].text, 'accuracy: 91%');
});

test('simplifiedDisplayState matrix', () => {
  assert.deepEqual(simplifiedDisplayState({ hasExtraction: true, rewrite: null, providerConfigured: true }),
    { view: 'auto', showButton: true });
  assert.deepEqual(simplifiedDisplayState({ hasExtraction: true, rewrite: { groups: [] }, providerConfigured: true }),
    { view: 'rewrite', showButton: true });
  assert.deepEqual(simplifiedDisplayState({ hasExtraction: false, rewrite: null, providerConfigured: true }),
    { view: 'empty', showButton: false });
  assert.deepEqual(simplifiedDisplayState({ hasExtraction: true, rewrite: null, providerConfigured: false }),
    { view: 'auto', showButton: false });
});
