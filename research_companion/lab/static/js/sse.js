/**
 * sse.js — SSE client for /api/events with seq-gate and graph_delta coalescing.
 *
 * Exports (DOM-free, node-testable):
 *   makeSeqGate()          — creates a seq-gate closure
 *   makeCoalescer(fn, ms, scheduler, canceller) — creates a timer-injectable coalescer
 *   onGraphDeltas(cb)      — register a callback that receives each coalesced batch of
 *                            raw graph_delta event objects; returns an unregister function
 *
 * Default export (browser only):
 *   connectSSE(store, onResync, EventSourceImpl?, scheduler?, canceller?)
 *                          — opens EventSource and wires everything up
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
// Module-level graph_delta listener registry
// ---------------------------------------------------------------------------

/** @type {Set<(batch: object[]) => void>} */
const _graphDeltaListeners = new Set();

/**
 * Register a callback to receive coalesced graph_delta batches.
 * The callback is called with an array of raw graph_delta SSE event objects
 * every time the 200ms coalescer flushes.
 *
 * @param {(batch: object[]) => void} cb
 * @returns {() => void}  — call to unregister
 */
export function onGraphDeltas(cb) {
  _graphDeltaListeners.add(cb);
  return () => _graphDeltaListeners.delete(cb);
}

// ---------------------------------------------------------------------------
// Browser-only: connectSSE
// ---------------------------------------------------------------------------

/**
 * Open an EventSource to /api/events and dispatch events through the store.
 *
 * @param {object}   store            — the store module
 * @param {Function} onResync         — called when a gap is detected and we need to resync
 * @param {Function} [EventSourceImpl] — injectable EventSource constructor (defaults to
 *   globalThis.EventSource); pass a fake in node tests so no browser globals are needed
 * @param {Function} [scheduler]      — injectable setTimeout (for testing coalescer timing)
 * @param {Function} [canceller]      — injectable clearTimeout (for testing coalescer timing)
 * @returns {{ close: () => void }}
 */
export function connectSSE(store, onResync, EventSourceImpl, scheduler, canceller) {
  return _connectSSEImpl(store, onResync, EventSourceImpl, scheduler, canceller);
}

function _connectSSEImpl(store, onResync, EventSourceImpl, scheduler, canceller) {
  const ES = EventSourceImpl || globalThis.EventSource;
  const gate = makeSeqGate();
  let es = null;
  let closed = false;

  // Coalescer for graph_delta — flush every 200ms.
  // On flush: notify store (for counters / graphSeq) AND call all registered
  // onGraphDeltas listeners with the raw batch.
  const graphCoalescer = makeCoalescer((batch) => {
    // Notify store that graph changed (bumps graphSeq for counters)
    store.notify(['graph']);
    // Deliver raw batch to all registered delta listeners (e.g. views/graph.js)
    if (_graphDeltaListeners.size > 0) {
      for (const cb of _graphDeltaListeners) {
        try { cb(batch); } catch (e) { console.error('[sse] onGraphDeltas listener error', e); }
      }
    }
  }, 200, scheduler, canceller);

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
          // Coalesce graph_delta events; flush delivers to store.notify + onGraphDeltas listeners
          graphCoalescer(validEvt);
          // Still apply to reducer for graphSeq (but suppress 'graph' topic here —
          // the coalescer flush already calls store.notify(['graph']))
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
