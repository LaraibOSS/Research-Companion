/**
 * suggestionHelpers.test.mjs — Table-driven tests for W3-F3 pure helpers:
 *   groupSuggestions, countOpen, highestOpenSeverity, severityRank, diffStatuses
 *
 * Run from repo root:
 *   node --test tests/js/suggestionHelpers.test.mjs
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot  = path.resolve(__dirname, '..', '..');

const {
  groupSuggestions,
  countOpen,
  highestOpenSeverity,
  severityRank,
  diffStatuses,
} = await import(
  pathToFileURL(path.join(
    repoRoot,
    'research_companion', 'lab', 'static', 'js', 'components', 'suggestionHelpers.js',
  )).href
);

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const SUGS = [
  { id: 's1', kind: 'citation',    severity: 'high',   section_id: 'sec-1', status: 'open'      },
  { id: 's2', kind: 'novelty',     severity: 'medium', section_id: null,    status: 'open'      },
  { id: 's3', kind: 'evidence',    severity: 'low',    section_id: 'sec-2', status: 'open'      },
  { id: 's4', kind: 'benchmark',   severity: 'high',   section_id: null,    status: 'addressed' },
  { id: 's5', kind: 'related_work',severity: 'medium', section_id: 'sec-1', status: 'dismissed' },
  { id: 's6', kind: 'citation',    severity: 'medium', section_id: 'sec-2', status: 'open'      },
];

// ---------------------------------------------------------------------------
// severityRank
// ---------------------------------------------------------------------------

test('severityRank: high > medium > low', () => {
  assert.ok(severityRank('high') > severityRank('medium'));
  assert.ok(severityRank('medium') > severityRank('low'));
});

test('severityRank: unknown severity returns 0', () => {
  assert.equal(severityRank('critical'), 0);
  assert.equal(severityRank(undefined), 0);
});

// ---------------------------------------------------------------------------
// countOpen
// ---------------------------------------------------------------------------

test('countOpen: counts only open status', () => {
  assert.equal(countOpen(SUGS), 4); // s1, s2, s3, s6
});

test('countOpen: empty list returns 0', () => {
  assert.equal(countOpen([]), 0);
});

test('countOpen: all addressed returns 0', () => {
  const all = SUGS.map(s => ({ ...s, status: 'addressed' }));
  assert.equal(countOpen(all), 0);
});

// ---------------------------------------------------------------------------
// highestOpenSeverity
// ---------------------------------------------------------------------------

test('highestOpenSeverity: returns high when high open exists', () => {
  assert.equal(highestOpenSeverity(SUGS), 'high'); // s1 is high + open
});

test('highestOpenSeverity: returns medium when highest open is medium', () => {
  const filtered = SUGS.filter(s => s.id !== 's1'); // remove only high open
  assert.equal(highestOpenSeverity(filtered), 'medium');
});

test('highestOpenSeverity: returns low when only low open', () => {
  const only = [{ id: 'x', severity: 'low', status: 'open' }];
  assert.equal(highestOpenSeverity(only), 'low');
});

test('highestOpenSeverity: returns null when no open suggestions', () => {
  const none = SUGS.map(s => ({ ...s, status: 'addressed' }));
  assert.equal(highestOpenSeverity(none), null);
});

test('highestOpenSeverity: high addressed does not count', () => {
  // s4 is high but addressed — only s1 (high+open) matters
  const noS1 = SUGS.filter(s => s.id !== 's1');
  // s4 still present (addressed), highest open is medium
  assert.equal(highestOpenSeverity(noS1), 'medium');
});

// ---------------------------------------------------------------------------
// groupSuggestions — severity mode
// ---------------------------------------------------------------------------

test('groupSuggestions severity: returns high, medium, low in order', () => {
  const groups = groupSuggestions(SUGS, 'severity');
  assert.equal(groups.length, 3);
  assert.equal(groups[0].key, 'high');
  assert.equal(groups[1].key, 'medium');
  assert.equal(groups[2].key, 'low');
});

test('groupSuggestions severity: correct item counts', () => {
  const groups = groupSuggestions(SUGS, 'severity');
  const byKey = Object.fromEntries(groups.map(g => [g.key, g.items.length]));
  assert.equal(byKey.high, 2);   // s1, s4
  assert.equal(byKey.medium, 3); // s2, s5, s6
  assert.equal(byKey.low, 1);    // s3
});

test('groupSuggestions severity: empty group not included', () => {
  const singleHigh = [{ id: 'x', severity: 'high', kind: 'citation', status: 'open' }];
  const groups = groupSuggestions(singleHigh, 'severity');
  assert.equal(groups.length, 1);
  assert.equal(groups[0].key, 'high');
});

test('groupSuggestions severity: has label field', () => {
  const groups = groupSuggestions(SUGS, 'severity');
  for (const g of groups) {
    assert.ok(typeof g.label === 'string' && g.label.length > 0, `missing label for ${g.key}`);
  }
});

// ---------------------------------------------------------------------------
// groupSuggestions — kind mode
// ---------------------------------------------------------------------------

test('groupSuggestions kind: groups are alphabetically sorted', () => {
  const groups = groupSuggestions(SUGS, 'kind');
  const keys = groups.map(g => g.key);
  assert.deepEqual(keys, [...keys].sort());
});

test('groupSuggestions kind: all kinds present', () => {
  const groups = groupSuggestions(SUGS, 'kind');
  const keys = new Set(groups.map(g => g.key));
  assert.ok(keys.has('citation'));
  assert.ok(keys.has('novelty'));
  assert.ok(keys.has('evidence'));
  assert.ok(keys.has('benchmark'));
  assert.ok(keys.has('related_work'));
});

test('groupSuggestions kind: citation group has 2 items', () => {
  const groups = groupSuggestions(SUGS, 'kind');
  const citation = groups.find(g => g.key === 'citation');
  assert.equal(citation.items.length, 2);
});

// ---------------------------------------------------------------------------
// groupSuggestions — section mode
// ---------------------------------------------------------------------------

test('groupSuggestions section: null section_id last as "General"', () => {
  const groups = groupSuggestions(SUGS, 'section');
  const last = groups[groups.length - 1];
  assert.equal(last.key, '__general__');
  assert.ok(last.label.toLowerCase().includes('general'));
});

test('groupSuggestions section: non-null sections sorted before null', () => {
  const groups = groupSuggestions(SUGS, 'section');
  const withSection = groups.filter(g => g.key !== '__general__');
  assert.ok(withSection.length >= 2, 'should have section groups');
  // All non-general groups should come before general
  const generalIdx = groups.findIndex(g => g.key === '__general__');
  for (const wg of withSection) {
    const idx = groups.indexOf(wg);
    assert.ok(idx < generalIdx, `section group ${wg.key} must precede general`);
  }
});

test('groupSuggestions section: sec-1 group contains s1 and s5', () => {
  const groups = groupSuggestions(SUGS, 'section');
  const sec1 = groups.find(g => g.key === 'sec-1');
  assert.ok(sec1, 'sec-1 group missing');
  const ids = sec1.items.map(i => i.id);
  assert.ok(ids.includes('s1'));
  assert.ok(ids.includes('s5'));
});

test('groupSuggestions section: general group contains s2 and s4', () => {
  const groups = groupSuggestions(SUGS, 'section');
  const gen = groups.find(g => g.key === '__general__');
  const ids = gen.items.map(i => i.id);
  assert.ok(ids.includes('s2'));
  assert.ok(ids.includes('s4'));
});

// ---------------------------------------------------------------------------
// diffStatuses
// ---------------------------------------------------------------------------

const PREV = [
  { id: 'a', status: 'open'      },
  { id: 'b', status: 'open'      },
  { id: 'c', status: 'open'      },
  { id: 'd', status: 'addressed' },
  { id: 'e', status: 'dismissed' },
];

test('diffStatuses: detects open->addressed transitions', () => {
  const next = [
    { id: 'a', status: 'addressed' },
    { id: 'b', status: 'open'      },
    { id: 'c', status: 'open'      },
    { id: 'd', status: 'addressed' },
    { id: 'e', status: 'dismissed' },
  ];
  const diff = diffStatuses(PREV, next);
  assert.deepEqual(diff.addressed, ['a']);
});

test('diffStatuses: dismissed->addressed not reported', () => {
  const next = [
    { id: 'a', status: 'open'      },
    { id: 'b', status: 'open'      },
    { id: 'c', status: 'open'      },
    { id: 'd', status: 'addressed' },
    { id: 'e', status: 'addressed' }, // was dismissed, now addressed
  ];
  const diff = diffStatuses(PREV, next);
  // 'e' was dismissed (not open), so NOT reported
  assert.ok(!diff.addressed.includes('e'));
});

test('diffStatuses: new ids (not in prev) not reported', () => {
  const next = [
    ...PREV,
    { id: 'NEW', status: 'addressed' },
  ];
  const diff = diffStatuses(PREV, next);
  assert.ok(!diff.addressed.includes('NEW'));
});

test('diffStatuses: multiple open->addressed all captured', () => {
  const next = [
    { id: 'a', status: 'addressed' },
    { id: 'b', status: 'addressed' },
    { id: 'c', status: 'addressed' },
    { id: 'd', status: 'addressed' },
    { id: 'e', status: 'dismissed' },
  ];
  const diff = diffStatuses(PREV, next);
  assert.deepEqual([...diff.addressed].sort(), ['a', 'b', 'c']);
});

test('diffStatuses: empty prev returns empty addressed', () => {
  const diff = diffStatuses([], PREV);
  assert.deepEqual(diff.addressed, []);
});

test('diffStatuses: empty next returns empty addressed', () => {
  const diff = diffStatuses(PREV, []);
  assert.deepEqual(diff.addressed, []);
});
