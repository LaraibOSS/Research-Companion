/**
 * citationsHelpers.test.mjs — TDD tests for W5-C3 pure helpers.
 *   coverageCounts, missingCount, bannerText, statusChip,
 *   availableEntries, groupByStatus (citationsHelpers.js)
 *   + selectNextActions 'add-cited-papers' rule (nextAction.js)
 *
 * Run from repo root:
 *   node --test tests/js/citationsHelpers.test.mjs
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot  = path.resolve(__dirname, '..', '..');

const {
  coverageCounts,
  missingCount,
  bannerText,
  statusChip,
  availableEntries,
  groupByStatus,
  linkTargetOptions,
  matchedPaperIdSet,
  unlinkedCitationOptions,
  coverageSource,
} = await import(
  pathToFileURL(path.join(repoRoot, 'research_companion', 'lab', 'static', 'js', 'citationsHelpers.js')).href
);

const { selectNextActions } = await import(
  pathToFileURL(path.join(repoRoot, 'research_companion', 'lab', 'static', 'js', 'nextAction.js')).href
);

// -----------------------------------------------------------------------
// coverageCounts — zeros-safe on null / no counts field
// -----------------------------------------------------------------------

test('coverageCounts: null coverage returns zeros', () => {
  const c = coverageCounts(null);
  assert.equal(c.total, 0);
  assert.equal(c.in_library, 0);
  assert.equal(c.available, 0);
  assert.equal(c.unchecked, 0);
  assert.equal(c.unresolved, 0);
});

test('coverageCounts: undefined coverage returns zeros', () => {
  const c = coverageCounts(undefined);
  assert.equal(c.total, 0);
  assert.equal(c.in_library, 0);
});

test('coverageCounts: coverage with no counts field returns zeros', () => {
  const c = coverageCounts({ source: 'none', references: [] });
  assert.equal(c.total, 0);
});

test('coverageCounts: returns existing counts from coverage.counts', () => {
  const cov = {
    counts: { total: 10, in_library: 4, available: 3, unchecked: 2, unresolved: 1 },
    references: [],
  };
  const c = coverageCounts(cov);
  assert.equal(c.total, 10);
  assert.equal(c.in_library, 4);
  assert.equal(c.available, 3);
  assert.equal(c.unchecked, 2);
  assert.equal(c.unresolved, 1);
});

test('coverageCounts: partial counts defaults missing fields to 0', () => {
  const cov = { counts: { total: 5, in_library: 5 }, references: [] };
  const c = coverageCounts(cov);
  assert.equal(c.total, 5);
  assert.equal(c.in_library, 5);
  assert.equal(c.available, 0);
  assert.equal(c.unchecked, 0);
  assert.equal(c.unresolved, 0);
});

test('coverageCounts: usable passes through when present', () => {
  const cov = { counts: { total: 10, in_library: 4, usable: 3 } };
  const c = coverageCounts(cov);
  assert.equal(c.usable, 3);
});

test('coverageCounts: usable falls back to in_library when absent (stale payload)', () => {
  const cov = { counts: { total: 10, in_library: 4 } };
  const c = coverageCounts(cov);
  assert.equal(c.usable, 4);
});

test('coverageCounts: usable is 0 (not fallback) when explicitly 0', () => {
  const cov = { counts: { total: 10, in_library: 4, usable: 0 } };
  const c = coverageCounts(cov);
  assert.equal(c.usable, 0);
});

// -----------------------------------------------------------------------
// missingCount
// -----------------------------------------------------------------------

test('missingCount: total - in_library', () => {
  assert.equal(missingCount({ total: 10, in_library: 4 }), 6);
});

test('missingCount: fully covered returns 0', () => {
  assert.equal(missingCount({ total: 5, in_library: 5 }), 0);
});

test('missingCount: zeros returns 0', () => {
  assert.equal(missingCount({ total: 0, in_library: 0 }), 0);
});

// -----------------------------------------------------------------------
// bannerText
// -----------------------------------------------------------------------

test('bannerText: returns correct string', () => {
  const text = bannerText({ total: 12, in_library: 5 });
  assert.equal(text, 'Analysis covers 5 of 12 cited references');
});

test('bannerText: zero totals', () => {
  const text = bannerText({ total: 0, in_library: 0 });
  assert.equal(text, 'Analysis covers 0 of 0 cited references');
});

test('bannerText: bibliography source uses "cited references" wording', () => {
  const text = bannerText({ total: 17, in_library: 5 }, 'bibliography');
  assert.equal(text, 'Analysis covers 5 of 17 cited references');
});

test('bannerText: related_work fallback is labelled as related-work, not cited references', () => {
  const text = bannerText({ total: 12, in_library: 0 }, 'related_work');
  assert.ok(!/cited references/.test(text), 'must not say "cited references"');
  assert.ok(/related-work/.test(text), 'must mention related-work');
  assert.ok(/bibliography not detected/.test(text));
  assert.ok(/\b12\b/.test(text));
});

test('bannerText: none source also uses the related-work wording', () => {
  const text = bannerText({ total: 3, in_library: 0 }, 'none');
  assert.ok(!/cited references/.test(text));
});

test('bannerText: uses usable count when lower than in_library, with unreadable suffix', () => {
  const text = bannerText({ total: 12, in_library: 5, usable: 3 });
  assert.equal(text, 'Analysis covers 3 of 12 cited references (2 in library but unreadable)');
});

test('bannerText: usable equal to in_library omits the unreadable suffix', () => {
  const text = bannerText({ total: 12, in_library: 5, usable: 5 });
  assert.equal(text, 'Analysis covers 5 of 12 cited references');
});

test('bannerText: usable undefined falls back to in_library (stale payload, no suffix)', () => {
  const text = bannerText({ total: 8, in_library: 3 });
  assert.equal(text, 'Analysis covers 3 of 8 cited references');
});

// -----------------------------------------------------------------------
// coverageSource
// -----------------------------------------------------------------------

test('coverageSource: reads .source', () => {
  assert.equal(coverageSource({ source: 'bibliography' }), 'bibliography');
  assert.equal(coverageSource({ source: 'related_work' }), 'related_work');
});

test('coverageSource: defaults to none', () => {
  assert.equal(coverageSource(null), 'none');
  assert.equal(coverageSource({}), 'none');
});

// -----------------------------------------------------------------------
// statusChip — four statuses
// -----------------------------------------------------------------------

test('statusChip: in_library', () => {
  const chip = statusChip({ status: 'in_library' });
  assert.equal(chip.label, 'In library ✓');
  assert.equal(chip.cls, 'chip-ok');
});

test('statusChip: available', () => {
  const chip = statusChip({ status: 'available' });
  assert.equal(chip.label, 'Missing');
  assert.equal(chip.cls, 'chip-add');
});

test('statusChip: in_library with ingest_failed uses warn chip', () => {
  const chip = statusChip({ status: 'in_library', ingest_failed: true });
  assert.equal(chip.label, 'In library — ingest failed');
  assert.equal(chip.cls, 'chip-warn');
});

test('statusChip: in_library without ingest_failed stays the ok chip', () => {
  const chip = statusChip({ status: 'in_library', ingest_failed: false });
  assert.equal(chip.label, 'In library ✓');
  assert.equal(chip.cls, 'chip-ok');
});

test('statusChip: in_library with ingest_failed still yields to downloading', () => {
  const chip = statusChip({ status: 'in_library', ingest_failed: true, downloading: true });
  assert.equal(chip.label, 'Downloading…');
  assert.equal(chip.cls, 'chip-loading');
});

test('statusChip: unchecked', () => {
  const chip = statusChip({ status: 'unchecked' });
  assert.equal(chip.label, 'Not checked');
  assert.equal(chip.cls, 'chip-muted');
});

test('statusChip: unresolved', () => {
  const chip = statusChip({ status: 'unresolved' });
  assert.equal(chip.label, 'Unresolved ?');
  assert.equal(chip.cls, 'chip-warn');
});

test('statusChip: unknown status returns fallback', () => {
  const chip = statusChip({ status: 'bogus' });
  assert.ok(chip.label);
  assert.ok(chip.cls);
});

// -----------------------------------------------------------------------
// availableEntries
// -----------------------------------------------------------------------

const REFS = [
  { index: 1, raw: 'Foo et al.', status: 'available', add_target: 'arxiv:1234' },
  { index: 2, raw: 'Bar et al.', status: 'in_library', add_target: null },
  { index: 3, raw: 'Baz et al.', status: 'available', add_target: null }, // no add_target
  { index: 4, raw: 'Qux et al.', status: 'unchecked', add_target: 'arxiv:5678' },
  { index: 5, raw: 'Quux et al.', status: 'available', add_target: 'arxiv:9999' },
];

test('availableEntries: returns only available refs with add_target', () => {
  const coverage = { references: REFS, counts: {} };
  const entries = availableEntries(coverage);
  assert.equal(entries.length, 2);
  assert.ok(entries.every(e => e.status === 'available' && e.add_target));
});

test('availableEntries: null coverage returns empty', () => {
  assert.deepEqual(availableEntries(null), []);
});

test('availableEntries: no references returns empty', () => {
  assert.deepEqual(availableEntries({ counts: {} }), []);
});

// -----------------------------------------------------------------------
// groupByStatus — order: available, unchecked, unresolved, in_library
// -----------------------------------------------------------------------

const MIXED_REFS = [
  { index: 1, raw: 'A', status: 'in_library' },
  { index: 2, raw: 'B', status: 'available', add_target: 'x' },
  { index: 3, raw: 'C', status: 'unresolved' },
  { index: 4, raw: 'D', status: 'unchecked' },
  { index: 5, raw: 'E', status: 'available', add_target: 'y' },
  { index: 6, raw: 'F', status: 'in_library' },
];

test('groupByStatus: available comes first', () => {
  const groups = groupByStatus(MIXED_REFS);
  // First group should be available entries
  const availableIdx = groups.findIndex(e => e.status === 'available');
  const inLibIdx = groups.findIndex(e => e.status === 'in_library');
  assert.ok(availableIdx < inLibIdx, 'available before in_library');
});

test('groupByStatus: unchecked before unresolved', () => {
  const groups = groupByStatus(MIXED_REFS);
  const uncheckedIdx = groups.findIndex(e => e.status === 'unchecked');
  const unresolvedIdx = groups.findIndex(e => e.status === 'unresolved');
  assert.ok(uncheckedIdx < unresolvedIdx, 'unchecked before unresolved');
});

test('groupByStatus: all refs present', () => {
  const groups = groupByStatus(MIXED_REFS);
  assert.equal(groups.length, MIXED_REFS.length);
});

test('groupByStatus: within same status, original index order preserved', () => {
  const groups = groupByStatus(MIXED_REFS);
  const avail = groups.filter(e => e.status === 'available');
  assert.equal(avail[0].index, 2);
  assert.equal(avail[1].index, 5);
});

test('groupByStatus: empty returns empty', () => {
  assert.deepEqual(groupByStatus([]), []);
});

test('groupByStatus: null returns empty', () => {
  assert.deepEqual(groupByStatus(null), []);
});

// -----------------------------------------------------------------------
// linkTargetOptions — options for the "Link…" picker (v0.5.8 Task 2)
// -----------------------------------------------------------------------

const LINK_PAPERS = [
  { paper_id: 'p-draft', title: 'My Draft', authors: ['Me'], year: 2024 },
  { paper_id: 'p-full',  title: 'Complete Paper', authors: ['Ada'], year: 2020 },
  { paper_id: 'p-noyear', title: 'Needs Year', authors: ['Bob'], year: null },
  { paper_id: 'p-noauth', title: 'Needs Authors', authors: [], year: 2019 },
];

test('linkTargetOptions: empty / nullish input returns []', () => {
  assert.deepEqual(linkTargetOptions([], 'p-draft'), []);
  assert.deepEqual(linkTargetOptions(null, 'p-draft'), []);
  assert.deepEqual(linkTargetOptions(undefined, null), []);
});

test('linkTargetOptions: excludes the draft paper', () => {
  const opts = linkTargetOptions(LINK_PAPERS, 'p-draft');
  assert.ok(!opts.some(o => o.paperId === 'p-draft'), 'draft must be excluded');
  assert.equal(opts.length, 3);
});

test('linkTargetOptions: label formats year and — for null year', () => {
  const opts = linkTargetOptions(LINK_PAPERS, 'p-draft');
  const full = opts.find(o => o.paperId === 'p-full');
  const noyear = opts.find(o => o.paperId === 'p-noyear');
  assert.equal(full.label, 'Complete Paper (2020)');
  assert.equal(noyear.label, 'Needs Year (—)');
});

test('linkTargetOptions: needs-metadata papers sort first (null year OR no authors)', () => {
  const opts = linkTargetOptions(LINK_PAPERS, 'p-draft');
  const ids = opts.map(o => o.paperId);
  // p-noauth ("Needs Authors") and p-noyear ("Needs Year") need metadata;
  // A–Z within that group => Needs Authors before Needs Year; p-full last.
  assert.deepEqual(ids, ['p-noauth', 'p-noyear', 'p-full']);
});

test('linkTargetOptions: complete papers sorted A–Z after needs-metadata group', () => {
  const papers = [
    { paper_id: 'a', title: 'Zebra', authors: ['X'], year: 2001 },
    { paper_id: 'b', title: 'Apple', authors: ['Y'], year: 2002 },
  ];
  const opts = linkTargetOptions(papers, null);
  assert.deepEqual(opts.map(o => o.paperId), ['b', 'a']);
});

test('linkTargetOptions: accepts a Map (store shape) of papers', () => {
  const map = new Map(LINK_PAPERS.map(p => [p.paper_id, p]));
  const opts = linkTargetOptions(map, 'p-draft');
  assert.equal(opts.length, 3);
  assert.ok(!opts.some(o => o.paperId === 'p-draft'));
});

// -----------------------------------------------------------------------
// linkTargetOptions — already-matched annotation + demotion (fix/upload-pdf-
// and-link-clarity: warn about accidental duplicate links)
// -----------------------------------------------------------------------

test('linkTargetOptions: with no matchedPaperIds arg, behaves exactly as before (back-compat)', () => {
  const opts = linkTargetOptions(LINK_PAPERS, 'p-draft');
  assert.deepEqual(opts.map(o => o.paperId), ['p-noauth', 'p-noyear', 'p-full']);
  assert.ok(opts.every(o => !o.label.includes('already matched')));
});

test('linkTargetOptions: matched papers get the "(already matched to another reference)" suffix', () => {
  const opts = linkTargetOptions(LINK_PAPERS, 'p-draft', new Set(['p-full']));
  const full = opts.find(o => o.paperId === 'p-full');
  assert.equal(full.label, 'Complete Paper (2020) (already matched to another reference)');
  // Unmatched papers are untouched.
  const noyear = opts.find(o => o.paperId === 'p-noyear');
  assert.equal(noyear.label, 'Needs Year (—)');
});

test('linkTargetOptions: matched papers are sorted AFTER all unmatched papers', () => {
  // p-noauth needs metadata (would normally sort first) but is matched, so it
  // must be demoted below every unmatched option, including the "complete"
  // p-full paper that would otherwise sort after it.
  const opts = linkTargetOptions(LINK_PAPERS, 'p-draft', new Set(['p-noauth']));
  const ids = opts.map(o => o.paperId);
  assert.deepEqual(ids, ['p-noyear', 'p-full', 'p-noauth']);
});

test('linkTargetOptions: matched papers remain selectable (still present in options)', () => {
  const opts = linkTargetOptions(LINK_PAPERS, 'p-draft', new Set(['p-full', 'p-noyear']));
  assert.equal(opts.length, 3, 'a draft can legitimately cite the same work twice');
  assert.ok(opts.some(o => o.paperId === 'p-full'));
  assert.ok(opts.some(o => o.paperId === 'p-noyear'));
});

test('linkTargetOptions: accepts a plain array as matchedPaperIds, not just a Set', () => {
  const opts = linkTargetOptions(LINK_PAPERS, 'p-draft', ['p-full']);
  const full = opts.find(o => o.paperId === 'p-full');
  assert.ok(full.label.includes('already matched to another reference'));
});

test('linkTargetOptions: the draft paper is still excluded regardless of matchedPaperIds', () => {
  const opts = linkTargetOptions(LINK_PAPERS, 'p-draft', new Set(['p-draft', 'p-full']));
  assert.ok(!opts.some(o => o.paperId === 'p-draft'));
});

// -----------------------------------------------------------------------
// matchedPaperIdSet — which papers are matched_paper_id of an in_library
// reference OTHER than the one currently being linked
// -----------------------------------------------------------------------

const MATCH_REFS = [
  { index: 0, status: 'in_library', matched_paper_id: 'pA' },
  { index: 1, status: 'in_library', matched_paper_id: 'pB' },
  { index: 2, status: 'available' },
  { index: 3, status: 'in_library', matched_paper_id: null },
  { index: 4, status: 'unresolved' },
];

test('matchedPaperIdSet: null/undefined/non-array references -> empty set', () => {
  assert.deepEqual([...matchedPaperIdSet(null)], []);
  assert.deepEqual([...matchedPaperIdSet(undefined)], []);
  assert.deepEqual([...matchedPaperIdSet({})], []);
});

test('matchedPaperIdSet: collects matched_paper_id only from in_library refs', () => {
  const set = matchedPaperIdSet(MATCH_REFS);
  assert.deepEqual([...set].sort(), ['pA', 'pB']);
});

test('matchedPaperIdSet: excludes the reference at excludeIndex', () => {
  const set = matchedPaperIdSet(MATCH_REFS, 0);
  assert.deepEqual([...set], ['pB']);
});

test('matchedPaperIdSet: in_library refs with no matched_paper_id contribute nothing', () => {
  const set = matchedPaperIdSet(MATCH_REFS);
  assert.equal(set.has(null), false);
  assert.equal(set.has(undefined), false);
});

// -----------------------------------------------------------------------
// unlinkedCitationOptions — options for the library-drawer reverse picker
// (v0.5.8 Task 3)
// -----------------------------------------------------------------------

const UNLINKED_REFS = {
  references: [
    { index: 0, title: 'Already In Library', year: 2020, status: 'in_library' },
    { index: 1, title: 'Available Paper',    year: 2021, status: 'available' },
    { index: 2, raw: 'Unchecked raw citation text', status: 'unchecked' },
    { index: 3, title: 'Unresolved Paper',   year: 2019, status: 'unresolved' },
  ],
};

test('unlinkedCitationOptions: null / empty / no-references coverage returns []', () => {
  assert.deepEqual(unlinkedCitationOptions(null), []);
  assert.deepEqual(unlinkedCitationOptions(undefined), []);
  assert.deepEqual(unlinkedCitationOptions({}), []);
  assert.deepEqual(unlinkedCitationOptions({ references: [] }), []);
});

test('unlinkedCitationOptions: excludes in_library references', () => {
  const opts = unlinkedCitationOptions(UNLINKED_REFS);
  assert.ok(!opts.some(o => o.index === 0), 'in_library ref must be excluded');
});

test('unlinkedCitationOptions: includes available/unchecked/unresolved, index preserved', () => {
  const opts = unlinkedCitationOptions(UNLINKED_REFS);
  assert.deepEqual(opts.map(o => o.index), [1, 2, 3]);
});

test('unlinkedCitationOptions: label appends year when present', () => {
  const opts = unlinkedCitationOptions(UNLINKED_REFS);
  const avail = opts.find(o => o.index === 1);
  assert.equal(avail.label, 'Available Paper (2021)');
});

test('unlinkedCitationOptions: label omits year when absent, falls back to raw', () => {
  const opts = unlinkedCitationOptions(UNLINKED_REFS);
  const unchecked = opts.find(o => o.index === 2);
  assert.equal(unchecked.label, 'Unchecked raw citation text');
});

test('unlinkedCitationOptions: truncates long titles to ~70 chars', () => {
  const longTitle = 'A'.repeat(120);
  const opts = unlinkedCitationOptions({
    references: [{ index: 5, title: longTitle, status: 'available' }],
  });
  assert.equal(opts.length, 1);
  assert.ok(opts[0].label.length <= 70, 'label body should be truncated');
  assert.ok(opts[0].label.endsWith('…'), 'truncated label ends with ellipsis');
});

// -----------------------------------------------------------------------
// selectNextActions — add-cited-papers rule
// -----------------------------------------------------------------------

function makeNBAState(overrides = {}) {
  return {
    settings: { provider: 'anthropic', keys: { anthropic_api_key: { set: true } } },
    draftId: 'paper-1',
    papers: new Map([
      ['paper-1', { paper_id: 'paper-1', is_draft: true, status: 'done' }],
      ['paper-2', { paper_id: 'paper-2', is_draft: false, status: 'done' }],
      ['paper-3', { paper_id: 'paper-3', is_draft: false, status: 'done' }],
    ]),
    failures: {},
    suggestions: [],
    suggestionCounts: { open: 0, by_severity: null },
    ...overrides,
  };
}

test('selectNextActions add-cited-papers: fires when draft set, total>0, missing>0', () => {
  const state = makeNBAState({
    citationCoverage: {
      draft_paper_id: 'paper-1',
      counts: { total: 10, in_library: 4, available: 3, unchecked: 2, unresolved: 1 },
    },
  });
  const actions = selectNextActions(state);
  const action = actions.find(a => a.id === 'add-cited-papers');
  assert.ok(action, 'add-cited-papers action should be present');
  assert.equal(action.action, 'open-citations');
  assert.ok(action.label.includes('6'), 'label should mention missing count');
});

test('selectNextActions add-cited-papers: absent when fully covered', () => {
  const state = makeNBAState({
    citationCoverage: {
      draft_paper_id: 'paper-1',
      counts: { total: 5, in_library: 5, available: 0, unchecked: 0, unresolved: 0 },
    },
  });
  const actions = selectNextActions(state);
  assert.ok(!actions.some(a => a.id === 'add-cited-papers'), 'should NOT fire when fully covered');
});

test('selectNextActions add-cited-papers: absent when no draft', () => {
  const state = makeNBAState({
    draftId: null,
    citationCoverage: {
      draft_paper_id: null,
      counts: { total: 10, in_library: 4, available: 3, unchecked: 2, unresolved: 1 },
    },
  });
  const actions = selectNextActions(state);
  assert.ok(!actions.some(a => a.id === 'add-cited-papers'), 'should NOT fire when no draft');
});

test('selectNextActions add-cited-papers: absent when citationCoverage null', () => {
  const state = makeNBAState({ citationCoverage: null });
  const actions = selectNextActions(state);
  assert.ok(!actions.some(a => a.id === 'add-cited-papers'));
});

test('selectNextActions add-cited-papers: absent when total=0', () => {
  const state = makeNBAState({
    citationCoverage: {
      draft_paper_id: 'paper-1',
      counts: { total: 0, in_library: 0, available: 0, unchecked: 0, unresolved: 0 },
    },
  });
  const actions = selectNextActions(state);
  assert.ok(!actions.some(a => a.id === 'add-cited-papers'));
});

test('selectNextActions add-cited-papers: priority places it before add-papers (Rule 3)', () => {
  // State that triggers both add-cited-papers and add-papers
  const state = makeNBAState({
    papers: new Map([['paper-1', { paper_id: 'paper-1', is_draft: true }]]), // < 3 non-draft
    citationCoverage: {
      draft_paper_id: 'paper-1',
      counts: { total: 10, in_library: 2, available: 5, unchecked: 3, unresolved: 0 },
    },
  });
  const actions = selectNextActions(state);
  const ccIdx = actions.findIndex(a => a.id === 'add-cited-papers');
  const apIdx = actions.findIndex(a => a.id === 'add-papers');
  // Both present: add-cited-papers must come first (lower priority number)
  if (ccIdx !== -1 && apIdx !== -1) {
    assert.ok(ccIdx < apIdx, 'add-cited-papers must appear before add-papers');
  }
});

test('selectNextActions add-cited-papers: singular label for 1 missing', () => {
  const state = makeNBAState({
    citationCoverage: {
      draft_paper_id: 'paper-1',
      counts: { total: 5, in_library: 4, available: 1, unchecked: 0, unresolved: 0 },
    },
  });
  const actions = selectNextActions(state);
  const action = actions.find(a => a.id === 'add-cited-papers');
  assert.ok(action, 'should be present');
  assert.ok(!action.label.endsWith('papers'), 'singular: no trailing s');
  assert.ok(action.label.includes('paper'), 'should include "paper"');
});
