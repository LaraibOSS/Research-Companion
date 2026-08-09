/**
 * homehelpers.test.mjs — Tests for the pure emptyHeroModel() helper
 * (research_companion/lab/static/js/homeHelpers.js), used to render the
 * "Research Companion" welcome hero shown on /home when there is no draft.
 *
 * Run from repo root:
 *   node --test tests/js/homehelpers.test.mjs
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot  = path.resolve(__dirname, '..', '..');

// onboarding.js (imported transitively by homeHelpers.js) uses localStorage —
// needs a browser global — mock it before importing.
const mockLocalStorage = new Map();
globalThis.localStorage = {
  getItem: (k) => mockLocalStorage.get(k) ?? null,
  setItem: (k, v) => mockLocalStorage.set(k, v),
  removeItem: (k) => mockLocalStorage.delete(k),
};

const { emptyHeroModel, homeNavModel } = await import(
  pathToFileURL(path.join(repoRoot, 'research_companion', 'lab', 'static', 'js', 'homeHelpers.js')).href
);

const { onboardingStep } = await import(
  pathToFileURL(path.join(repoRoot, 'research_companion', 'lab', 'static', 'js', 'components', 'onboarding.js')).href
);

// -----------------------------------------------------------------------
// Helpers
// -----------------------------------------------------------------------

function makeState(overrides = {}) {
  return {
    settings: { provider: 'anthropic', keys: { anthropic_api_key: { set: true }, openai_api_key: { set: false } } },
    draftId: null,
    papers: new Map(),
    failures: {},
    suggestions: [],
    suggestionCounts: { open: 0, by_severity: null },
    ...overrides,
  };
}

// -----------------------------------------------------------------------
// heading
// -----------------------------------------------------------------------

test('emptyHeroModel: heading is Research Companion', () => {
  mockLocalStorage.clear();
  const model = emptyHeroModel(makeState());
  assert.equal(model.heading, 'Research Companion');
});

// -----------------------------------------------------------------------
// subline
// -----------------------------------------------------------------------

test('emptyHeroModel: 0 non-draft papers -> default value-prop subline', () => {
  mockLocalStorage.clear();
  const model = emptyHeroModel(makeState({ papers: new Map() }));
  assert.equal(
    model.subline,
    'Verify what your paper claims. Add your draft and the literature around it — get grounded, cited answers.',
  );
});

test('emptyHeroModel: N>0 papers -> subline mentions count and pluralizes (plural)', () => {
  mockLocalStorage.clear();
  const papers = new Map([
    ['p1', { paper_id: 'p1', is_draft: false, status: 'done' }],
    ['p2', { paper_id: 'p2', is_draft: false, status: 'done' }],
  ]);
  const model = emptyHeroModel(makeState({ papers }));
  assert.equal(
    model.subline,
    "You've added 2 papers — add your draft to start analyzing them.",
  );
});

test('emptyHeroModel: exactly 1 non-draft paper -> subline singularizes "paper"', () => {
  mockLocalStorage.clear();
  const papers = new Map([
    ['p1', { paper_id: 'p1', is_draft: false, status: 'done' }],
  ]);
  const model = emptyHeroModel(makeState({ papers }));
  assert.equal(
    model.subline,
    "You've added 1 paper — add your draft to start analyzing them.",
  );
});

// -----------------------------------------------------------------------
// paperCount
// -----------------------------------------------------------------------

test('emptyHeroModel: paperCount excludes the draft and is_draft entries', () => {
  mockLocalStorage.clear();
  const papers = new Map([
    ['draft-1', { paper_id: 'draft-1', is_draft: true, status: 'done' }],
    ['p1', { paper_id: 'p1', is_draft: false, status: 'done' }],
    ['p2', { paper_id: 'p2', is_draft: false, status: 'done' }],
  ]);
  const model = emptyHeroModel(makeState({ draftId: 'draft-1', papers }));
  assert.equal(model.paperCount, 2);
});

test('emptyHeroModel: paperCount is 0 for empty papers map', () => {
  mockLocalStorage.clear();
  const model = emptyHeroModel(makeState({ papers: new Map() }));
  assert.equal(model.paperCount, 0);
});

// -----------------------------------------------------------------------
// activeStep — must match onboardingStep(state)
// -----------------------------------------------------------------------

test('emptyHeroModel: no API key -> activeStep connect', () => {
  mockLocalStorage.clear();
  const state = makeState({
    settings: { provider: 'anthropic', keys: { anthropic_api_key: { set: false } } },
  });
  const model = emptyHeroModel(state);
  assert.equal(model.activeStep, 'connect');
  assert.equal(model.activeStep, onboardingStep(state));
});

test('emptyHeroModel: key set + no draft -> activeStep add_draft', () => {
  mockLocalStorage.clear();
  const state = makeState({ draftId: null });
  const model = emptyHeroModel(state);
  assert.equal(model.activeStep, 'add_draft');
  assert.equal(model.activeStep, onboardingStep(state));
});

// -----------------------------------------------------------------------
// homeNavModel tests
// -----------------------------------------------------------------------

test('homeNavModel returns the curated tab set in order', () => {
  const state = { draftId: 'd1', papers: new Map([
    ['d1', { is_draft: true }],
    ['p1', { is_draft: false }],
    ['p2', { is_draft: false }],
  ]) };
  const model = homeNavModel(state);
  assert.deepEqual(model.map(m => m.key),
    ['library', 'graph', 'draft', 'ask', 'timeline', 'citations']);
  // library shows the non-draft paper count
  assert.equal(model.find(m => m.key === 'library').count, 2);
  // routed vs action entries
  assert.equal(model.find(m => m.key === 'library').route, '#/library');
  assert.equal(model.find(m => m.key === 'citations').action, 'open-citations');
  assert.equal(model.find(m => m.key === 'citations').route, undefined);
});

test('homeNavModel draft label switches on whether a draft exists', () => {
  const withDraft = homeNavModel({ draftId: 'd1', papers: new Map([['d1', { is_draft: true }]]) });
  assert.equal(withDraft.find(m => m.key === 'draft').label, 'Draft');
  const noDraft = homeNavModel({ draftId: null, papers: new Map() });
  assert.equal(noDraft.find(m => m.key === 'draft').label, 'Set a draft');
  // never throws on missing/empty state
  assert.doesNotThrow(() => homeNavModel({}));
  assert.equal(homeNavModel({}).find(m => m.key === 'library').count, 0);
});
