/**
 * sse.js — SSE client for /api/events with seq-gate and graph_delta coalescing.
 *
 * Exports (DOM-free, node-testable):
 *   makeSeqGate()          — creates a seq-gate closure
 *   makeCoalescer(fn, ms, scheduler, canceller) — creates a timer-injectable coalescer
 *
 * Default export (browser only):
 *   connectSSE(store, onResync) — opens EventSource and wires everything up
 */

// ---------------------------------------------------------------------------
// Pure, DOM-free: makeSeqGate
// ---------------------------------------------------------------------------

/**
 * Create a seq gate that drops duplicate or stale events.
 * Returns a gate function: gate(evt, handler) — calls handler(evt) only if seq > lastSeq.
 * gate.lastSeq() returns the current high-water mark.
 *
 * @returns {Function & { lastSeq: () => number }}
 */
export function makeSeqGate() {
  let _lastSeq = 0;

  function gate(evt, handler) {
    const seq = evt && evt.seq;
    if (typeof seq !== 'number' || seq <= _lastSeq) return;
    _lastSeq = seq;
    handler(evt);
  }

  gate.lastSeq = () => _lastSeq;
  return gate;
}

// ---------------------------------------------------------------------------
// Pure, DOM-free: makeCoalescer
// ---------------------------------------------------------------------------

/**
 * Create a coalescer that batches events and flushes them at most every `interval` ms.
 * The scheduler and canceller are injectable for testing (default: setTimeout/clearTimeout).
 *
 * @param {(items: object[]) => void} flushFn
 * @param {number} interval  — ms between flushes
 * @param {Function} [scheduler]  — injectable setTimeout-like
 * @param {Function} [canceller]  — injectable clearTimeout-like
 * @returns {(item: object) => void}
 */
export function makeCoalescer(
  flushFn,
  interval = 200,
  scheduler = setTimeout,
  canceller = clearTimeout
) {
  let pending = [];
  let timerId = null;

  return function coalesce(item) {
    pending.push(item);
    if (timerId !== null) {
      canceller(timerId);
    }
    timerId = scheduler(() => {
      const batch = pending;
      pending = [];
      timerId = null;
      flushFn(batch);
    }, interval);
  };
}

// ---------------------------------------------------------------------------
// Browser-only: connectSSE
// ---------------------------------------------------------------------------

/**
 * Open an EventSource to /api/events and dispatch events through the store.
 *
 * @param {object} store  — the store module
 * @param {Function} onResync  — called when a gap is detected and we need to resync
 * @param {Function} [EventSourceImpl]  — injectable EventSource constructor (defaults to
 *   globalThis.EventSource); pass a fake in node tests so no browser globals are needed
 * @returns {{ close: () => void }}
 */
export function connectSSE(store, onResync, EventSourceImpl) {
  return _connectSSEImpl(store, onResync, EventSourceImpl);
}

function _connectSSEImpl(store, onResync, EventSourceImpl) {
  const ES = EventSourceImpl || globalThis.EventSource;
  const gate = makeSeqGate();
  let es = null;
  let closed = false;

  // Coalescer for graph_delta — flush into store every 200ms
  const graphCoalescer = makeCoalescer((batch) => {
    // Just bump graphSeq once for the batch; real graph data is F2's concern
    store.notify(['graph']);
  }, 200);

  function open() {
    if (closed) return;
    es = new ES('/api/events');

    es.onopen = () => {
      store.setConnection('connected');
      // If we had a gap (lastSeq > 0 means we were connected before), resync
      if (gate.lastSeq() > 0 && typeof onResync === 'function') {
        onResync();
      }
    };

    es.onerror = () => {
      store.setConnection('reconnecting');
      es.close();
      // Reconnect after 3 seconds
      if (!closed) setTimeout(open, 3000);
    };

    es.onmessage = (e) => {
      let evt;
      try { evt = JSON.parse(e.data); } catch { return; }

      gate(evt, (validEvt) => {
        if (validEvt.event === 'graph_delta') {
          // Coalesce graph_delta events
          graphCoalescer(validEvt);
          // Still apply to reducer for graphSeq
          const topics = store.applyAndNotify(validEvt);
          const nonGraphTopics = topics.filter(t => t !== 'graph');
          if (nonGraphTopics.length) store.notify(nonGraphTopics);
        } else {
          store.applyAndNotify(validEvt);
        }
      });
    };
  }

  open();

  return {
    close() {
      closed = true;
      if (es) { es.close(); es = null; }
    },
  };
}
