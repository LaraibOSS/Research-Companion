/**
 * converse.test.mjs — W3-F4 pure-function tests.
 *
 * Tests:
 *   - deriveContext: all route/event cases
 *   - nextThreadState: all state machine transitions
 *   - threadKey: derivation from context
 *   - answerHtml re-export identity: assert ask.js export === answerHtml.js export
 *
 * Run from repo root:
 *   node --test tests/js/converse.test.mjs
 * (also included in the full documented node command in test_lab_static.py)
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, '..', '..');
const jsRoot = path.join(repoRoot, 'research_companion', 'lab', 'static', 'js');

// Import the pure helpers from conversePanel.js
const { deriveContext, nextThreadState, threadKey } = await import(
  pathToFileURL(path.join(jsRoot, 'components', 'conversePanel.js')).href
);

// Import renderAnswerHtml from both ask.js and answerHtml.js for identity check
const { renderAnswerHtml: renderFromAsk } = await import(
  pathToFileURL(path.join(jsRoot, 'views', 'ask.js')).href
);
const { renderAnswerHtml: renderFromAnswerHtml } = await import(
  pathToFileURL(path.join(jsRoot, 'answerHtml.js')).href
);

// ---------------------------------------------------------------------------
// deriveContext — route-based
// ---------------------------------------------------------------------------

test('deriveContext /draft -> alignment', () => {
  const ctx = deriveContext('/draft');
  assert.equal(ctx.type, 'alignment');
  assert.equal(ctx.id, null);
});

test('deriveContext /library without paperId -> review', () => {
  const ctx = deriveContext('/library');
  assert.equal(ctx.type, 'review');
  assert.equal(ctx.id, null);
});

test('deriveContext /ask -> review (default)', () => {
  const ctx = deriveContext('/ask');
  assert.equal(ctx.type, 'review');
  assert.equal(ctx.id, null);
});

test('deriveContext /graph -> review (default)', () => {
  const ctx = deriveContext('/graph');
  assert.equal(ctx.type, 'review');
  assert.equal(ctx.id, null);
});

test('deriveContext unknown route -> review (default)', () => {
  const ctx = deriveContext('/timeline');
  assert.equal(ctx.type, 'review');
  assert.equal(ctx.id, null);
});

// ---------------------------------------------------------------------------
// deriveContext — paperId (library drawer open)
// ---------------------------------------------------------------------------

test('deriveContext with paperId -> {type:paper, id}', () => {
  const ctx = deriveContext('/library', { paperId: 'abc123' });
  assert.equal(ctx.type, 'paper');
  assert.equal(ctx.id, 'abc123');
});

test('deriveContext /draft with paperId -> paper wins', () => {
  const ctx = deriveContext('/draft', { paperId: 'xyz' });
  assert.equal(ctx.type, 'paper');
  assert.equal(ctx.id, 'xyz');
});

// ---------------------------------------------------------------------------
// deriveContext — rc:discuss event (highest priority)
// ---------------------------------------------------------------------------

test('deriveContext rc:discuss type suggestions -> suggestions', () => {
  const ctx = deriveContext('/library', {
    rcDiscussEvent: { type: 'suggestions' },
  });
  assert.equal(ctx.type, 'suggestions');
  assert.equal(ctx.id, null);
});

test('deriveContext rc:discuss type gaps with id -> gaps', () => {
  const ctx = deriveContext('/timeline', {
    rcDiscussEvent: { type: 'gaps', id: 'gap-42' },
  });
  assert.equal(ctx.type, 'gaps');
  assert.equal(ctx.id, 'gap-42');
});

test('deriveContext rc:discuss overrides paperId and route', () => {
  const ctx = deriveContext('/draft', {
    paperId: 'should-be-ignored',
    rcDiscussEvent: { type: 'alignment', id: 'draft-1' },
  });
  assert.equal(ctx.type, 'alignment');
  assert.equal(ctx.id, 'draft-1');
});

test('deriveContext rc:discuss with no type falls back to review', () => {
  const ctx = deriveContext('/ask', {
    rcDiscussEvent: { type: '' },
  });
  assert.equal(ctx.type, 'review');
});

// ---------------------------------------------------------------------------
// nextThreadState — state machine
// ---------------------------------------------------------------------------

test('nextThreadState idle + send -> sending', () => {
  assert.equal(nextThreadState('idle', 'send'), 'sending');
});

test('nextThreadState idle + other event -> idle', () => {
  assert.equal(nextThreadState('idle', 'success'), 'idle');
  assert.equal(nextThreadState('idle', 'error'), 'idle');
  assert.equal(nextThreadState('idle', 'retry'), 'idle');
});

test('nextThreadState sending + success -> idle', () => {
  assert.equal(nextThreadState('sending', 'success'), 'idle');
});

test('nextThreadState sending + error -> error', () => {
  assert.equal(nextThreadState('sending', 'error'), 'error');
});

test('nextThreadState sending + other -> sending', () => {
  assert.equal(nextThreadState('sending', 'retry'), 'sending');
  assert.equal(nextThreadState('sending', 'send'), 'sending');
});

test('nextThreadState error + retry -> sending', () => {
  assert.equal(nextThreadState('error', 'retry'), 'sending');
});

test('nextThreadState error + send -> sending', () => {
  assert.equal(nextThreadState('error', 'send'), 'sending');
});

test('nextThreadState error + other -> error', () => {
  assert.equal(nextThreadState('error', 'success'), 'error');
});

test('nextThreadState unknown state -> idle', () => {
  assert.equal(nextThreadState('unknown', 'send'), 'idle');
});

// ---------------------------------------------------------------------------
// threadKey — derivation
// ---------------------------------------------------------------------------

test('threadKey {type:review, id:null} -> "review:"', () => {
  assert.equal(threadKey({ type: 'review', id: null }), 'review:');
});

test('threadKey {type:paper, id:"abc"} -> "paper:abc"', () => {
  assert.equal(threadKey({ type: 'paper', id: 'abc' }), 'paper:abc');
});

test('threadKey {type:alignment, id:null} -> "alignment:"', () => {
  assert.equal(threadKey({ type: 'alignment', id: null }), 'alignment:');
});

test('threadKey {type:suggestions, id:"sug-1"} -> "suggestions:sug-1"', () => {
  assert.equal(threadKey({ type: 'suggestions', id: 'sug-1' }), 'suggestions:sug-1');
});

test('threadKey {type:gaps, id:"gap-x"} -> "gaps:gap-x"', () => {
  assert.equal(threadKey({ type: 'gaps', id: 'gap-x' }), 'gaps:gap-x');
});

// ---------------------------------------------------------------------------
// answerHtml re-export identity
// answerHtml.js and ask.js must export the exact same renderAnswerHtml function
// ---------------------------------------------------------------------------

test('ask.js renderAnswerHtml is the same function as answerHtml.js export', () => {
  assert.strictEqual(renderFromAsk, renderFromAnswerHtml,
    'ask.js must re-export the same renderAnswerHtml from answerHtml.js');
});
