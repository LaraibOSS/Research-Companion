/**
 * addReceipt.test.mjs — the post-Add receipt model
 * (research_companion/lab/static/js/addReceipt.js).
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, '..', '..');
const { addReceiptModel, MANUAL_ADD_DISCLAIMER } = await import(pathToFileURL(
  path.join(repoRoot, 'research_companion', 'lab', 'static', 'js', 'addReceipt.js')).href);

test('names the research the papers went into', () => {
  const m = addReceiptModel({ queued: 12, skipped: 0, failed: 0, researchName: 'Memory Agents' });
  assert.match(m.title, /Adding 12 papers/);
  assert.match(m.title, /Memory Agents/);
  assert.match(m.detail, /background/);
  assert.equal(m.hasContent, true);
});

test('singular/plural and the already-present case', () => {
  assert.match(addReceiptModel({ queued: 1 }).title, /Adding 1 paper\b/);
  const dup = addReceiptModel({ queued: 0, skipped: 5 });
  assert.equal(dup.title, 'Nothing to add');
  assert.match(dup.detail, /5 were already in this research/);
  const one = addReceiptModel({ queued: 0, skipped: 1 });
  assert.match(one.detail, /1 was already in this research/);
});

test('reports add failures alongside successes', () => {
  const m = addReceiptModel({ queued: 3, skipped: 1, failed: 2 });
  assert.match(m.detail, /3|background/);
  assert.match(m.detail, /1 was already/);
  assert.match(m.detail, /2 could not be added/);
});

test('always carries the manual-download disclaimer', () => {
  const m = addReceiptModel({ queued: 1 });
  assert.equal(m.disclaimer, MANUAL_ADD_DISCLAIMER);
  assert.match(m.disclaimer, /manually/i);
  assert.match(m.disclaimer, /failed/i);
});

test('never throws; empty input has no content', () => {
  assert.doesNotThrow(() => addReceiptModel(undefined));
  assert.doesNotThrow(() => addReceiptModel(null));
  assert.doesNotThrow(() => addReceiptModel('x'));
  assert.equal(addReceiptModel({}).hasContent, false);
  assert.equal(addReceiptModel({ queued: -5 }).hasContent, false);
});
