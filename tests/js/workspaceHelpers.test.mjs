/**
 * tests/js/workspaceHelpers.test.mjs — W4-F1 pure workspace helpers.
 *
 * Run: node --test tests/js/workspaceHelpers.test.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';

import {
  decideResearchGuard,
  deleteConfirmMessage,
  researchRowModel,
  sortResearchRows,
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
// decideResearchGuard
// ---------------------------------------------------------------------------

test('decideResearchGuard: passthrough when activeId is set', () => {
  assert.deepEqual(decideResearchGuard({ activeId: 'main' }), { decision: 'passthrough' });
});

test('decideResearchGuard: prompt when activeId is null', () => {
  assert.deepEqual(decideResearchGuard({ activeId: null }), { decision: 'prompt' });
});

test('decideResearchGuard: prompt when activeId is undefined', () => {
  assert.deepEqual(decideResearchGuard({ activeId: undefined }), { decision: 'prompt' });
});

test('decideResearchGuard: prompt for null/undefined state, never throws', () => {
  assert.doesNotThrow(() => decideResearchGuard(null));
  assert.doesNotThrow(() => decideResearchGuard(undefined));
  assert.deepEqual(decideResearchGuard(null), { decision: 'prompt' });
  assert.deepEqual(decideResearchGuard(undefined), { decision: 'prompt' });
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

// ---------------------------------------------------------------------------
// deleteConfirmMessage
// ---------------------------------------------------------------------------

test('deleteConfirmMessage: plural paper count', () => {
  assert.equal(
    deleteConfirmMessage('Quantum', 12),
    'Delete research "Quantum" and its 12 papers? This cannot be undone.',
  );
});

test('deleteConfirmMessage: singular for exactly one paper', () => {
  assert.equal(
    deleteConfirmMessage('Quantum', 1),
    'Delete research "Quantum" and its 1 paper? This cannot be undone.',
  );
});

test('deleteConfirmMessage: zero papers stays plural', () => {
  assert.equal(
    deleteConfirmMessage('Empty', 0),
    'Delete research "Empty" and its 0 papers? This cannot be undone.',
  );
});

test('deleteConfirmMessage: unknown count omits the paper clause', () => {
  for (const unknown of [null, undefined, NaN, 'not-a-number']) {
    assert.equal(
      deleteConfirmMessage('Mystery', unknown),
      'Delete research "Mystery"? This cannot be undone.',
    );
  }
});

// ---------------------------------------------------------------------------
// researchRowModel
// ---------------------------------------------------------------------------

function fullWs(over = {}) {
  return {
    id: 'w1',
    name: 'Quantum',
    created_at: '2026-01-01T00:00:00Z',
    archived: false,
    stats: {
      papers: 10,
      failed: 2,
      draft_title: 'My Draft',
      draft_versions: 3,
      draft_updated: '2026-02-01T00:00:00Z',
      coverage: { in_library: 6, total: 8 },
      open_suggestions: 4,
      strength: { strong: 3, moderate: 2, weak: 1, unscored: 4 },
      last_activity: '2026-03-01T00:00:00Z',
    },
    ...over,
  };
}

test('researchRowModel: maps all derived fields from full stats', () => {
  const m = researchRowModel(fullWs(), 'w1');
  assert.deepEqual(m, {
    id: 'w1',
    name: 'Quantum',
    isActive: true,
    hasDraft: true,
    draftTitle: 'My Draft',
    papers: 10,
    analyzed: 8,
    failed: 2,
    draftVersions: 3,
    coveragePct: 75,
    coverageLabel: '6/8',
    strengthSegments: [
      { band: 'strong', count: 3 },
      { band: 'moderate', count: 2 },
      { band: 'weak', count: 1 },
    ],
    openSuggestions: 4,
    draftUpdatedIso: '2026-02-01T00:00:00Z',
    lastActivityIso: '2026-03-01T00:00:00Z',
    createdAtIso: '2026-01-01T00:00:00Z',
    archived: false,
  });
});

test('researchRowModel: isActive false for other ids', () => {
  const m = researchRowModel(fullWs(), 'other');
  assert.equal(m.isActive, false);
});

test('researchRowModel: analyzed clamps at 0 when failed exceeds papers', () => {
  const m = researchRowModel(fullWs({ stats: { ...fullWs().stats, papers: 1, failed: 5 } }), 'w1');
  assert.equal(m.analyzed, 0);
});

test('researchRowModel: hasDraft false when draft_title missing', () => {
  const m = researchRowModel(fullWs({ stats: { ...fullWs().stats, draft_title: null } }), 'w1');
  assert.equal(m.hasDraft, false);
  assert.equal(m.draftTitle, null);
});

test('researchRowModel: coverage null yields label em-dash and pct null', () => {
  const m = researchRowModel(fullWs({ stats: { ...fullWs().stats, coverage: null } }), 'w1');
  assert.equal(m.coverageLabel, '—');
  assert.equal(m.coveragePct, null);
});

test('researchRowModel: coverage with total 0 yields pct null (avoid div-by-zero)', () => {
  const m = researchRowModel(
    fullWs({ stats: { ...fullWs().stats, coverage: { in_library: 0, total: 0 } } }),
    'w1',
  );
  assert.equal(m.coveragePct, null);
  assert.equal(m.coverageLabel, '0/0');
});

test('researchRowModel: stats-less workspace never throws, all safe defaults', () => {
  assert.doesNotThrow(() => researchRowModel({ id: 'bare', name: 'Bare', archived: true }, 'x'));
  const m = researchRowModel({ id: 'bare', name: 'Bare', archived: true }, 'x');
  assert.deepEqual(m, {
    id: 'bare',
    name: 'Bare',
    isActive: false,
    hasDraft: false,
    draftTitle: null,
    papers: 0,
    analyzed: 0,
    failed: 0,
    draftVersions: 0,
    coveragePct: null,
    coverageLabel: '—',
    strengthSegments: [
      { band: 'strong', count: 0 },
      { band: 'moderate', count: 0 },
      { band: 'weak', count: 0 },
    ],
    openSuggestions: 0,
    draftUpdatedIso: null,
    lastActivityIso: null,
    createdAtIso: null,
    archived: true,
  });
});

test('researchRowModel: tolerates completely missing stats key (undefined)', () => {
  assert.doesNotThrow(() => researchRowModel({ id: 'x', name: 'X' }, 'x'));
});

test('researchRowModel: falls back to id when name missing', () => {
  const m = researchRowModel({ id: 'w9', archived: false, stats: {} }, 'w9');
  assert.equal(m.name, 'w9');
});

// ---------------------------------------------------------------------------
// sortResearchRows
// ---------------------------------------------------------------------------

function row(over = {}) {
  return {
    id: over.id || 'r',
    name: 'r',
    papers: 0,
    coveragePct: null,
    lastActivityIso: null,
    createdAtIso: null,
    draftUpdatedIso: null,
    ...over,
  };
}

test('sortResearchRows: non-array input returns empty array', () => {
  assert.deepEqual(sortResearchRows(null, 'name', 'asc'), []);
  assert.deepEqual(sortResearchRows(undefined, 'name', 'asc'), []);
  assert.deepEqual(sortResearchRows('nope', 'name', 'asc'), []);
});

test('sortResearchRows: returns a new array, does not mutate input', () => {
  const rows = [row({ id: 'b', name: 'b' }), row({ id: 'a', name: 'a' })];
  const sorted = sortResearchRows(rows, 'name', 'asc');
  assert.notEqual(sorted, rows);
  assert.deepEqual(rows.map(r => r.id), ['b', 'a']);
  assert.deepEqual(sorted.map(r => r.id), ['a', 'b']);
});

test('sortResearchRows: name asc/desc, case-insensitive', () => {
  const rows = [row({ id: '1', name: 'zeta' }), row({ id: '2', name: 'Alpha' }), row({ id: '3', name: 'beta' })];
  assert.deepEqual(sortResearchRows(rows, 'name', 'asc').map(r => r.id), ['2', '3', '1']);
  assert.deepEqual(sortResearchRows(rows, 'name', 'desc').map(r => r.id), ['1', '3', '2']);
});

test('sortResearchRows: papers asc/desc with nulls last regardless of dir', () => {
  const rows = [
    row({ id: 'a', papers: 5 }),
    row({ id: 'b', papers: null }),
    row({ id: 'c', papers: 1 }),
  ];
  assert.deepEqual(sortResearchRows(rows, 'papers', 'asc').map(r => r.id), ['c', 'a', 'b']);
  assert.deepEqual(sortResearchRows(rows, 'papers', 'desc').map(r => r.id), ['a', 'c', 'b']);
});

test('sortResearchRows: coverage asc/desc with nulls last', () => {
  const rows = [
    row({ id: 'a', coveragePct: 50 }),
    row({ id: 'b', coveragePct: null }),
    row({ id: 'c', coveragePct: 90 }),
  ];
  assert.deepEqual(sortResearchRows(rows, 'coverage', 'asc').map(r => r.id), ['a', 'c', 'b']);
  assert.deepEqual(sortResearchRows(rows, 'coverage', 'desc').map(r => r.id), ['c', 'a', 'b']);
});

test('sortResearchRows: lastActivity asc/desc with nulls last', () => {
  const rows = [
    row({ id: 'a', lastActivityIso: '2026-01-01T00:00:00Z' }),
    row({ id: 'b', lastActivityIso: null }),
    row({ id: 'c', lastActivityIso: '2026-06-01T00:00:00Z' }),
  ];
  assert.deepEqual(sortResearchRows(rows, 'lastActivity', 'asc').map(r => r.id), ['a', 'c', 'b']);
  assert.deepEqual(sortResearchRows(rows, 'lastActivity', 'desc').map(r => r.id), ['c', 'a', 'b']);
});

test('sortResearchRows: created asc/desc with nulls last', () => {
  const rows = [
    row({ id: 'a', createdAtIso: '2026-02-01T00:00:00Z' }),
    row({ id: 'b', createdAtIso: null }),
    row({ id: 'c', createdAtIso: '2026-01-01T00:00:00Z' }),
  ];
  assert.deepEqual(sortResearchRows(rows, 'created', 'asc').map(r => r.id), ['c', 'a', 'b']);
  assert.deepEqual(sortResearchRows(rows, 'created', 'desc').map(r => r.id), ['a', 'c', 'b']);
});

test('sortResearchRows: draftUpdated asc/desc with nulls last', () => {
  const rows = [
    row({ id: 'a', draftUpdatedIso: '2026-02-01T00:00:00Z' }),
    row({ id: 'b', draftUpdatedIso: null }),
    row({ id: 'c', draftUpdatedIso: '2026-01-01T00:00:00Z' }),
  ];
  assert.deepEqual(sortResearchRows(rows, 'draftUpdated', 'asc').map(r => r.id), ['c', 'a', 'b']);
  assert.deepEqual(sortResearchRows(rows, 'draftUpdated', 'desc').map(r => r.id), ['a', 'c', 'b']);
});

test('sortResearchRows: stable sort — equal keys retain original relative order', () => {
  const rows = [
    row({ id: 'a', papers: 5 }),
    row({ id: 'b', papers: 5 }),
    row({ id: 'c', papers: 5 }),
  ];
  assert.deepEqual(sortResearchRows(rows, 'papers', 'asc').map(r => r.id), ['a', 'b', 'c']);
  assert.deepEqual(sortResearchRows(rows, 'papers', 'desc').map(r => r.id), ['a', 'b', 'c']);
});

test('sortResearchRows: multiple nulls preserve relative order among themselves', () => {
  const rows = [
    row({ id: 'a', papers: 1 }),
    row({ id: 'b', papers: null }),
    row({ id: 'c', papers: null }),
    row({ id: 'd', papers: 2 }),
  ];
  assert.deepEqual(sortResearchRows(rows, 'papers', 'asc').map(r => r.id), ['a', 'd', 'b', 'c']);
});
