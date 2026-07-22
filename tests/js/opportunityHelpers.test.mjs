/**
 * opportunityHelpers.test.mjs — Table-driven tests for Task 3 pure helpers:
 *   opportunityModel, noteRowModel
 *
 * Run from repo root:
 *   node --test tests/js/opportunityHelpers.test.mjs
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot  = path.resolve(__dirname, '..', '..');

const { opportunityModel, noteRowModel } = await import(
  pathToFileURL(path.join(
    repoRoot,
    'research_companion', 'lab', 'static', 'js', 'opportunityHelpers.js',
  )).href
);

// ---------------------------------------------------------------------------
// opportunityModel
// ---------------------------------------------------------------------------

const SECTIONS = [
  {
    section_id: 'sec-1',
    section_title: 'Related Work',
    suggestions: [
      {
        paper_id: 'p1',
        title: 'Paper One',
        relation: 'strengthens',
        relevance: 0.9,
        rationale: 'Supports the claim.',
        evidence: [{ quote: 'quote one', section_id: 'p1-sec-3' }],
        strength_band: 'strong',
      },
      {
        paper_id: 'p2',
        title: 'Paper Two',
        relation: 'challenges',
        relevance: 0.4,
        rationale: 'Pushes back.',
        evidence: [],
        strength_band: null,
      },
    ],
  },
  {
    section_id: 'sec-2',
    section_title: 'Methods',
    suggestions: [
      {
        paper_id: 'p3',
        title: 'Paper Three',
        relation: 'alternative',
        relevance: 0.6,
        rationale: 'Offers a different approach.',
        evidence: [{ quote: 'quote three', section_id: 'p3-sec-1' }],
        strength_band: 'moderate',
      },
    ],
  },
];

test('opportunityModel: flattens evidence[0] into quote/quoteSectionId', () => {
  const model = opportunityModel(SECTIONS);
  const sec1 = model.find(s => s.sectionId === 'sec-1');
  const s1 = sec1.suggestions.find(s => s.paperId === 'p1');
  assert.equal(s1.quote, 'quote one');
  assert.equal(s1.quoteSectionId, 'p1-sec-3');
});

test('opportunityModel: empty evidence array yields quote:"" quoteSectionId:null', () => {
  const model = opportunityModel(SECTIONS);
  const sec1 = model.find(s => s.sectionId === 'sec-1');
  const s2 = sec1.suggestions.find(s => s.paperId === 'p2');
  assert.equal(s2.quote, '');
  assert.equal(s2.quoteSectionId, null);
});

test('opportunityModel: count equals suggestions length', () => {
  const model = opportunityModel(SECTIONS);
  const sec1 = model.find(s => s.sectionId === 'sec-1');
  const sec2 = model.find(s => s.sectionId === 'sec-2');
  assert.equal(sec1.count, 2);
  assert.equal(sec2.count, 1);
});

test('opportunityModel: sorted order of input suggestions is preserved', () => {
  const model = opportunityModel(SECTIONS);
  const sec1 = model.find(s => s.sectionId === 'sec-1');
  assert.deepEqual(sec1.suggestions.map(s => s.paperId), ['p1', 'p2']);
});

test('opportunityModel: carries through relation/relevance/rationale/title/strengthBand', () => {
  const model = opportunityModel(SECTIONS);
  const sec2 = model.find(s => s.sectionId === 'sec-2');
  const s3 = sec2.suggestions[0];
  assert.equal(s3.paperId, 'p3');
  assert.equal(s3.title, 'Paper Three');
  assert.equal(s3.relation, 'alternative');
  assert.equal(s3.relevance, 0.6);
  assert.equal(s3.rationale, 'Offers a different approach.');
  assert.equal(s3.strengthBand, 'moderate');
});

test('opportunityModel: section with zero suggestions still normalizes (count 0)', () => {
  const model = opportunityModel([{ section_id: 'sec-3', section_title: 'Empty', suggestions: [] }]);
  assert.equal(model.length, 1);
  assert.equal(model[0].count, 0);
  assert.deepEqual(model[0].suggestions, []);
});

test('opportunityModel: empty array input returns []', () => {
  assert.deepEqual(opportunityModel([]), []);
});

test('opportunityModel: null input returns [] and does not throw', () => {
  assert.deepEqual(opportunityModel(null), []);
});

test('opportunityModel: undefined input returns [] and does not throw', () => {
  assert.deepEqual(opportunityModel(undefined), []);
});

test('opportunityModel: non-array input (object/string/number) returns []', () => {
  assert.deepEqual(opportunityModel({}), []);
  assert.deepEqual(opportunityModel('sections'), []);
  assert.deepEqual(opportunityModel(42), []);
});

test('opportunityModel: malformed section entries (null, missing fields) are tolerated', () => {
  const malformed = [
    null,
    undefined,
    'not-an-object',
    { section_id: 'sec-x' }, // missing suggestions
    { section_id: 'sec-y', suggestions: [null, undefined, 'oops', 42] },
  ];
  assert.doesNotThrow(() => opportunityModel(malformed));
  const model = opportunityModel(malformed);
  // sec-x normalizes with an empty suggestions array
  const secX = model.find(s => s.sectionId === 'sec-x');
  assert.ok(secX);
  assert.equal(secX.count, 0);
  // sec-y's malformed suggestion entries normalize to safe defaults, not throw
  const secY = model.find(s => s.sectionId === 'sec-y');
  assert.ok(secY);
  assert.equal(secY.count, 4);
  for (const s of secY.suggestions) {
    assert.equal(s.paperId, '');
    assert.equal(s.quote, '');
    assert.equal(s.quoteSectionId, null);
  }
});

test('opportunityModel: sectionTitle falls back to section_id when missing', () => {
  const model = opportunityModel([{ section_id: 'sec-z', suggestions: [] }]);
  assert.equal(model[0].sectionTitle, 'sec-z');
});

// ---------------------------------------------------------------------------
// noteRowModel
// ---------------------------------------------------------------------------

const NOTE = {
  id: 'note-1',
  created_at: '2026-07-01T00:00:00Z',
  status: 'open',
  draft_section_id: 'sec-1',
  draft_section_title: 'Related Work',
  paper_id: 'p1',
  paper_title: 'Paper One',
  relation: 'strengthens',
  relevance: 0.9,
  rationale: 'Supports the claim.',
  evidence_quote: 'quote one',
  evidence_section_id: 'p1-sec-3',
  comment: 'Cite this in revision.',
};

test('noteRowModel: maps relation to badge color/icon (strengthens)', () => {
  const row = noteRowModel(NOTE);
  assert.equal(row.badgeColor, '#3fb950');
  assert.equal(row.badgeIcon, '▲');
});

test('noteRowModel: maps relation to badge color/icon (challenges)', () => {
  const row = noteRowModel({ ...NOTE, relation: 'challenges' });
  assert.equal(row.badgeColor, '#f85149');
  assert.equal(row.badgeIcon, '⚡');
});

test('noteRowModel: maps relation to badge color/icon (alternative)', () => {
  const row = noteRowModel({ ...NOTE, relation: 'alternative' });
  assert.equal(row.badgeColor, '#58a6ff');
  assert.equal(row.badgeIcon, '◆');
});

test('noteRowModel: unknown relation falls back to muted color and empty icon', () => {
  const row = noteRowModel({ ...NOTE, relation: 'unknown-relation' });
  assert.equal(row.badgeColor, '#8b949e');
  assert.equal(row.badgeIcon, '');
});

test('noteRowModel: passes through comment and status unchanged', () => {
  const row = noteRowModel(NOTE);
  assert.equal(row.comment, 'Cite this in revision.');
  assert.equal(row.status, 'open');
});

test('noteRowModel: passes through done/dismissed status', () => {
  assert.equal(noteRowModel({ ...NOTE, status: 'done' }).status, 'done');
  assert.equal(noteRowModel({ ...NOTE, status: 'dismissed' }).status, 'dismissed');
});

test('noteRowModel: relevance converts to a rounded percent', () => {
  assert.equal(noteRowModel({ ...NOTE, relevance: 0.873 }).relevancePct, 87);
  assert.equal(noteRowModel({ ...NOTE, relevance: 0 }).relevancePct, 0);
});

test('noteRowModel: carries through quote and quoteSectionId', () => {
  const row = noteRowModel(NOTE);
  assert.equal(row.quote, 'quote one');
  assert.equal(row.quoteSectionId, 'p1-sec-3');
});

test('noteRowModel: missing comment/status default to empty comment and "open" status', () => {
  const minimal = { id: 'n2', paper_id: 'p2', draft_section_id: 'sec-2' };
  const row = noteRowModel(minimal);
  assert.equal(row.comment, '');
  assert.equal(row.status, 'open');
});

test('noteRowModel: malformed/empty input never throws, returns safe defaults', () => {
  assert.doesNotThrow(() => noteRowModel(null));
  assert.doesNotThrow(() => noteRowModel(undefined));
  assert.doesNotThrow(() => noteRowModel('not-an-object'));
  assert.doesNotThrow(() => noteRowModel(42));

  const row = noteRowModel(null);
  assert.equal(row.status, 'open');
  assert.equal(row.comment, '');
  assert.equal(row.badgeColor, '#8b949e');
  assert.equal(row.badgeIcon, '');
});
