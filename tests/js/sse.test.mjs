/**
 * sse.test.mjs — TDD tests for makeSeqGate, makeCoalescer, and connectSSE.
 * Run from repo root:
 *   node --test tests/js/reducer.test.mjs tests/js/sse.test.mjs tests/js/format.test.mjs tests/js/mapping.test.mjs
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, '..', '..');
const { makeSeqGate, makeCoalescer, connectSSE } = await import(
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

// --- connectSSE tests ---

// Minimal fake EventSource that never fires events (just records the URL)
class FakeEventSource {
  constructor(url) {
    this.url = url;
    this.onopen = null;
    this.onerror = null;
    this.onmessage = null;
  }
  close() {}
}

// Minimal fake store (no _reducer property — tests the guard is gone)
function makeFakeStore() {
  const notifications = [];
  return {
    // Deliberately no _reducer property
    setConnection(status) { notifications.push({ type: 'connection', status }); },
    notify(topics) { notifications.push({ type: 'notify', topics }); },
    applyAndNotify(evt) { return []; },
    _notifications: notifications,
  };
}

test('connectSSE does NOT throw when store lacks _reducer', () => {
  const fakeStore = makeFakeStore();
  assert.doesNotThrow(() => {
    const conn = connectSSE(fakeStore, null, FakeEventSource);
    conn.close();
  }, 'connectSSE must not throw a guard error when store._reducer is absent');
});

test('connectSSE returns an object with a close() method', () => {
  const fakeStore = makeFakeStore();
  const conn = connectSSE(fakeStore, null, FakeEventSource);
  assert.ok(conn && typeof conn.close === 'function', 'should return { close() }');
  conn.close();
});

test('connectSSE calls store.setConnection when EventSource opens', () => {
  const fakeStore = makeFakeStore();
  let openHandler = null;

  class CapturingES extends FakeEventSource {
    constructor(url) {
      super(url);
      // Defer so connectSSE can assign onopen first
      Promise.resolve().then(() => {
        if (typeof this.onopen === 'function') this.onopen();
      });
    }
  }

  const conn = connectSSE(fakeStore, null, CapturingES);
  // Return a promise so the test runner awaits it
  return new Promise((resolve) => {
    setTimeout(() => {
      const connNotif = fakeStore._notifications.find(n => n.type === 'connection' && n.status === 'connected');
      assert.ok(connNotif, 'store.setConnection("connected") should be called on open');
      conn.close();
      resolve();
    }, 20);
  });
});
