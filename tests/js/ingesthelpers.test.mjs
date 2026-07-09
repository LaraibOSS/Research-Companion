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

const { classifyIngestError, validateUploadFile, MAX_UPLOAD_BYTES, scanSummary, scanRows, manifestItemView } = await import(
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

// ---------------------------------------------------------------------------
// scanSummary (folder scan-preview)
// ---------------------------------------------------------------------------

test('scanSummary: counts new vs already-in-library over the scan files array', () => {
  const files = [
    { name: 'a.pdf', already_in_library: false },
    { name: 'b.pdf', already_in_library: false },
    { name: 'c.pdf', already_in_library: true },
  ];
  assert.deepEqual(scanSummary(files), { total: 3, newCount: 2, alreadyCount: 1 });
});

test('scanSummary: all new', () => {
  const files = [
    { name: 'a.pdf', already_in_library: false },
    { name: 'b.pdf', already_in_library: false },
  ];
  assert.deepEqual(scanSummary(files), { total: 2, newCount: 2, alreadyCount: 0 });
});

test('scanSummary: all already in library', () => {
  const files = [
    { name: 'a.pdf', already_in_library: true },
    { name: 'b.pdf', already_in_library: true },
  ];
  assert.deepEqual(scanSummary(files), { total: 2, newCount: 0, alreadyCount: 2 });
});

test('scanSummary: null/undefined files -> zeros', () => {
  assert.deepEqual(scanSummary(null), { total: 0, newCount: 0, alreadyCount: 0 });
  assert.deepEqual(scanSummary(undefined), { total: 0, newCount: 0, alreadyCount: 0 });
});

test('scanSummary: empty array -> zeros', () => {
  assert.deepEqual(scanSummary([]), { total: 0, newCount: 0, alreadyCount: 0 });
});

// ---------------------------------------------------------------------------
// scanRows (folder scan-preview)
// ---------------------------------------------------------------------------

test('scanRows: normalizes fields from scan file objects', () => {
  const files = [
    { name: 'b.pdf', path: '/lib/b.pdf', rel_path: 'sub/b.pdf', already_in_library: false },
  ];
  const rows = scanRows(files);
  assert.deepEqual(rows, [
    { name: 'b.pdf', relPath: 'sub/b.pdf', path: '/lib/b.pdf', already: false },
  ]);
});

test('scanRows: new files sort before already-in-library, each group sorted by relPath', () => {
  const files = [
    { name: 'z.pdf', path: '/lib/z.pdf', rel_path: 'z.pdf', already_in_library: true },
    { name: 'b.pdf', path: '/lib/b.pdf', rel_path: 'b.pdf', already_in_library: false },
    { name: 'a.pdf', path: '/lib/a.pdf', rel_path: 'a.pdf', already_in_library: true },
    { name: 'c.pdf', path: '/lib/c.pdf', rel_path: 'c.pdf', already_in_library: false },
  ];
  const rows = scanRows(files);
  assert.deepEqual(rows.map(r => r.relPath), ['b.pdf', 'c.pdf', 'a.pdf', 'z.pdf']);
  assert.deepEqual(rows.map(r => r.already), [false, false, true, true]);
});

test('scanRows: tolerates missing fields (falls back to name/path)', () => {
  const files = [
    { path: '/lib/nopename.pdf', already_in_library: false },
    {},
  ];
  const rows = scanRows(files);
  const withPath = rows.find(r => r.relPath === '/lib/nopename.pdf');
  const empty = rows.find(r => r.relPath === '');
  assert.ok(withPath, 'row falls back to path when name/rel_path are missing');
  assert.equal(withPath.name, '');
  assert.ok(empty, 'row with no fields at all still produces a row');
  assert.equal(empty.path, '');
  assert.equal(empty.already, false);
});

test('scanRows: null/undefined files -> empty array', () => {
  assert.deepEqual(scanRows(null), []);
  assert.deepEqual(scanRows(undefined), []);
});

// ---------------------------------------------------------------------------
// manifestItemView (progress dock per-file status chip)
// ---------------------------------------------------------------------------

test('manifestItemView: queued', () => {
  const view = manifestItemView({ status: 'queued' });
  assert.equal(view.cls, 'lib-status-pill-queued');
  assert.equal(view.chipLabel, 'Queued');
});

test('manifestItemView: processing', () => {
  const view = manifestItemView({ status: 'processing' });
  assert.equal(view.cls, 'lib-status-pill-processing');
  assert.equal(view.chipLabel, 'Reading…');
});

test('manifestItemView: done', () => {
  const view = manifestItemView({ status: 'done' });
  assert.equal(view.cls, 'lib-status-pill-ingested');
  assert.equal(view.chipLabel, 'Added ✓');
  assert.equal(view.icon, '✓');
});

test('manifestItemView: failed', () => {
  const view = manifestItemView({ status: 'failed' });
  assert.equal(view.cls, 'lib-status-pill-failed');
  assert.equal(view.chipLabel, 'Failed ✗');
  assert.equal(view.icon, '✗');
});

test('manifestItemView: skipped', () => {
  const view = manifestItemView({ status: 'skipped' });
  assert.equal(view.cls, 'lib-status-pill-skipped');
  assert.equal(view.chipLabel, 'Skipped');
});

test('manifestItemView: unknown/missing status falls back to queued', () => {
  const view = manifestItemView({});
  assert.equal(view.cls, 'lib-status-pill-queued');
  assert.equal(view.chipLabel, 'Queued');
});
