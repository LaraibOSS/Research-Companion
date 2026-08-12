/**
 * helpContent.test.mjs — per-page help copy registry
 * (research_companion/lab/static/js/helpContent.js).
 *
 * Run from repo root:
 *   node --test tests/js/helpContent.test.mjs
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, '..', '..');

const { helpFor, helpViewIds, AI_DISCLAIMER, DETERMINISTIC_NOTE } = await import(
  pathToFileURL(path.join(repoRoot, 'research_companion', 'lab', 'static', 'js', 'helpContent.js')).href
);

// Every tab reachable from the nav must have real help copy.
const REQUIRED = [
  'home', 'brainstorm', 'library', 'graph', 'draft', 'timeline',
  'gaps', 'report', 'ask', 'compare', 'citations', 'notes', 'researches',
];

test('every navigable view has a dedicated help entry', () => {
  const ids = helpViewIds();
  for (const id of REQUIRED) {
    assert.ok(ids.includes(id), `missing help entry for "${id}"`);
  }
});

test('each entry has substantive what/basedOn copy', () => {
  for (const id of REQUIRED) {
    const h = helpFor(id);
    assert.ok(h.title.length > 0, `${id}: empty title`);
    assert.ok(h.what.length > 60, `${id}: "what" too short to be useful`);
    assert.ok(h.basedOn.length > 20, `${id}: "basedOn" too short`);
    assert.equal(typeof h.aiUsed, 'boolean');
  }
});

test('AI pages carry the verification disclaimer; deterministic pages do not', () => {
  // Brainstorm/draft/report/ask are model-driven.
  for (const id of ['brainstorm', 'draft', 'report', 'ask', 'gaps']) {
    const h = helpFor(id);
    assert.equal(h.aiUsed, true, `${id} should be flagged aiUsed`);
    assert.equal(h.disclaimer, AI_DISCLAIMER);
    assert.match(h.disclaimer, /verify/i);
  }
  // Library/timeline/citations/notes are computed, not generated.
  for (const id of ['library', 'timeline', 'citations', 'notes', 'researches']) {
    const h = helpFor(id);
    assert.equal(h.aiUsed, false, `${id} should not be flagged aiUsed`);
    assert.equal(h.disclaimer, DETERMINISTIC_NOTE);
  }
});

test('helpFor accepts routes, bare ids, and odd casing', () => {
  assert.equal(helpFor('/graph').title, helpFor('graph').title);
  assert.equal(helpFor('#/graph').title, helpFor('graph').title);
  assert.equal(helpFor('GRAPH').title, helpFor('graph').title);
});

test('helpFor never throws and falls back for unknown ids', () => {
  assert.doesNotThrow(() => helpFor(undefined));
  assert.doesNotThrow(() => helpFor(null));
  assert.doesNotThrow(() => helpFor(42));
  const fallback = helpFor('/does-not-exist');
  assert.ok(fallback.title.length > 0);
  assert.ok(fallback.what.length > 0);
  assert.ok(fallback.disclaimer.length > 0);
});

test('timeline help explains how to read the page (the confusing tab)', () => {
  const h = helpFor('timeline');
  assert.match(h.what, /year/i);
  // it must tell the user what they should get out of it
  assert.ok(h.what.length > 150, 'timeline needs a fuller explanation');
  // and explain why some papers are missing
  assert.match(h.basedOn, /year/i);
});
