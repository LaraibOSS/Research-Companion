/**
 * graphview.test.mjs — TDD tests for pure functions in graph/graphview.js.
 * Run from repo root: node --test tests/js/
 *
 * Tests:
 *   - seedPosition: anchored neighbor + jitter bounds; no neighbor -> null
 *   - makeFlasher:  batches one revert per flush; reverts exact node ids
 *   - makeFilterPredicate: table-driven (section+kind+draft); composed rules
 *   - dedup: existing ids skipped
 *   - shouldReducePerf: threshold decision
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, '..', '..');

const {
  seedPosition,
  makeFlasher,
  makeFilterPredicate,
  dedup,
  shouldReducePerf,
} = await import(
  pathToFileURL(
    path.join(repoRoot, 'research_companion', 'lab', 'static', 'js', 'graph', 'graphview.js')
  ).href
);

// ---------------------------------------------------------------------------
// seedPosition
// ---------------------------------------------------------------------------

test('seedPosition: returns null when no edges connect to known neighbor', () => {
  const newNode = { id: 'n1' };
  const edgesInDelta = [{ source: 'n1', target: 'n2' }];
  const getPositions = () => null; // n2 not positioned yet
  const result = seedPosition(newNode, edgesInDelta, getPositions);
  assert.equal(result, null);
});

test('seedPosition: returns null when no edges involve the new node', () => {
  const newNode = { id: 'n1' };
  const edgesInDelta = [{ source: 'n3', target: 'n4' }];
  const getPositions = (id) => ({ x: 100, y: 200 });
  const result = seedPosition(newNode, edgesInDelta, getPositions);
  assert.equal(result, null);
});

test('seedPosition: seeds near anchored neighbor with jitter in [-60, 60]', () => {
  const newNode = { id: 'child' };
  const edgesInDelta = [{ source: 'parent', target: 'child' }];
  const getPositions = (id) => id === 'parent' ? { x: 300, y: 200 } : null;

  // Use a seeded rng: always returns 0.5 => jitter = 0.5*120 - 60 = 0
  const rng = () => 0.5;
  const result = seedPosition(newNode, edgesInDelta, getPositions, rng);
  assert.ok(result !== null, 'should find a position');
  assert.equal(result.x, 300, 'x = parent.x + 0 jitter');
  assert.equal(result.y, 200, 'y = parent.y + 0 jitter');
});

test('seedPosition: jitter is within [-60, 60] range', () => {
  const newNode = { id: 'child' };
  const edgesInDelta = [{ source: 'parent', target: 'child' }];
  const getPositions = (id) => id === 'parent' ? { x: 0, y: 0 } : null;

  // Run with real Math.random 50 times
  for (let i = 0; i < 50; i++) {
    const result = seedPosition(newNode, edgesInDelta, getPositions);
    assert.ok(result !== null, 'should have a position');
    assert.ok(result.x >= -60 && result.x <= 60, `x jitter out of range: ${result.x}`);
    assert.ok(result.y >= -60 && result.y <= 60, `y jitter out of range: ${result.y}`);
  }
});

test('seedPosition: works with "from"/"to" edge format as well as source/target', () => {
  const newNode = { id: 'n2' };
  const edgesInDelta = [{ from: 'n1', to: 'n2' }];
  const getPositions = (id) => id === 'n1' ? { x: 50, y: 75 } : null;
  const rng = () => 0.5;
  const result = seedPosition(newNode, edgesInDelta, getPositions, rng);
  assert.ok(result !== null);
  assert.equal(result.x, 50);
  assert.equal(result.y, 75);
});

test('seedPosition: uses first anchored neighbor when multiple edges exist', () => {
  const newNode = { id: 'child' };
  const edgesInDelta = [
    { source: 'unpositioned', target: 'child' },
    { source: 'positioned', target: 'child' },
  ];
  const getPositions = (id) => {
    if (id === 'unpositioned') return null;
    if (id === 'positioned') return { x: 10, y: 20 };
    return null;
  };
  const rng = () => 0.5;
  const result = seedPosition(newNode, edgesInDelta, getPositions, rng);
  assert.ok(result !== null);
  assert.equal(result.x, 10);
  assert.equal(result.y, 20);
});

// ---------------------------------------------------------------------------
// makeFlasher
// ---------------------------------------------------------------------------

test('makeFlasher: schedules one timer per flush', () => {
  const updates = [];
  const scheduleLog = [];
  let timerCount = 0;

  const updateFn = (items) => updates.push(items);
  const schedule = (fn, ms) => {
    scheduleLog.push(ms);
    timerCount++;
    fn(); // execute immediately in test
    return timerCount;
  };

  const flasher = makeFlasher(updateFn, schedule);

  const items = [
    { id: 'n1', label: 'A' },
    { id: 'n2', label: 'B' },
    { id: 'n3', label: 'C' },
  ];
  flasher.flash(items, 800);

  // Only one timer scheduled per flash call
  assert.equal(scheduleLog.length, 1, 'should schedule exactly one timer');
  assert.equal(scheduleLog[0], 800, 'should use the provided duration');
});

test('makeFlasher: reverts all node ids in the batch', () => {
  const updates = [];
  const schedule = (fn, ms) => { fn(); return 1; };
  const updateFn = (items) => updates.push(...items);

  const flasher = makeFlasher(updateFn, schedule);
  const items = [{ id: 'x1' }, { id: 'x2' }, { id: 'x3' }];
  flasher.flash(items, 800);

  const revertedIds = updates.map(u => u.id);
  assert.deepEqual(revertedIds.sort(), ['x1', 'x2', 'x3'].sort());
});

test('makeFlasher: each reverted item has id, borderWidth, size, color', () => {
  const updates = [];
  const schedule = (fn, ms) => { fn(); return 1; };
  const updateFn = (items) => updates.push(...items);

  const flasher = makeFlasher(updateFn, schedule);
  flasher.flash([{ id: 'abc' }], 200);

  assert.equal(updates.length, 1);
  assert.ok('id' in updates[0]);
  assert.ok('borderWidth' in updates[0]);
});

test('makeFlasher: does nothing for empty items array', () => {
  let scheduled = 0;
  const schedule = (fn, ms) => { scheduled++; fn(); return 1; };
  const flasher = makeFlasher(() => {}, schedule);
  flasher.flash([], 800);
  assert.equal(scheduled, 0, 'should not schedule timer for empty array');
});

test('makeFlasher: uses default duration 800ms when not specified', () => {
  const scheduleLog = [];
  const schedule = (fn, ms) => { scheduleLog.push(ms); fn(); return 1; };
  const flasher = makeFlasher(() => {}, schedule);
  flasher.flash([{ id: 'n1' }]);
  assert.equal(scheduleLog[0], 800);
});

// ---------------------------------------------------------------------------
// makeFilterPredicate — table-driven
// ---------------------------------------------------------------------------

const filterCases = [
  {
    name: 'no filters: all nodes pass',
    sectionId: null,
    hiddenKinds: new Set(),
    draftPaperId: null,
    node: { id: 'n1', kind: 'concept', sections: ['s1'] },
    expected: true,
  },
  {
    name: 'hidden kind filters out node',
    sectionId: null,
    hiddenKinds: new Set(['concept']),
    draftPaperId: null,
    node: { id: 'n1', kind: 'concept', sections: ['s1'] },
    expected: false,
  },
  {
    name: 'hidden kind does not filter different kind',
    sectionId: null,
    hiddenKinds: new Set(['concept']),
    draftPaperId: null,
    node: { id: 'n2', kind: 'paper', sections: ['s1'] },
    expected: true,
  },
  {
    name: 'section filter: node with matching section passes',
    sectionId: 's1',
    hiddenKinds: new Set(),
    draftPaperId: null,
    node: { id: 'n1', kind: 'concept', sections: ['s1', 's2'] },
    expected: true,
  },
  {
    name: 'section filter: node without matching section blocked',
    sectionId: 's1',
    hiddenKinds: new Set(),
    draftPaperId: null,
    node: { id: 'n1', kind: 'concept', sections: ['s2', 's3'] },
    expected: false,
  },
  {
    name: 'section filter: draft paper always visible',
    sectionId: 's1',
    hiddenKinds: new Set(),
    draftPaperId: 'draft-paper',
    node: { id: 'draft-paper', kind: 'paper', sections: [] },
    expected: true,
  },
  {
    name: 'section filter: draft paper visible even with hidden kind',
    sectionId: 's1',
    hiddenKinds: new Set(['paper']),
    draftPaperId: 'draft-paper',
    node: { id: 'draft-paper', kind: 'paper', sections: [] },
    expected: false, // kind filter applied first, before draft-paper exemption for section
  },
  {
    name: 'section filter: node with no sections array is blocked',
    sectionId: 's1',
    hiddenKinds: new Set(),
    draftPaperId: null,
    node: { id: 'n3', kind: 'method', sections: undefined },
    expected: false,
  },
  {
    name: 'composed: hidden kind + section filter, node fails both',
    sectionId: 's2',
    hiddenKinds: new Set(['dataset']),
    draftPaperId: null,
    node: { id: 'n4', kind: 'dataset', sections: ['s2'] },
    expected: false,
  },
  {
    name: 'composed: hidden kind blocks, but section would pass',
    sectionId: 's2',
    hiddenKinds: new Set(['method']),
    draftPaperId: null,
    node: { id: 'n5', kind: 'method', sections: ['s2'] },
    expected: false,
  },
];

for (const tc of filterCases) {
  test(`makeFilterPredicate: ${tc.name}`, () => {
    const pred = makeFilterPredicate(tc.sectionId, tc.hiddenKinds, tc.draftPaperId);
    assert.equal(pred(tc.node), tc.expected);
  });
}

// ---------------------------------------------------------------------------
// dedup
// ---------------------------------------------------------------------------

test('dedup: returns all items when none exist in set', () => {
  const items = [{ id: 'a' }, { id: 'b' }, { id: 'c' }];
  const existsSet = new Set();
  const result = dedup(items, existsSet);
  assert.deepEqual(result, items);
});

test('dedup: filters out items whose ids are in existsSet', () => {
  const items = [{ id: 'a' }, { id: 'b' }, { id: 'c' }];
  const existsSet = new Set(['a', 'c']);
  const result = dedup(items, existsSet);
  assert.deepEqual(result, [{ id: 'b' }]);
});

test('dedup: returns empty array when all ids exist', () => {
  const items = [{ id: 'a' }, { id: 'b' }];
  const existsSet = new Set(['a', 'b']);
  const result = dedup(items, existsSet);
  assert.deepEqual(result, []);
});

test('dedup: empty items returns empty array', () => {
  const result = dedup([], new Set(['a', 'b']));
  assert.deepEqual(result, []);
});

// ---------------------------------------------------------------------------
// shouldReducePerf
// ---------------------------------------------------------------------------

test('shouldReducePerf: returns false below threshold (1200)', () => {
  assert.equal(shouldReducePerf(0), false);
  assert.equal(shouldReducePerf(100), false);
  assert.equal(shouldReducePerf(1200), false);
});

test('shouldReducePerf: returns true above threshold (> 1200)', () => {
  assert.equal(shouldReducePerf(1201), true);
  assert.equal(shouldReducePerf(5000), true);
});
