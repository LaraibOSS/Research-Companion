/**
 * sse.test.mjs — TDD tests for makeSeqGate and makeCoalescer.
 * Run from repo root: node --test tests/js/
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, '..', '..');
const { makeSeqGate, makeCoalescer } = await import(
  pathToFileURL(path.join(repoRoot, 'research_companion', 'lab', 'static', 'js', 'sse.js')).href
);

// --- makeSeqGate tests ---

test('makeSeqGate accepts events with increasing seq', () => {
  const gate = makeSeqGate();
  const accepted = [];
  const handler = (evt) => accepted.push(evt.seq);

  gate({ seq: 1, event: 'paper_added' }, handler);
  gate({ seq: 2, event: 'paper_added' }, handler);
  gate({ seq: 3, event: 'paper_added' }, handler);

  assert.deepEqual(accepted, [1, 2, 3]);
});

test('makeSeqGate drops duplicate seq', () => {
  const gate = makeSeqGate();
  const accepted = [];
  const handler = (evt) => accepted.push(evt.seq);

  gate({ seq: 1, event: 'paper_added' }, handler);
  gate({ seq: 1, event: 'paper_added' }, handler); // duplicate
  gate({ seq: 2, event: 'paper_added' }, handler);

  assert.deepEqual(accepted, [1, 2]);
});

test('makeSeqGate drops stale (lower) seq', () => {
  const gate = makeSeqGate();
  const accepted = [];
  const handler = (evt) => accepted.push(evt.seq);

  gate({ seq: 5, event: 'paper_added' }, handler);
  gate({ seq: 3, event: 'paper_added' }, handler); // stale
  gate({ seq: 6, event: 'paper_added' }, handler);

  assert.deepEqual(accepted, [5, 6]);
});

test('makeSeqGate: lastSeq is accessible', () => {
  const gate = makeSeqGate();
  assert.equal(gate.lastSeq(), 0);
  gate({ seq: 7, event: 'paper_added' }, () => {});
  assert.equal(gate.lastSeq(), 7);
});

// --- makeCoalescer tests ---

test('makeCoalescer batches multiple calls into one flush', () => {
  const flushed = [];
  let pendingFn = null;
  let pendingDelay = null;

  // Fake scheduler: captures the scheduled function
  function fakeScheduler(fn, delay) {
    pendingFn = fn;
    pendingDelay = delay;
    return 1; // fake timer id
  }
  function fakeCanceller(id) {}

  const coalescer = makeCoalescer(
    (items) => flushed.push([...items]),
    200,
    fakeScheduler,
    fakeCanceller
  );

  coalescer({ event: 'graph_delta', seq: 1 });
  coalescer({ event: 'graph_delta', seq: 2 });
  coalescer({ event: 'graph_delta', seq: 3 });

  // Nothing flushed yet
  assert.equal(flushed.length, 0, 'should not have flushed yet');
  assert.equal(pendingDelay, 200, 'should schedule with 200ms delay');

  // Trigger flush
  pendingFn();
  assert.equal(flushed.length, 1, 'should flush once');
  assert.equal(flushed[0].length, 3, 'should have all 3 items');
});

test('makeCoalescer: subsequent calls reset the timer', () => {
  const flushed = [];
  const schedulerCalls = [];
  let timerIdCounter = 0;
  let pendingFn = null;
  const cancelledIds = [];

  function fakeScheduler(fn, delay) {
    const id = ++timerIdCounter;
    schedulerCalls.push(id);
    pendingFn = fn;
    return id;
  }
  function fakeCanceller(id) {
    cancelledIds.push(id);
  }

  const coalescer = makeCoalescer(
    (items) => flushed.push([...items]),
    200,
    fakeScheduler,
    fakeCanceller
  );

  coalescer({ event: 'graph_delta', seq: 1 });
  coalescer({ event: 'graph_delta', seq: 2 }); // second call should cancel first timer

  // First timer (id=1) should have been cancelled
  assert.ok(cancelledIds.includes(1), 'first timer should be cancelled');

  // Flush with the latest timer
  pendingFn();
  assert.equal(flushed.length, 1);
  assert.equal(flushed[0].length, 2);
});

test('makeCoalescer: after flush, new calls schedule again', () => {
  const flushed = [];
  let pendingFn = null;

  function fakeScheduler(fn, delay) {
    pendingFn = fn;
    return 1;
  }
  function fakeCanceller(id) {}

  const coalescer = makeCoalescer(
    (items) => flushed.push([...items]),
    200,
    fakeScheduler,
    fakeCanceller
  );

  coalescer({ event: 'graph_delta', seq: 1 });
  pendingFn(); // first flush
  assert.equal(flushed.length, 1);

  // new call after flush
  coalescer({ event: 'graph_delta', seq: 2 });
  pendingFn(); // second flush
  assert.equal(flushed.length, 2);
  assert.equal(flushed[1][0].seq, 2);
});
