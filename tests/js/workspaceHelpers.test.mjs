/**
 * tests/js/workspaceHelpers.test.mjs — W4-F1 pure workspace helpers.
 *
 * Run: node --test tests/js/workspaceHelpers.test.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';

import {
  splitWorkspaces,
  validateWorkspaceName,
  workspaceCardModel,
} from '../../research_companion/lab/static/js/workspaceHelpers.js';

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function ws(id, over = {}) {
  return {
    id,
    name: over.name !== undefined ? over.name : id,
    created_at: '2026-01-01T00:00:00Z',
    archived: over.archived || false,
    stats: {
      papers: 0,
      draft_title: null,
      open_suggestions: 0,
      last_activity: null,
      ...(over.stats || {}),
    },
  };
}

// ---------------------------------------------------------------------------
// splitWorkspaces
// ---------------------------------------------------------------------------

test('splitWorkspaces: separates archived from active', () => {
  const list = [ws('a'), ws('b', { archived: true }), ws('c')];
  const { active, archived } = splitWorkspaces(list, 'a');
  assert.deepEqual(active.map(w => w.id), ['a', 'c']);
  assert.deepEqual(archived.map(w => w.id), ['b']);
});

test('splitWorkspaces: current-active workspace sorts first', () => {
  const list = [
    ws('older', { stats: { last_activity: '2026-06-01T00:00:00Z' } }),
    ws('current', { stats: { last_activity: '2026-01-01T00:00:00Z' } }),
  ];
  const { active } = splitWorkspaces(list, 'current');
  assert.equal(active[0].id, 'current');
  assert.equal(active[1].id, 'older');
});

test('splitWorkspaces: non-active sorted by last_activity desc', () => {
  const list = [
    ws('old',   { stats: { last_activity: '2026-01-01T00:00:00Z' } }),
    ws('new',   { stats: { last_activity: '2026-06-01T00:00:00Z' } }),
    ws('mid',   { stats: { last_activity: '2026-03-01T00:00:00Z' } }),
    ws('main'),
  ];
  const { active } = splitWorkspaces(list, 'main');
  assert.deepEqual(active.map(w => w.id), ['main', 'new', 'mid', 'old']);
});

test('splitWorkspaces: null last_activity sorts after any timestamp', () => {
  const list = [
    ws('never'),
    ws('active-once', { stats: { last_activity: '2020-01-01T00:00:00Z' } }),
  ];
  const { active } = splitWorkspaces(list, 'nope');
  assert.deepEqual(active.map(w => w.id), ['active-once', 'never']);
});

test('splitWorkspaces: ties broken by name (case-insensitive)', () => {
  const iso = '2026-02-02T00:00:00Z';
  const list = [
    ws('z1', { name: 'zeta',  stats: { last_activity: iso } }),
    ws('a1', { name: 'Alpha', stats: { last_activity: iso } }),
    ws('b1', { name: 'beta',  stats: { last_activity: iso } }),
  ];
  const { active } = splitWorkspaces(list, 'none');
  assert.deepEqual(active.map(w => w.name), ['Alpha', 'beta', 'zeta']);
});

test('splitWorkspaces: tolerates non-array and missing stats', () => {
  assert.deepEqual(splitWorkspaces(null, 'x'), { active: [], archived: [] });
  assert.deepEqual(splitWorkspaces(undefined, 'x'), { active: [], archived: [] });
  const bare = { id: 'bare', name: 'bare', archived: false }; // no stats at all
  const { active } = splitWorkspaces([bare], 'bare');
  assert.equal(active.length, 1);
});

test('splitWorkspaces: does not mutate the input list', () => {
  const list = [ws('b'), ws('a')];
  splitWorkspaces(list, 'a');
  assert.deepEqual(list.map(w => w.id), ['b', 'a']);
});

// ---------------------------------------------------------------------------
// validateWorkspaceName
// ---------------------------------------------------------------------------

test('validateWorkspaceName: trims and accepts a valid name', () => {
  const res = validateWorkspaceName('  My Research  ', []);
  assert.equal(res.ok, true);
  assert.equal(res.name, 'My Research');
});

test('validateWorkspaceName: rejects empty / whitespace-only', () => {
  for (const bad of ['', '   ', '\t\n', null, undefined]) {
    const res = validateWorkspaceName(bad, []);
    assert.equal(res.ok, false, `expected reject for ${JSON.stringify(bad)}`);
    assert.ok(res.error.length > 0);
  }
});

test('validateWorkspaceName: accepts exactly 80 chars, rejects 81', () => {
  const ok = validateWorkspaceName('x'.repeat(80), []);
  assert.equal(ok.ok, true);
  const bad = validateWorkspaceName('x'.repeat(81), []);
  assert.equal(bad.ok, false);
  assert.match(bad.error, /80/);
});

test('validateWorkspaceName: length checked after trim', () => {
  const res = validateWorkspaceName('  ' + 'x'.repeat(80) + '  ', []);
  assert.equal(res.ok, true);
});

test('validateWorkspaceName: rejects case-insensitive duplicates', () => {
  const existing = ['Main', 'Protein Folding'];
  const res = validateWorkspaceName('protein folding', existing);
  assert.equal(res.ok, false);
  assert.match(res.error, /exists/i);
});

test('validateWorkspaceName: duplicate check compares trimmed value', () => {
  const res = validateWorkspaceName('  MAIN ', ['main']);
  assert.equal(res.ok, false);
});

test('validateWorkspaceName: non-duplicate passes with existing names', () => {
  const res = validateWorkspaceName('brand new', ['Main', 'other']);
  assert.equal(res.ok, true);
  assert.equal(res.name, 'brand new');
});

test('validateWorkspaceName: tolerates missing existingNames arg', () => {
  const res = validateWorkspaceName('solo');
  assert.equal(res.ok, true);
});

// ---------------------------------------------------------------------------
// workspaceCardModel
// ---------------------------------------------------------------------------

test('workspaceCardModel: maps all fields flat', () => {
  const rec = ws('w1', {
    name: 'Quantum',
    stats: {
      papers: 12,
      draft_title: 'My Draft',
      open_suggestions: 3,
      last_activity: '2026-06-30T10:00:00Z',
    },
  });
  const m = workspaceCardModel(rec, 'w1');
  assert.deepEqual(m, {
    id: 'w1',
    name: 'Quantum',
    isActive: true,
    draftTitle: 'My Draft',
    paperCount: 12,
    openSuggestions: 3,
    lastActivityIso: '2026-06-30T10:00:00Z',
    archived: false,
  });
});

test('workspaceCardModel: isActive false for other ids', () => {
  const m = workspaceCardModel(ws('w2'), 'w1');
  assert.equal(m.isActive, false);
});

test('workspaceCardModel: defaults for missing stats', () => {
  const m = workspaceCardModel({ id: 'bare', name: 'Bare', archived: true }, 'x');
  assert.equal(m.draftTitle, null);
  assert.equal(m.paperCount, 0);
  assert.equal(m.openSuggestions, 0);
  assert.equal(m.lastActivityIso, null);
  assert.equal(m.archived, true);
});

test('workspaceCardModel: falls back to id when name missing', () => {
  const m = workspaceCardModel({ id: 'w9', archived: false }, 'w9');
  assert.equal(m.name, 'w9');
});
