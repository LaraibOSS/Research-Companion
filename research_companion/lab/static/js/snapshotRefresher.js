/**
 * snapshotRefresher.js — Debounced snapshot refresher for stance_counts.
 *
 * When an alignment_ready SSE event fires, the reducer sets paper.stance/score
 * from the event payload, but stance_counts (used by library cards) is a
 * server-side aggregate that only a fresh GET /api/papers can supply.
 *
 * makeSnapshotRefresher wires up a debounced fetch so that any burst of
 * alignment_ready events results in exactly one GET /api/papers after the
 * burst settles, merging the fresh stance_counts back into the store.
 *
 * Exports:
 *   makeSnapshotRefresher(fetchPapers, applyFn, debounceMs, scheduler)
 *     — returns { schedule() } — call schedule() on each alignment_ready.
 *
 * All arguments except fetchPapers are injectable for node testing.
 */

/**
 * @param {() => Promise<object[]>} fetchPapers
 *   Async function returning the fresh papers array (e.g. api.getPapers).
 * @param {(papers: object[]) => void} applyFn
 *   Called with the fresh papers array to merge into the store.
 * @param {number} [debounceMs=500]
 *   How long to wait after the last schedule() call before fetching.
 * @param {Function} [scheduler=setTimeout]
 *   Injectable setTimeout-like for testing.
 * @param {Function} [canceller=clearTimeout]
 *   Injectable clearTimeout-like for testing.
 * @returns {{ schedule: () => void }}
 */
export function makeSnapshotRefresher(
  fetchPapers,
  applyFn,
  debounceMs = 500,
  scheduler = setTimeout,
  canceller = clearTimeout,
) {
  let timerId = null;

  function schedule() {
    if (timerId !== null) {
      canceller(timerId);
    }
    timerId = scheduler(async () => {
      timerId = null;
      try {
        const papers = await fetchPapers();
        applyFn(papers);
      } catch (err) {
        // Non-fatal: stance_counts will refresh on next full resync
        console.warn('[snapshotRefresher] fetch failed:', err);
      }
    }, debounceMs);
  }

  return { schedule };
}
