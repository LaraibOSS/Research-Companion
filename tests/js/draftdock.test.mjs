/**
 * draftdock.test.mjs — TDD tests for dockModel and F3 reducer additions.
 * Run from repo root: node --test tests/js/
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot  = path.resolve(__dirname, '..', '..');

const { dockModel } = await import(
  pathToFileURL(path.join(repoRoot, 'research_companion', 'lab', 'static', 'js', 'components', 'progressDock.js')).href
);

const { applyEvent } = await import(
  pathToFileURL(path.join(repoRoot, 'research_companion', 'lab', 'static', 'js', 'reducer.js')).href
);

// ---------------------------------------------------------------------------
// Helper: build initial state (mirrors reducer.test.mjs)
// ---------------------------------------------------------------------------
function makeState() {
  return {
    papers:    new Map(),
    draftId:   null,
    sections:  [],
    lab:       { counts: {} },
    jobs:      new Map(),
    connection: 'connected',
    failures:  {},
    graphSeq:  0,
    ingestLog: [],
  };
}

// ===========================================================================
// dockModel table-driven tests
// ===========================================================================

test('dockModel: no job -> hidden', () => {
  const state = makeState();
  const model = dockModel(state);
  assert.equal(model.visible, false);
  assert.equal(model.bar.done, 0);
  assert.equal(model.bar.total, 0);
  assert.deepEqual(model.items, []);
  assert.equal(model.summary, null);
});

test('dockModel: running job with total=0 -> hidden (dock only appears when total>0)', () => {
  const state = makeState();
  state.jobs.set('ingest', { status: 'running', done: 0, total: 0, current: '' });
  const model = dockModel(state);
  assert.equal(model.visible, false);
});

test('dockModel: running job with total>0 -> visible, bar, current shown', () => {
  const state = makeState();
  state.jobs.set('ingest', { status: 'running', done: 2, total: 5, current: 'paper_a.pdf' });
  const model = dockModel(state);
  assert.equal(model.visible, true);
  assert.equal(model.collapsed, false);
  assert.equal(model.bar.done, 2);
  assert.equal(model.bar.total, 5);
  assert.equal(model.current, 'paper_a.pdf');
  assert.equal(model.summary, null);
});

test('dockModel: failures -> items with retryable iff paperId present', () => {
  const state = makeState();
  state.jobs.set('ingest', { status: 'running', done: 1, total: 3, current: '' });
  state.ingestLog = [
    { ok: false, label: 'bad.pdf',  paperId: 'local:bad', seq: 0 },
    { ok: false, label: 'noId.pdf', paperId: null,         seq: 1 },
  ];
  const model = dockModel(state);
  assert.equal(model.items.length, 2);
  assert.equal(model.items[0].retryable, true,  'item with paperId is retryable');
  assert.equal(model.items[1].retryable, false, 'item without paperId is NOT retryable');
  assert.equal(model.items[0].paperId, 'local:bad');
  assert.equal(model.items[1].paperId, null);
});

test('dockModel: job_done -> summary pill (collapsed=true, summary string)', () => {
  const state = makeState();
  state.jobs.set('ingest', { status: 'done', done: 3, total: 3, current: '' });
  state.ingestLog = [
    { ok: true,  label: 'p1.pdf', paperId: 'local:p1', seq: 0 },
    { ok: true,  label: 'p2.pdf', paperId: 'local:p2', seq: 1 },
    { ok: false, label: 'p3.pdf', paperId: null,        seq: 2 },
  ];
  const model = dockModel(state);
  assert.equal(model.visible, true);
  assert.equal(model.collapsed, true);
  assert.ok(model.summary, 'summary should be set');
  assert.ok(model.summary.includes('2'), 'summary should count 2 successes');
  assert.ok(model.summary.toLowerCase().includes('ingest'), 'summary should mention ingest');
});

test('dockModel: job_done with 1 paper -> singular "paper" in summary', () => {
  const state = makeState();
  state.jobs.set('ingest', { status: 'done', done: 1, total: 1, current: '' });
  state.ingestLog = [{ ok: true, label: 'p1.pdf', paperId: 'local:p1', seq: 0 }];
  const model = dockModel(state);
  assert.ok(model.summary.includes('1 paper'), `expected "1 paper" in "${model.summary}"`);
});

test('dockModel: items carry label from ingestLog', () => {
  const state = makeState();
  state.jobs.set('ingest', { status: 'running', done: 1, total: 2, current: '' });
  state.ingestLog = [{ ok: true, label: 'My Paper Title', paperId: 'local:x', seq: 0 }];
  const model = dockModel(state);
  assert.equal(model.items[0].label, 'My Paper Title');
  assert.equal(model.items[0].ok, true);
});

// ===========================================================================
// Reducer additions: ingestLog
// ===========================================================================

test('reducer: ingest_progress on fresh state initialises ingestLog', () => {
  const state = makeState();
  applyEvent(state, { event: 'ingest_progress', done: 0, total: 3, current: 'a.pdf' });
  assert.ok(Array.isArray(state.ingestLog), 'ingestLog should be an array');
  assert.equal(state.ingestLog.length, 0);
});

test('reducer: ingest_failed pushes failure entry to ingestLog', () => {
  const state = makeState();
  // Start the job
  applyEvent(state, { event: 'ingest_progress', done: 0, total: 3, current: 'bad.pdf' });
  const topics = applyEvent(state, {
    event: 'ingest_failed',
    path: 'bad.pdf',
    stage: 'extract',
    error: 'parse error',
    paper_id: null,
  });
  assert.ok(topics.includes('ingestLog'), 'ingestLog topic emitted on ingest_failed');
  assert.equal(state.ingestLog.length, 1);
  const entry = state.ingestLog[0];
  assert.equal(entry.ok, false);
  assert.equal(entry.label, 'bad.pdf');
  assert.equal(entry.paperId, null);
});

test('reducer: ingest_failed with paper_id -> retryable entry', () => {
  const state = makeState();
  applyEvent(state, { event: 'ingest_progress', done: 0, total: 1, current: 'p.pdf' });
  applyEvent(state, {
    event: 'ingest_failed',
    path: 'p.pdf',
    stage: 'align',
    error: 'timeout',
    paper_id: 'local:ppp',
  });
  const entry = state.ingestLog[0];
  assert.equal(entry.paperId, 'local:ppp');
  assert.equal(entry.ok, false);
});

test('reducer: paper_added during running job pushes success entry to ingestLog', () => {
  const state = makeState();
  applyEvent(state, { event: 'ingest_progress', done: 0, total: 2, current: 'p.pdf' });
  const topics = applyEvent(state, {
    event: 'paper_added',
    paper_id: 'local:q',
    title: 'A Cool Paper',
    source: '',
  });
  assert.ok(topics.includes('ingestLog'), 'ingestLog topic emitted');
  assert.equal(state.ingestLog.length, 1);
  const entry = state.ingestLog[0];
  assert.equal(entry.ok, true);
  assert.equal(entry.paperId, 'local:q');
  assert.equal(entry.label, 'A Cool Paper');
});

test('reducer: paper_added WITHOUT active job does NOT push to ingestLog', () => {
  const state = makeState();
  // No ingest_progress first
  const topics = applyEvent(state, {
    event: 'paper_added',
    paper_id: 'local:r',
    title: 'Orphan Paper',
    source: '',
  });
  assert.equal(state.ingestLog.length, 0, 'no ingestLog entry when no job running');
  assert.ok(!topics.includes('ingestLog'), 'no ingestLog topic when no job running');
});

test('reducer: ingest_progress resets ingestLog when previous job was done', () => {
  const state = makeState();
  // Run first job
  applyEvent(state, { event: 'ingest_progress', done: 0, total: 1, current: '' });
  applyEvent(state, {
    event: 'ingest_failed', path: 'old.pdf', stage: 'x', error: 'e', paper_id: null,
  });
  applyEvent(state, { event: 'job_done', job: 'ingest' });
  assert.equal(state.ingestLog.length, 1, 'first run had 1 log entry');

  // Start second job
  applyEvent(state, { event: 'ingest_progress', done: 0, total: 2, current: '' });
  assert.equal(state.ingestLog.length, 0, 'ingestLog reset for new run');
});

// ===========================================================================
// Reducer additions: alignment topic
// ===========================================================================

test('reducer: alignment_ready emits "alignment" topic', () => {
  const state = makeState();
  state.papers.set('p1', { paper_id: 'p1', status: 'processing' });
  const topics = applyEvent(state, {
    event: 'alignment_ready',
    paper_id: 'p1',
    draft_paper_id: 'draft1',
    verdict: 'strengthens',
    score: 0.9,
  });
  assert.ok(topics.includes('alignment'), 'alignment topic should be emitted');
  assert.ok(topics.includes('papers'),   'papers topic should still be emitted');
});

// ===========================================================================
// Fixture replay: verify ingestLog is populated
// ===========================================================================

test('fixture replay: ingestLog has 1 failure entry from lab_events.jsonl', () => {
  const fixturePath = path.join(repoRoot, 'tests', 'fixtures', 'lab_events.jsonl');
  const lines = fs.readFileSync(fixturePath, 'utf8').trim().split('\n');
  const state = makeState();

  for (const line of lines) {
    applyEvent(state, JSON.parse(line));
  }

  // lab_events.jsonl has 1 ingest_failed (local:fixb) and 3 paper_added during a job
  const failures = state.ingestLog.filter(e => !e.ok);
  const successes = state.ingestLog.filter(e => e.ok);

  assert.equal(failures.length, 1,  'should have 1 failure in ingestLog');
  assert.ok(successes.length >= 2,  'should have >=2 success entries (paper_added during job)');

  const failEntry = failures[0];
  assert.equal(failEntry.ok, false);
  assert.ok(failEntry.label, 'failure entry should have a label');
});

// ===========================================================================
// dockModel: dismiss/resurrect behaviour
// These tests verify the pure model: after job_done, subsequent notifications
// that don't change the job status must NOT flip visible back to true from a
// dismissed state — the subscriber logic (not the model) is responsible for
// resetting _dismissed only on real transitions.
// ===========================================================================

test('dockModel: done state stays collapsed/summary across multiple calls (no spontaneous reset)', () => {
  // Simulate: job finishes, dockModel is called multiple times (e.g. papers events arrive)
  // The model must keep returning collapsed:true / summary for the same done state.
  const state = makeState();
  state.jobs.set('ingest', { status: 'done', done: 2, total: 2 });
  state.ingestLog = [
    { ok: true, label: 'p1.pdf', paperId: 'local:p1', seq: 0 },
    { ok: true, label: 'p2.pdf', paperId: 'local:p2', seq: 1 },
  ];

  // Call dockModel multiple times — simulates alignment_ready / papers notifications
  const m1 = dockModel(state);
  const m2 = dockModel(state);
  const m3 = dockModel(state);

  assert.equal(m1.collapsed, true, 'first call: collapsed');
  assert.equal(m2.collapsed, true, 'second call: still collapsed (no transition)');
  assert.equal(m3.collapsed, true, 'third call: still collapsed');
  assert.ok(m1.summary, 'summary present');
  assert.ok(m2.summary, 'summary still present on re-call');
  assert.ok(m3.summary, 'summary still present on third re-call');
});

test('dockModel: new run (status transitions running) yields visible=true, collapsed=false', () => {
  // Simulate a second ingest starting after first completed
  const state = makeState();
  state.jobs.set('ingest', { status: 'done', done: 1, total: 1 });
  state.ingestLog = [{ ok: true, label: 'p1.pdf', paperId: 'local:p1', seq: 0 }];

  // First run done
  const m1 = dockModel(state);
  assert.equal(m1.collapsed, true, 'done -> collapsed pill');

  // New run starts
  state.jobs.set('ingest', { status: 'running', done: 0, total: 3, current: 'x.pdf' });
  state.ingestLog = [];
  const m2 = dockModel(state);
  assert.equal(m2.visible, true, 'new run -> visible');
  assert.equal(m2.collapsed, false, 'new run -> not collapsed');
  assert.equal(m2.summary, null, 'new run -> no summary');
});

test('dockModel: done state -> papers notification same status -> model unchanged (caller must not reset _dismissed)', () => {
  // Confirms the model never spontaneously changes state between equal-status calls.
  // The spec fix is: _dismissed resets ONLY on status transition, not on every 'done' notification.
  const state = makeState();
  state.jobs.set('ingest', { status: 'done', done: 1, total: 1 });
  state.ingestLog = [{ ok: true, label: 'p.pdf', paperId: 'local:p', seq: 0 }];

  const before = dockModel(state);
  // Simulate a papers-topic notification (e.g. alignment_ready) — state unchanged
  state.papers.set('local:p', { paper_id: 'local:p', title: 'P', strength: 'strong' });
  const after = dockModel(state);

  // Model outputs must be identical in structure (summary, collapsed, visible)
  assert.equal(before.visible,   after.visible);
  assert.equal(before.collapsed, after.collapsed);
  assert.equal(before.summary,   after.summary);
});
