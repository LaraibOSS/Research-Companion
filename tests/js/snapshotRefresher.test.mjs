/**
 * snapshotRefresher.test.mjs — Tests for makeSnapshotRefresher debounce/merge logic.
 * Run from repo root:
 *   node --test tests/js/reducer.test.mjs tests/js/sse.test.mjs tests/js/format.test.mjs tests/js/mapping.test.mjs tests/js/snapshotRefresher.test.mjs
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, '..', '..');
const { makeSnapshotRefresher } = await import(
  pathToFileURL(
    path.join(repoRoot, 'research_companion', 'lab', 'static', 'js', 'snapshotRefresher.js')
  ).href
);

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeFakeTimer() {
  let timerId = 0;
  const pending = new Map(); // id -> fn
  const cancelled = new Set();

  function scheduler(fn, ms) {
    const id = ++timerId;
    pending.set(id, fn);
    return id;
  }
  function canceller(id) {
    cancelled.add(id);
    pending.delete(id);
  }
  async function flush(id) {
    const fn = pending.get(id);
    if (fn) {
      pending.delete(id);
      await fn();
    }
  }
  async function flushAll() {
    for (const [id, fn] of [...pending]) {
      pending.delete(id);
      await fn();
    }
  }
  return { scheduler, canceller, cancelled, pending, flush, flushAll, get lastId() { return timerId; } };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test('makeSnapshotRefresher: schedule() triggers fetchPapers after debounce', async () => {
  const fetched = [];
  const applied = [];
  const fakePapers = [{ paper_id: 'p1', stance_counts: { strengthens: 1, challenges: 0, alternative: 0 } }];

  async function fetchPapers() {
    fetched.push(Date.now());
    return fakePapers;
  }
  function applyFn(papers) {
    applied.push(papers);
  }

  const timer = makeFakeTimer();
  const refresher = makeSnapshotRefresher(fetchPapers, applyFn, 500, timer.scheduler, timer.canceller);

  refresher.schedule();
  assert.equal(fetched.length, 0, 'fetch should not fire until timer fires');

  await timer.flushAll();
  assert.equal(fetched.length, 1, 'fetch should fire once after timer');
  assert.equal(applied.length, 1, 'applyFn should be called once');
  assert.deepEqual(applied[0], fakePapers);
});

test('makeSnapshotRefresher: multiple schedule() calls debounce to one fetch', async () => {
  const fetched = [];
  const timer = makeFakeTimer();

  async function fetchPapers() { fetched.push(1); return []; }

  const refresher = makeSnapshotRefresher(fetchPapers, () => {}, 500, timer.scheduler, timer.canceller);

  refresher.schedule();
  refresher.schedule();
  refresher.schedule();

  // First two timers should be cancelled
  assert.ok(timer.cancelled.has(1), 'first timer should be cancelled');
  assert.ok(timer.cancelled.has(2), 'second timer should be cancelled');
  assert.equal(timer.pending.size, 1, 'only the last timer should be pending');

  await timer.flushAll();
  assert.equal(fetched.length, 1, 'only one fetch despite three schedule() calls');
});

test('makeSnapshotRefresher: fetch errors are non-fatal', async () => {
  const timer = makeFakeTimer();
  let applyCount = 0;

  async function fetchPapers() { throw new Error('network failure'); }
  function applyFn() { applyCount++; }

  const refresher = makeSnapshotRefresher(fetchPapers, applyFn, 500, timer.scheduler, timer.canceller);
  refresher.schedule();

  await assert.doesNotReject(timer.flushAll(), 'fetch error must not propagate');
  assert.equal(applyCount, 0, 'applyFn should not be called on fetch error');
});

test('makeSnapshotRefresher: after one flush, schedule() can fire again', async () => {
  const fetched = [];
  const timer = makeFakeTimer();

  async function fetchPapers() { fetched.push(1); return []; }

  const refresher = makeSnapshotRefresher(fetchPapers, () => {}, 500, timer.scheduler, timer.canceller);

  refresher.schedule();
  await timer.flushAll();
  assert.equal(fetched.length, 1);

  refresher.schedule();
  await timer.flushAll();
  assert.equal(fetched.length, 2, 'second schedule-cycle should produce a second fetch');
});

test('makeSnapshotRefresher: applyFn receives the papers from fetchPapers', async () => {
  const timer = makeFakeTimer();
  const receivedPapers = [];
  const fakePapers = [
    { paper_id: 'a1', stance_counts: { strengthens: 2, challenges: 1, alternative: 0 } },
    { paper_id: 'a2', stance_counts: { strengthens: 0, challenges: 3, alternative: 1 } },
  ];

  async function fetchPapers() { return fakePapers; }
  function applyFn(papers) { receivedPapers.push(...papers); }

  const refresher = makeSnapshotRefresher(fetchPapers, applyFn, 500, timer.scheduler, timer.canceller);
  refresher.schedule();
  await timer.flushAll();

  assert.equal(receivedPapers.length, 2);
  assert.equal(receivedPapers[0].paper_id, 'a1');
  assert.equal(receivedPapers[1].paper_id, 'a2');
});
