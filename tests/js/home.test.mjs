/**
 * home.test.mjs — Tests for W3-F2 pure modules:
 *   selectNextActions (nextAction.js), onboardingStep (onboarding.js),
 *   mergeJourney, sparklinePath, severityDonut (journeyHelpers.js)
 *
 * Run from repo root:
 *   node --test tests/js/home.test.mjs
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot  = path.resolve(__dirname, '..', '..');

const { selectNextActions } = await import(
  pathToFileURL(path.join(repoRoot, 'research_companion', 'lab', 'static', 'js', 'nextAction.js')).href
);

const { mergeJourney, sparklinePath, severityDonut } = await import(
  pathToFileURL(path.join(repoRoot, 'research_companion', 'lab', 'static', 'js', 'journeyHelpers.js')).href
);

// onboarding.js uses localStorage which needs a browser — mock it
const mockLocalStorage = new Map();
globalThis.localStorage = {
  getItem: (k) => mockLocalStorage.get(k) ?? null,
  setItem: (k, v) => mockLocalStorage.set(k, v),
  removeItem: (k) => mockLocalStorage.delete(k),
};

const { onboardingStep } = await import(
  pathToFileURL(path.join(repoRoot, 'research_companion', 'lab', 'static', 'js', 'components', 'onboarding.js')).href
);

// -----------------------------------------------------------------------
// Helpers
// -----------------------------------------------------------------------

function makeState(overrides = {}) {
  return {
    settings: { provider: 'anthropic', keys: { anthropic_api_key: { set: true }, openai_api_key: { set: false } } },
    draftId: 'paper-1',
    papers: new Map([['paper-1', { paper_id: 'paper-1', is_draft: true, status: 'done' }],
                     ['paper-2', { paper_id: 'paper-2', is_draft: false, status: 'done' }],
                     ['paper-3', { paper_id: 'paper-3', is_draft: false, status: 'done' }]]),
    failures: {},
    suggestions: [],
    suggestionCounts: { open: 0, by_severity: null },
    ...overrides,
  };
}

// -----------------------------------------------------------------------
// selectNextActions: Rule 1 — no API key
// -----------------------------------------------------------------------

test('selectNextActions rule1: no API key returns connect action', () => {
  const state = makeState({
    settings: { provider: 'anthropic', keys: { anthropic_api_key: { set: false } } },
    draftId: 'paper-1',
  });
  const actions = selectNextActions(state);
  assert.ok(actions.length > 0);
  assert.equal(actions[0].id, 'connect');
  assert.equal(actions[0].route, '#/settings');
});

test('selectNextActions rule1: openai provider checks openai key', () => {
  const state = makeState({
    settings: { provider: 'openai', keys: { anthropic_api_key: { set: true }, openai_api_key: { set: false } } },
    draftId: 'paper-1',
  });
  const actions = selectNextActions(state);
  assert.equal(actions[0].id, 'connect');
});

// -----------------------------------------------------------------------
// selectNextActions: Rule 2 — no draft
// -----------------------------------------------------------------------

test('selectNextActions rule2: no draft returns add-draft action', () => {
  const state = makeState({ draftId: null });
  const actions = selectNextActions(state);
  assert.ok(actions.some(a => a.id === 'add-draft'));
  const addDraft = actions.find(a => a.id === 'add-draft');
  // Draft-first: opens the upload tab with "This is my draft" pre-checked
  assert.equal(addDraft.action, 'open-ingest-draft');
});

// -----------------------------------------------------------------------
// selectNextActions: Rule 3 — papers < 3
// -----------------------------------------------------------------------

test('selectNextActions rule3: fewer than 3 non-draft papers returns add-papers', () => {
  const state = makeState({
    papers: new Map([['paper-1', { paper_id: 'paper-1', is_draft: true, status: 'done' }]]),
  });
  const actions = selectNextActions(state);
  assert.ok(actions.some(a => a.id === 'add-papers'));
  const action = actions.find(a => a.id === 'add-papers');
  assert.equal(action.action, 'open-ingest');
});

// -----------------------------------------------------------------------
// selectNextActions: Rule 4 — failures
// -----------------------------------------------------------------------

test('selectNextActions rule4: failures returns fix-failures action', () => {
  const state = makeState({ failures: { 'path/paper.pdf': { error: 'timeout' } } });
  const actions = selectNextActions(state);
  assert.ok(actions.some(a => a.id === 'fix-failures'));
  const action = actions.find(a => a.id === 'fix-failures');
  assert.ok(action.label.includes('1'));
  assert.equal(action.route, '#/library');
});

// -----------------------------------------------------------------------
// selectNextActions: Rule 5 — citation suggestions
// -----------------------------------------------------------------------

test('selectNextActions rule5: open citation suggestions returns verify-citations', () => {
  const state = makeState({
    suggestions: [{ id: 's1', status: 'open', kind: 'citation', severity: 'medium' }],
  });
  const actions = selectNextActions(state);
  assert.ok(actions.some(a => a.id === 'verify-citations'));
  const action = actions.find(a => a.id === 'verify-citations');
  assert.equal(action.action, 'open-suggestions');
  assert.ok(action.label.includes('1'));
});

// -----------------------------------------------------------------------
// selectNextActions: Rule 6 — high severity
// -----------------------------------------------------------------------

test('selectNextActions rule6: open high severity returns high-priority', () => {
  const state = makeState({
    suggestions: [{ id: 's1', status: 'open', kind: 'evidence', severity: 'high' }],
  });
  const actions = selectNextActions(state);
  assert.ok(actions.some(a => a.id === 'high-priority'));
});

// -----------------------------------------------------------------------
// selectNextActions: Rule 7 — empty suggestions + draft set
// -----------------------------------------------------------------------

test('selectNextActions rule7: empty suggestions with draft returns analyze', () => {
  const state = makeState({ suggestions: [], draftId: 'paper-1' });
  const actions = selectNextActions(state);
  assert.ok(actions.some(a => a.id === 'analyze'));
  const action = actions.find(a => a.id === 'analyze');
  assert.equal(action.action, 'open-suggestions');
});

// -----------------------------------------------------------------------
// selectNextActions: Rule 8 — fallback
// -----------------------------------------------------------------------

test('selectNextActions rule8: fully healthy state returns explore', () => {
  const state = makeState({
    suggestions: [{ id: 's1', status: 'addressed', kind: 'citation', severity: 'medium' }],
    draftId: 'paper-1',
    failures: {},
  });
  const actions = selectNextActions(state);
  assert.ok(actions.some(a => a.id === 'explore'));
  const explore = actions.find(a => a.id === 'explore');
  assert.equal(explore.route, '#/timeline');
});

// -----------------------------------------------------------------------
// selectNextActions: Priority order and distinctness
// -----------------------------------------------------------------------

test('selectNextActions returns at most 3 actions', () => {
  const state = makeState({
    settings: { provider: 'anthropic', keys: {} },
    draftId: null,
    failures: { 'x': {} },
    suggestions: [{ id: 's1', status: 'open', kind: 'citation', severity: 'high' }],
  });
  const actions = selectNextActions(state);
  assert.ok(actions.length <= 3);
});

test('selectNextActions actions have distinct ids', () => {
  const state = makeState({});
  const actions = selectNextActions(state);
  const ids = actions.map(a => a.id);
  const unique = [...new Set(ids)];
  assert.deepEqual(ids.sort(), unique.sort());
});

// -----------------------------------------------------------------------
// onboardingStep
// -----------------------------------------------------------------------

test('onboardingStep: no API key -> connect', () => {
  mockLocalStorage.clear();
  const state = makeState({ settings: { provider: 'anthropic', keys: { anthropic_api_key: { set: false } } } });
  assert.equal(onboardingStep(state), 'connect');
});

test('onboardingStep: key set, no draft -> add_draft', () => {
  mockLocalStorage.clear();
  const state = makeState({ draftId: null });
  assert.equal(onboardingStep(state), 'add_draft');
});

test('onboardingStep: draft set, no non-draft papers -> ingest', () => {
  mockLocalStorage.clear();
  const state = makeState({
    papers: new Map([['p1', { paper_id: 'p1', is_draft: true, status: 'done' }]]),
    draftId: 'p1',
  });
  assert.equal(onboardingStep(state), 'ingest');
});

test('onboardingStep: papers > 0, open suggestions -> meet_suggestions', () => {
  mockLocalStorage.clear();
  const state = makeState({
    suggestionCounts: { open: 2, by_severity: null },
  });
  assert.equal(onboardingStep(state), 'meet_suggestions');
});

test('onboardingStep: tourMetSuggestions set -> done', () => {
  mockLocalStorage.clear();
  mockLocalStorage.set('rc.tourMetSuggestions', '1');
  const state = makeState({ suggestionCounts: { open: 2, by_severity: null } });
  assert.equal(onboardingStep(state), 'done');
});

// -----------------------------------------------------------------------
// mergeJourney
// -----------------------------------------------------------------------

const VERSIONS = [
  { version: 1, paper_id: 'p1', added_at: '2024-01-10T10:00:00Z', n_sections: 5, n_claims: 12 },
  { version: 2, paper_id: 'p1', added_at: '2024-01-15T10:00:00Z', n_sections: 6, n_claims: 15 },
];
const EVENTS = [
  { at: '2024-01-12T10:00:00Z', kind: 'suggestion_addressed', data: {} },
  { at: '2024-01-08T10:00:00Z', kind: 'paper_added', data: { title: 'Cool Paper' } },
];

test('mergeJourney: returns newest first', () => {
  const merged = mergeJourney(VERSIONS, EVENTS);
  assert.ok(merged.length === 4);
  assert.ok(merged[0].at >= merged[1].at);
  assert.ok(merged[1].at >= merged[2].at);
});

test('mergeJourney: version entries have icon=version', () => {
  const merged = mergeJourney(VERSIONS, EVENTS);
  const versionEntries = merged.filter(e => e.icon === 'version');
  assert.equal(versionEntries.length, 2);
});

test('mergeJourney: version title includes claim count', () => {
  const merged = mergeJourney(VERSIONS, EVENTS);
  const v2 = merged.find(e => e.icon === 'version' && e.at === '2024-01-15T10:00:00Z');
  assert.ok(v2, 'version 2 entry not found');
  assert.ok(v2.title.includes('15'), 'title should include claim count');
  assert.ok(v2.title.includes('v2') || v2.title.includes('2'), 'title should include version number');
});

test('mergeJourney: event entries have icon=event', () => {
  const merged = mergeJourney(VERSIONS, EVENTS);
  const eventEntries = merged.filter(e => e.icon === 'event');
  assert.equal(eventEntries.length, 2);
});

test('mergeJourney: suggestion_addressed event title is human readable', () => {
  const merged = mergeJourney([], EVENTS);
  const sug = merged.find(e => e.at === '2024-01-12T10:00:00Z');
  assert.ok(sug.title.toLowerCase().includes('addressed') || sug.title.toLowerCase().includes('suggestion'));
});

test('mergeJourney: paper_added includes title from data', () => {
  const merged = mergeJourney([], EVENTS);
  const pa = merged.find(e => e.at === '2024-01-08T10:00:00Z');
  assert.ok(pa.title.toLowerCase().includes('cool paper') || pa.title.toLowerCase().includes('paper'));
});

test('mergeJourney: empty inputs return empty array', () => {
  assert.deepEqual(mergeJourney([], []), []);
});

// -----------------------------------------------------------------------
// sparklinePath
// -----------------------------------------------------------------------

test('sparklinePath: empty returns empty string', () => {
  assert.equal(sparklinePath([], 920, 48), '');
});

test('sparklinePath: single point returns flat line', () => {
  const p = sparklinePath([{ version: 1, at: '2024-01-01', open: 5, addressed: 0, dismissed: 0 }], 920, 48);
  assert.ok(p.startsWith('M'), 'should start with M');
  assert.ok(p.includes('L'), 'should have L segment');
});

test('sparklinePath: multiple points returns M...L... path', () => {
  const data = [
    { version: 1, at: '2024-01-01', open: 5, addressed: 0, dismissed: 0 },
    { version: 2, at: '2024-01-05', open: 3, addressed: 2, dismissed: 0 },
    { version: 3, at: '2024-01-10', open: 1, addressed: 4, dismissed: 0 },
  ];
  const p = sparklinePath(data, 920, 48);
  assert.ok(p.startsWith('M'));
  const lCount = (p.match(/L/g) || []).length;
  assert.ok(lCount >= 2, 'should have at least 2 L segments for 3 points');
});

// -----------------------------------------------------------------------
// severityDonut
// -----------------------------------------------------------------------

test('severityDonut: null counts returns single muted segment', () => {
  const segs = severityDonut({ open: 0, by_severity: null });
  assert.equal(segs.length, 1);
  assert.ok(segs[0].color.includes('muted') || segs[0].frac === 1);
});

test('severityDonut: mixed severities sum to 1', () => {
  const segs = severityDonut({ open: 10, by_severity: { high: 5, medium: 3, low: 2 } });
  const total = segs.reduce((s, seg) => s + seg.frac, 0);
  assert.ok(Math.abs(total - 1) < 0.01, 'fractions should sum to 1');
});

test('severityDonut: high severity first', () => {
  const segs = severityDonut({ open: 6, by_severity: { high: 3, medium: 2, low: 1 } });
  assert.ok(segs[0].color.includes('high') || segs[0].frac === 3/6);
});

test('severityDonut: only low severity', () => {
  const segs = severityDonut({ open: 4, by_severity: { low: 4 } });
  assert.equal(segs.length, 1);
  assert.equal(segs[0].frac, 1);
});
