/**
 * "Import from Zotero" display logic.
 *
 * The report fixture is the shape interop/zotero.import_items returns; the
 * point of these tests is that no bucket of the denominator is dropped and
 * that a refusal is shown with the server's own reason.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  statusView, collectionOptions, reportSummary, reportRows, nextPoll, progressText,
  MAX_POLL_FAILURES,
} from '../../research_companion/lab/static/js/zoteroHelpers.js';

test('a ready Zotero is ready', () => {
  const v = statusView({ state: 'ready', ok: true, message: 'Connected to Zotero.' });
  assert.deepEqual(v, { ready: true, tone: 'ok', message: 'Connected to Zotero.' });
});

test('local API off keeps the server reason, which says where to turn it on', () => {
  const msg = 'Zotero is running, but ... Settings → Advanced ...';
  const v = statusView({ state: 'disabled', ok: false, message: msg });
  assert.equal(v.ready, false);
  assert.equal(v.tone, 'warn');
  assert.equal(v.message, msg);
});

test('a missing or odd status is never ready', () => {
  assert.equal(statusView(null).ready, false);
  assert.equal(statusView({ ok: true }).ready, false);
  assert.match(statusView({}).message, /Could not tell/);
});

test('collections: whole library first, counts shown when known', () => {
  const opts = collectionOptions({ collections: [
    { key: 'AB12', name: 'Thesis', items: 3 },
    { key: 'CD34', name: 'Reading', items: null },
    { name: 'no key' },
  ] });
  assert.deepEqual(opts, [
    { value: '', label: 'Whole library' },
    { value: 'AB12', label: 'Thesis (3)' },
    { value: 'CD34', label: 'Reading' },
  ]);
  assert.deepEqual(collectionOptions(undefined), [{ value: '', label: 'Whole library' }]);
});

const IMPORTED = {
  dry_run: false, total: 5, added: 2, metadata_only: 1, already_in_library: 1, no_pdf: 1,
  failed: [{ title: 'Bad', reason: 'Crossref API returned no entry' }],
  items: [
    { title: 'A', method: 'arxiv', outcome: 'added', has_pdf: true },
    { title: 'B', method: 'doi', outcome: 'added', has_pdf: false },
    { title: 'C', method: 'metadata', outcome: 'metadata_only' },
    { title: 'D', method: 'doi', outcome: 'already_in_library' },
    { title: 'Bad', outcome: 'failed', reason: 'Crossref API returned no entry' },
  ],
};

test('summary names every bucket, including papers still without a PDF', () => {
  assert.equal(reportSummary(IMPORTED),
    'Of 5 items: 2 added (1 still without a PDF), 1 added as details only, '
    + '1 already in your library, 1 could not be added.');
});

test('a preview says nothing has been added', () => {
  const s = reportSummary({ ...IMPORTED, dry_run: true, no_pdf: 0 });
  assert.match(s, /^Preview of 5 items: 2 would be added/);
  assert.match(s, /Nothing has been added yet\.$/);
});

test('an empty library is said plainly', () => {
  assert.match(reportSummary({ total: 0, failed: [] }), /no papers were found/);
});

test('rows: a failure carries its reason, an add without PDF is flagged', () => {
  const rows = reportRows(IMPORTED);
  assert.equal(rows.length, 5);
  assert.deepEqual(rows[0], { title: 'A', text: 'Added by arXiv id', tone: 'ok' });
  assert.deepEqual(rows[1], { title: 'B', text: 'Added by DOI; no PDF yet', tone: 'warn' });
  assert.equal(rows[3].text, 'Already in your library');
  assert.equal(rows[4].text, 'Could not add: Crossref API returned no entry');
  assert.equal(rows[4].tone, 'warn');
});

test('rows: preview outcomes', () => {
  const rows = reportRows({ items: [
    { title: 'P', method: 'pdf', outcome: 'would_add' },
    { title: '', method: 'metadata', outcome: 'would_add_metadata_only' },
  ] });
  assert.equal(rows[0].text, 'Would add from the PDF in Zotero');
  assert.equal(rows[1].title, '(untitled)');
  assert.match(rows[1].text, /details only/);
});

test('polling: done and failed end it, transient errors are bounded', () => {
  assert.equal(nextPoll({ job: { status: 'running' } }), 'continue');
  assert.equal(nextPoll({ job: { status: 'done' } }), 'done');
  assert.equal(nextPoll({ job: { status: 'failed' } }), 'failed');
  assert.equal(nextPoll({ error: { status: 500 }, consecutiveFailures: 0 }), 'continue');
  assert.equal(nextPoll({ error: { status: 500 }, consecutiveFailures: MAX_POLL_FAILURES - 1 }),
    'give-up');
  assert.equal(nextPoll({ error: { status: 404 } }), 'give-up');
});

test('progress text', () => {
  assert.equal(progressText({ dry_run: true, progress: { done: 0, total: 0 } }), 'Checking…');
  assert.equal(progressText({ dry_run: false, progress: { done: 3, total: 9 } }),
    'Importing 3 of 9…');
});
