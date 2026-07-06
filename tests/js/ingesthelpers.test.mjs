/**
 * ingesthelpers.test.mjs — TDD tests for classifyIngestError pure helper.
 * Run from repo root: node --test tests/js/
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot  = path.resolve(__dirname, '..', '..');

const { classifyIngestError, validateUploadFile, MAX_UPLOAD_BYTES } = await import(
  pathToFileURL(path.join(repoRoot, 'research_companion', 'lab', 'static', 'js', 'components', 'ingestHelpers.js')).href
);

// ---------------------------------------------------------------------------
// classifyIngestError
// ---------------------------------------------------------------------------

test('classifyIngestError: status 409 -> conflict', () => {
  const err = Object.assign(new Error('An ingest job is already running'), { status: 409 });
  assert.equal(classifyIngestError(err), 'conflict');
});

test('classifyIngestError: status 400 -> inline', () => {
  const err = Object.assign(new Error('Folder not found'), { status: 400 });
  assert.equal(classifyIngestError(err), 'inline');
});

test('classifyIngestError: status 500 -> inline', () => {
  const err = Object.assign(new Error('Internal server error'), { status: 500 });
  assert.equal(classifyIngestError(err), 'inline');
});

test('classifyIngestError: no status property -> inline', () => {
  const err = new Error('Network error');
  assert.equal(classifyIngestError(err), 'inline');
});

test('classifyIngestError: old-style message-only 409 text -> inline (not conflict)', () => {
  // Guard: old message.includes('409') approach would have matched this incorrectly
  // The new approach requires err.status === 409; message content is irrelevant
  const err = new Error('409 conflict found');
  // err.status is undefined -> inline
  assert.equal(classifyIngestError(err), 'inline');
});

// ---------------------------------------------------------------------------
// validateUploadFile (v0.3.1 upload tab)
// ---------------------------------------------------------------------------

test('validateUploadFile: accepts a normal pdf', () => {
  assert.deepEqual(validateUploadFile('my draft.pdf', 1024), { ok: true });
});

test('validateUploadFile: extension check is case-insensitive', () => {
  assert.deepEqual(validateUploadFile('PAPER.PDF', 1024), { ok: true });
});

test('validateUploadFile: rejects non-pdf extensions', () => {
  const r = validateUploadFile('notes.docx', 1024);
  assert.equal(r.ok, false);
  assert.equal(r.reason, 'not-pdf');
  assert.ok(r.message);
});

test('validateUploadFile: rejects missing name', () => {
  assert.equal(validateUploadFile('', 1024).reason, 'not-pdf');
  assert.equal(validateUploadFile(undefined, 1024).reason, 'not-pdf');
});

test('validateUploadFile: rejects empty file', () => {
  const r = validateUploadFile('a.pdf', 0);
  assert.equal(r.ok, false);
  assert.equal(r.reason, 'empty');
});

test('validateUploadFile: rejects oversize file', () => {
  const r = validateUploadFile('a.pdf', MAX_UPLOAD_BYTES + 1);
  assert.equal(r.ok, false);
  assert.equal(r.reason, 'too-large');
});

test('validateUploadFile: exactly at the cap is fine', () => {
  assert.deepEqual(validateUploadFile('a.pdf', MAX_UPLOAD_BYTES), { ok: true });
});
