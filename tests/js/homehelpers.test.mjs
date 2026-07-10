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

const { emptyHeroModel } = await import(
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
