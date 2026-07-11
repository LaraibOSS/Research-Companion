/**
 * researchNudgeHelpers.test.mjs — Unit tests for researchNudgeHelpers.js.
 * Run: node --test tests/js/researchNudgeHelpers.test.mjs
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, '..', '..');
const { shouldSuggestNewResearch } = await import(
  pathToFileURL(path.join(repoRoot, 'research_companion', 'lab', 'static', 'js', 'researchNudgeHelpers.js')).href
);

test('no nudge for a fresh empty research', () => {
  assert.equal(shouldSuggestNewResearch({ papers: new Map(), draftId: null }), false);
});

test('nudge when the research already has papers (Map)', () => {
  const papers = new Map([['a', {}], ['b', {}]]);
  assert.equal(shouldSuggestNewResearch({ papers, draftId: null }), true);
});

test('nudge when the research already has papers (Array)', () => {
  assert.equal(shouldSuggestNewResearch({ papers: [{}], draftId: null }), true);
});

test('nudge when the research already has a draft', () => {
  assert.equal(shouldSuggestNewResearch({ papers: new Map(), draftId: 'local:abc' }), true);
});

test('defensive: null/undefined state does not nudge', () => {
  assert.equal(shouldSuggestNewResearch(null), false);
  assert.equal(shouldSuggestNewResearch(undefined), false);
  assert.equal(shouldSuggestNewResearch({}), false);
});
