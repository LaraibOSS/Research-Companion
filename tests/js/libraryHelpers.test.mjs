/**
 * libraryHelpers.test.mjs — Tests for W4-F2 pure helpers:
 *   deriveStatus, dominantRelation, buildRows, sortRows (js/libraryHelpers.js)
 *
 * Run from repo root:
 *   node --test tests/js/libraryHelpers.test.mjs
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot  = path.resolve(__dirname, '..', '..');

const { deriveStatus, dominantRelation, buildRows, sortRows, draftActionFor, needsMetadata, metadataBannerText, formatFailureReason } = await import(
  pathToFileURL(path.join(repoRoot, 'research_companion', 'lab', 'static', 'js', 'libraryHelpers.js')).href
);

// ---------------------------------------------------------------------------
// needsMetadata (truth table)
// ---------------------------------------------------------------------------

test('needsMetadata: year null -> true', () => {
  assert.equal(needsMetadata({ year: null, authors: ['Alice'] }), true);
  assert.equal(needsMetadata({ authors: ['Alice'] }), true); // year undefined
});

test('needsMetadata: authors empty/absent -> true', () => {
  assert.equal(needsMetadata({ year: 2020, authors: [] }), true);
  assert.equal(needsMetadata({ year: 2020 }), true); // authors absent
  assert.equal(needsMetadata({ year: 2020, authors: null }), true);
});

test('needsMetadata: both missing -> true', () => {
  assert.equal(needsMetadata({}), true);
  assert.equal(needsMetadata({ year: null, authors: [] }), true);
});

test('needsMetadata: year present and authors present -> false', () => {
  assert.equal(needsMetadata({ year: 2020, authors: ['Alice'] }), false);
  assert.equal(needsMetadata({ year: 1999, authors: ['A', 'B'] }), false);
});

test('needsMetadata: null/undefined paper -> false (nothing to flag)', () => {
  assert.equal(needsMetadata(null), false);
  assert.equal(needsMetadata(undefined), false);
});

test('buildRows: exposes authors and needsMetadata on each row', () => {
  const rows = buildRows(new Map([
    ['a', { paper_id: 'a', title: 'A', year: 2020, authors: ['Alice'] }],
    ['b', { paper_id: 'b', title: 'B', year: null, authors: [] }],
  ]), null);
  const a = rows.find(r => r.paperId === 'a');
  const b = rows.find(r => r.paperId === 'b');
  assert.deepEqual(a.authors, ['Alice']);
  assert.equal(a.needsMetadata, false);
  assert.deepEqual(b.authors, []);
  assert.equal(b.needsMetadata, true);
});

// ---------------------------------------------------------------------------
// deriveStatus
// ---------------------------------------------------------------------------

test('deriveStatus: failed -> failed', () => {
  assert.equal(deriveStatus({ status: 'failed' }), 'failed');
});

test('deriveStatus: processing -> processing', () => {
  assert.equal(deriveStatus({ status: 'processing' }), 'processing');
});

test('deriveStatus: done -> ingested', () => {
  assert.equal(deriveStatus({ status: 'done' }), 'ingested');
});

test('deriveStatus: pending -> queued', () => {
  assert.equal(deriveStatus({ status: 'pending' }), 'queued');
});

test('deriveStatus: unknown/missing -> queued', () => {
  assert.equal(deriveStatus({ status: 'unknown' }), 'queued');
  assert.equal(deriveStatus({}), 'queued');
  assert.equal(deriveStatus({ status: null }), 'queued');
});

// ---------------------------------------------------------------------------
// dominantRelation
// ---------------------------------------------------------------------------

test('dominantRelation: returns max count relation', () => {
  assert.equal(dominantRelation({ strengthens: 1, challenges: 3, alternative: 0 }), 'challenges');
});

test('dominantRelation: tie-break strengthens > challenges', () => {
  assert.equal(dominantRelation({ strengthens: 2, challenges: 2, alternative: 0 }), 'strengthens');
});

test('dominantRelation: tie-break challenges > alternative', () => {
  assert.equal(dominantRelation({ strengthens: 0, challenges: 2, alternative: 2 }), 'challenges');
});

test('dominantRelation: tie-break strengthens > alternative', () => {
  assert.equal(dominantRelation({ strengthens: 3, challenges: 0, alternative: 3 }), 'strengthens');
});

test('dominantRelation: all-zero -> null', () => {
  assert.equal(dominantRelation({ strengthens: 0, challenges: 0, alternative: 0 }), null);
});

test('dominantRelation: missing object -> null', () => {
  assert.equal(dominantRelation(null), null);
  assert.equal(dominantRelation(undefined), null);
  assert.equal(dominantRelation({}), null);
});

test('dominantRelation: partial missing fields treated as 0', () => {
  assert.equal(dominantRelation({ strengthens: 2 }), 'strengthens');
  assert.equal(dominantRelation({ challenges: 5 }), 'challenges');
});

test('dominantRelation: all three tied -> strengthens wins', () => {
  assert.equal(dominantRelation({ strengthens: 1, challenges: 1, alternative: 1 }), 'strengthens');
});

// ---------------------------------------------------------------------------
// buildRows
// ---------------------------------------------------------------------------

const PAPERS_MAP = new Map([
  ['p1', {
    paper_id: 'p1',
    title: 'Alpha Paper',
    year: 2020,
    status: 'done',
    strength: { band: 'strong', score: 0.9 },
    stance_counts: { strengthens: 2, challenges: 1, alternative: 0 },
    added_at: '2024-01-01T00:00:00Z',
    is_draft: false,
    failure_reason: null,
  }],
  ['p2', {
    paper_id: 'p2',
    title: 'Beta Paper',
    year: 2022,
    status: 'processing',
    strength: null,
    stance_counts: { strengthens: 0, challenges: 0, alternative: 0 },
    added_at: '2024-01-02T00:00:00Z',
    is_draft: false,
    failure_reason: null,
  }],
  ['draft1', {
    paper_id: 'draft1',
    title: 'My Draft',
    year: 2023,
    status: 'done',
    strength: { band: 'moderate', score: 0.5 },
    stance_counts: { strengthens: 0, challenges: 0, alternative: 0 },
    added_at: '2024-01-03T00:00:00Z',
    is_draft: true,
    failure_reason: null,
  }],
]);

test('buildRows: draft row comes first', () => {
  const rows = buildRows(PAPERS_MAP, 'draft1');
  assert.equal(rows[0].paperId, 'draft1');
  assert.equal(rows[0].isDraft, true);
});

test('buildRows: all papers included', () => {
  const rows = buildRows(PAPERS_MAP, 'draft1');
  assert.equal(rows.length, 3);
});

test('buildRows: row shape is correct', () => {
  const rows = buildRows(PAPERS_MAP, 'draft1');
  const p1Row = rows.find(r => r.paperId === 'p1');
  assert.ok(p1Row, 'p1 row must exist');
  assert.equal(p1Row.title, 'Alpha Paper');
  assert.equal(p1Row.year, 2020);
  assert.equal(p1Row.status, 'ingested');
  assert.equal(p1Row.strengthBand, 'strong');
  assert.equal(p1Row.strengthScore, 0.9);
  assert.equal(p1Row.relation, 'strengthens');
  assert.equal(p1Row.addedAt, '2024-01-01T00:00:00Z');
  assert.equal(p1Row.isDraft, false);
  assert.equal(p1Row.failureReason, null);
});

test('buildRows: processing paper has correct status', () => {
  const rows = buildRows(PAPERS_MAP, 'draft1');
  const p2Row = rows.find(r => r.paperId === 'p2');
  assert.equal(p2Row.status, 'processing');
  assert.equal(p2Row.strengthBand, null);
  assert.equal(p2Row.relation, null);
});

test('buildRows: no draftId means no isDraft rows', () => {
  const rows = buildRows(PAPERS_MAP, null);
  assert.ok(rows.every(r => !r.isDraft));
});

test('buildRows: accepts array as well as Map', () => {
  const arr = [...PAPERS_MAP.values()];
  const rows = buildRows(arr, 'draft1');
  assert.equal(rows.length, 3);
  assert.equal(rows[0].paperId, 'draft1');
});

test('buildRows: empty input returns empty array', () => {
  assert.deepEqual(buildRows(new Map(), null), []);
  assert.deepEqual(buildRows([], null), []);
});

test('buildRows: null strengthBand when no strength', () => {
  const rows = buildRows(PAPERS_MAP, 'draft1');
  const p2Row = rows.find(r => r.paperId === 'p2');
  assert.equal(p2Row.strengthBand, null);
  assert.equal(p2Row.strengthScore, null);
});

test('buildRows carries ocrUsed and parseSource', () => {
  const papers = [
    { paper_id: 'p1', title: 'Scanned', ocr_used: true,  parse_source: 'docling+ocr' },
    { paper_id: 'p2', title: 'Digital',  ocr_used: false, parse_source: 'pypdfium' },
    { paper_id: 'p3', title: 'Legacy' },  // no fields -> defaults
  ];
  const rows = buildRows(papers, null);
  const byId = Object.fromEntries(rows.map(r => [r.paperId, r]));
  assert.equal(byId.p1.ocrUsed, true);
  assert.equal(byId.p1.parseSource, 'docling+ocr');
  assert.equal(byId.p2.ocrUsed, false);
  assert.equal(byId.p2.parseSource, 'pypdfium');
  assert.equal(byId.p3.ocrUsed, false);
  assert.equal(byId.p3.parseSource, '');
});

test('buildRows carries oa_links through as oaLinks (list-view find-pdf parity)', () => {
  const papers = [
    { paper_id: 'p1', title: 'Has links', status: 'failed', failure_reason: 'no PDF on disk',
      oa_links: [{ label: 'DOI page', url: 'https://doi.org/10.1/x' }] },
    { paper_id: 'p2', title: 'No links field', status: 'failed', failure_reason: 'no PDF on disk' },
  ];
  const rows = buildRows(papers, null);
  const byId = Object.fromEntries(rows.map(r => [r.paperId, r]));
  assert.deepEqual(byId.p1.oaLinks, [{ label: 'DOI page', url: 'https://doi.org/10.1/x' }]);
  assert.deepEqual(byId.p2.oaLinks, []);
});

test('buildRows carries acquisition through unchanged (list-view Upload/Find-PDF parity)', () => {
  const acquisition = { obtained: false, reason: 'blocked_by_host', human_can_help: true,
    attempts: [], source: null, headline: 'blocked', detail: 'try your browser' };
  const papers = [
    { paper_id: 'p1', title: 'Has acquisition', status: 'failed', acquisition },
    { paper_id: 'p2', title: 'No acquisition field', status: 'failed' },
  ];
  const rows = buildRows(papers, null);
  const byId = Object.fromEntries(rows.map(r => [r.paperId, r]));
  assert.deepEqual(byId.p1.acquisition, acquisition);
  assert.equal(byId.p2.acquisition, null);
});

// ---------------------------------------------------------------------------
// sortRows
// ---------------------------------------------------------------------------

function makeRows() {
  return buildRows(PAPERS_MAP, 'draft1');
}

test('sortRows: draft row always stays pinned at top regardless of sort', () => {
  for (const col of ['title', 'year', 'status', 'strength', 'relation', 'added']) {
    for (const dir of ['asc', 'desc']) {
      const rows = sortRows(makeRows(), col, dir);
      assert.equal(rows[0].paperId, 'draft1', `draft must be first for ${col} ${dir}`);
    }
  }
});

test('sortRows: title asc sorts alphabetically', () => {
  const rows = sortRows(makeRows(), 'title', 'asc');
  const nonDraft = rows.slice(1);
  assert.ok(nonDraft[0].title <= nonDraft[1].title, 'titles must be ascending');
});

test('sortRows: title desc sorts reverse alphabetically', () => {
  const rows = sortRows(makeRows(), 'title', 'desc');
  const nonDraft = rows.slice(1);
  assert.ok(nonDraft[0].title >= nonDraft[1].title, 'titles must be descending');
});

test('sortRows: year asc sorts years ascending', () => {
  const rows = sortRows(makeRows(), 'year', 'asc');
  const nonDraft = rows.slice(1);
  assert.ok(nonDraft[0].year <= nonDraft[1].year, 'years must be ascending');
});

test('sortRows: year desc sorts years descending', () => {
  const rows = sortRows(makeRows(), 'year', 'desc');
  const nonDraft = rows.slice(1);
  assert.ok(nonDraft[0].year >= nonDraft[1].year, 'years must be descending');
});

test('sortRows: strength order is strong < moderate < weak < unscored', () => {
  const rows = [
    { paperId: 'a', isDraft: false, strengthBand: 'weak' },
    { paperId: 'b', isDraft: false, strengthBand: 'strong' },
    { paperId: 'c', isDraft: false, strengthBand: 'moderate' },
    { paperId: 'd', isDraft: false, strengthBand: null },
  ];
  const sorted = sortRows(rows, 'strength', 'asc');
  assert.equal(sorted[0].strengthBand, 'strong');
  assert.equal(sorted[1].strengthBand, 'moderate');
  assert.equal(sorted[2].strengthBand, 'weak');
  assert.equal(sorted[3].strengthBand, null);
});

test('sortRows: status order is processing < queued < ingested < failed', () => {
  const rows = [
    { paperId: 'a', isDraft: false, status: 'failed' },
    { paperId: 'b', isDraft: false, status: 'ingested' },
    { paperId: 'c', isDraft: false, status: 'queued' },
    { paperId: 'd', isDraft: false, status: 'processing' },
  ];
  const sorted = sortRows(rows, 'status', 'asc');
  assert.equal(sorted[0].status, 'processing');
  assert.equal(sorted[1].status, 'queued');
  assert.equal(sorted[2].status, 'ingested');
  assert.equal(sorted[3].status, 'failed');
});

test('sortRows: added asc sorts by addedAt ascending', () => {
  const rows = [
    { paperId: 'a', isDraft: false, addedAt: '2024-03-01T00:00:00Z' },
    { paperId: 'b', isDraft: false, addedAt: '2024-01-01T00:00:00Z' },
    { paperId: 'c', isDraft: false, addedAt: '2024-02-01T00:00:00Z' },
  ];
  const sorted = sortRows(rows, 'added', 'asc');
  assert.equal(sorted[0].paperId, 'b');
  assert.equal(sorted[1].paperId, 'c');
  assert.equal(sorted[2].paperId, 'a');
});

test('sortRows: stable sort preserves order of equal elements', () => {
  const rows = [
    { paperId: 'x', isDraft: false, status: 'ingested', title: 'B' },
    { paperId: 'y', isDraft: false, status: 'ingested', title: 'A' },
  ];
  // Both have same status; stable sort should not swap them unless needed
  const sorted = sortRows(rows, 'status', 'asc');
  // Both are ingested, order among them should be stable (original order preserved)
  assert.equal(sorted[0].paperId, 'x');
  assert.equal(sorted[1].paperId, 'y');
});

test('sortRows: returns new array (immutable)', () => {
  const rows = makeRows();
  const sorted = sortRows(rows, 'title', 'asc');
  assert.notEqual(sorted, rows);
});

// ---------------------------------------------------------------------------
// draftActionFor
// ---------------------------------------------------------------------------

test('draftActionFor: paper is the current draft -> Unset draft, next null', () => {
  const action = draftActionFor('p1', 'p1');
  assert.equal(action.label, 'Unset draft');
  assert.equal(action.next, null);
  assert.equal(action.toast, 'Draft cleared');
});

test('draftActionFor: paper is not the draft -> Set as draft, next paperId', () => {
  const action = draftActionFor('p1', 'p2');
  assert.equal(action.label, 'Set as draft');
  assert.equal(action.next, 'p1');
  assert.equal(action.toast, 'Draft updated');
});

test('draftActionFor: no draft set (null) -> Set as draft', () => {
  const action = draftActionFor('p1', null);
  assert.equal(action.label, 'Set as draft');
  assert.equal(action.next, 'p1');
  assert.equal(action.toast, 'Draft updated');
});

test('draftActionFor: no draft set (undefined) -> Set as draft', () => {
  const action = draftActionFor('p1', undefined);
  assert.equal(action.label, 'Set as draft');
  assert.equal(action.next, 'p1');
});

// ---------------------------------------------------------------------------
// metadataBannerText
// ---------------------------------------------------------------------------

test('metadataBannerText: singular count -> "1 paper needs metadata"', () => {
  assert.equal(
    metadataBannerText(1),
    '1 paper needs metadata — add authors/year so they appear on the timeline and match your citations'
  );
});

test('metadataBannerText: plural count -> "N papers need metadata"', () => {
  assert.equal(
    metadataBannerText(2),
    '2 papers need metadata — add authors/year so they appear on the timeline and match your citations'
  );
  assert.equal(
    metadataBannerText(5),
    '5 papers need metadata — add authors/year so they appear on the timeline and match your citations'
  );
});

// ---------------------------------------------------------------------------
// formatFailureReason
// ---------------------------------------------------------------------------

test('formatFailureReason: null/undefined/empty -> ""', () => {
  assert.equal(formatFailureReason(null), '');
  assert.equal(formatFailureReason(undefined), '');
  assert.equal(formatFailureReason(''), '');
});

test('formatFailureReason: short reason returned unchanged', () => {
  assert.equal(formatFailureReason('parser crashed'), 'parser crashed');
});

test('formatFailureReason: long reason truncated to ~80 chars with an ellipsis', () => {
  const long = 'x'.repeat(120);
  const out = formatFailureReason(long);
  assert.ok(out.length <= 81, `expected <= 81 chars, got ${out.length}`);
  assert.ok(out.endsWith('…'));
  assert.ok(long.startsWith(out.slice(0, -1)));
});

test('formatFailureReason: prefers acquisition.headline when present, over the raw reason', () => {
  const acquisition = { human_can_help: true,
    headline: 'The PDF download was never attempted.',
    detail: 'Add the PDF directly and it will work like any other paper.' };
  const out = formatFailureReason('no PDF on disk for doi:10.1234/abcd', acquisition);
  assert.equal(out, 'The PDF download was never attempted.');
});

test('formatFailureReason: an acquisition with no headline falls back to the raw (truncated) reason', () => {
  const out = formatFailureReason('PDF not found: /some/path/paper.pdf', { human_can_help: true, headline: '' });
  assert.equal(out, 'PDF not found: /some/path/paper.pdf');
});

test('formatFailureReason: no acquisition at all falls back to the raw (truncated) reason', () => {
  assert.equal(formatFailureReason('PDF not found: /some/path/paper.pdf', null),
    'PDF not found: /some/path/paper.pdf');
  assert.equal(formatFailureReason('PDF not found: /some/path/paper.pdf'),
    'PDF not found: /some/path/paper.pdf');
});
