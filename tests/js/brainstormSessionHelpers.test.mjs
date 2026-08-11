/**
 * brainstormSessionHelpers.test.mjs — pure (de)serialization for the persisted
 * Brainstorm session (research_companion/lab/static/js/brainstormSessionHelpers.js).
 *
 * Run from repo root:
 *   node --test tests/js/brainstormSessionHelpers.test.mjs
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, '..', '..');

const { serializeSession, hydrateSession, sessionHasContent, BRAINSTORM_SESSION_VERSION } =
  await import(pathToFileURL(path.join(
    repoRoot, 'research_companion', 'lab', 'static', 'js', 'brainstormSessionHelpers.js')).href);

const fullState = {
  topic: 'graph retrieval for code',
  queriesUsed: ['graph retrieval', 'code search'],
  expandedFlag: true,
  rawResults: [{ paper_id: 'arxiv:1', title: 'A' }],
  rawDirections: [{ direction_id: 'dir_abc', title: 'D1' }],
  hasSearched: true,
  directionsHasGenerated: true,
  novelty: { dir_abc: { verdict: 'novel', score: 0.7 } },
  libraryIds: ['arxiv:1', 'doi:10.x'],
};

test('serializeSession: stamps version and preserves fields', () => {
  const p = serializeSession(fullState);
  assert.equal(p.v, BRAINSTORM_SESSION_VERSION);
  assert.equal(p.topic, 'graph retrieval for code');
  assert.deepEqual(p.libraryIds, ['arxiv:1', 'doi:10.x']);
  assert.deepEqual(p.novelty, { dir_abc: { verdict: 'novel', score: 0.7 } });
  assert.equal(p.brief, null);
});

test('serialize -> hydrate is a lossless round-trip for the persisted slice', () => {
  const back = hydrateSession(serializeSession(fullState));
  assert.equal(back.topic, fullState.topic);
  assert.equal(back.expandedFlag, true);
  assert.deepEqual(back.rawResults, fullState.rawResults);
  assert.deepEqual(back.rawDirections, fullState.rawDirections);
  assert.equal(back.hasSearched, true);
  assert.equal(back.directionsHasGenerated, true);
  assert.deepEqual(back.novelty, fullState.novelty);
  assert.deepEqual(back.libraryIds, fullState.libraryIds);
});

test('hydrateSession: tolerant of null / missing / old-shaped payloads', () => {
  assert.doesNotThrow(() => hydrateSession(null));
  assert.doesNotThrow(() => hydrateSession(undefined));
  assert.doesNotThrow(() => hydrateSession(5));
  const empty = hydrateSession(null);
  assert.equal(empty.topic, '');
  assert.deepEqual(empty.rawResults, []);
  assert.deepEqual(empty.novelty, {});
  assert.equal(empty.brief, null);
  // partial payload from an older client
  const partial = hydrateSession({ topic: 'x', rawResults: [{ paper_id: 'p' }] });
  assert.equal(partial.topic, 'x');
  assert.equal(partial.rawResults.length, 1);
  assert.equal(partial.directionsHasGenerated, false);
});

test('serializeSession: coerces wrong-typed fields safely', () => {
  const p = serializeSession({ topic: 42, rawResults: 'nope', novelty: [1, 2], libraryIds: null });
  assert.equal(p.topic, '');
  assert.deepEqual(p.rawResults, []);
  assert.deepEqual(p.novelty, {});
  assert.deepEqual(p.libraryIds, []);
});

test('sessionHasContent: true only when something is worth restoring', () => {
  assert.equal(sessionHasContent(null), false);
  assert.equal(sessionHasContent({ v: 1, topic: '', rawResults: [], rawDirections: [], novelty: {} }), false);
  assert.equal(sessionHasContent({ topic: 'x' }), true);
  assert.equal(sessionHasContent({ rawResults: [{ paper_id: 'p' }] }), true);
  assert.equal(sessionHasContent({ brief: { sections: [] } }), true);
});
