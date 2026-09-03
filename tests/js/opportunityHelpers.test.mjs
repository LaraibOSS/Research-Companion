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

const { opportunityModel, noteRowModel, notesGroupModel } = await import(
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

test('noteRowModel: carries through kind and sourceExcerpt', () => {
  const row = noteRowModel({ ...NOTE, kind: 'opportunity', source_excerpt: 'excerpt text' });
  assert.equal(row.kind, 'opportunity');
  assert.equal(row.sourceExcerpt, 'excerpt text');
});

test('noteRowModel: missing kind/source_excerpt default to empty strings', () => {
  const row = noteRowModel({ id: 'n3' });
  assert.equal(row.kind, '');
  assert.equal(row.sourceExcerpt, '');
});

test('noteRowModel: an "ask" note with no paper/section/relation does not throw and carries kind:"ask"', () => {
  const askNote = {
    id: 'ask-1',
    kind: 'ask',
    source_excerpt: 'What does the literature say about X?',
    created_at: '2026-07-02T00:00:00Z',
    status: 'open',
    comment: '',
  };
  assert.doesNotThrow(() => noteRowModel(askNote));
  const row = noteRowModel(askNote);
  assert.equal(row.kind, 'ask');
  assert.equal(row.sourceExcerpt, 'What does the literature say about X?');
  assert.equal(row.paperId, '');
  assert.equal(row.sectionId, '');
  assert.equal(row.relation, '');
  assert.equal(row.badgeColor, '#8b949e');
  assert.equal(row.badgeIcon, '');
});

// ---------------------------------------------------------------------------
// notesGroupModel
// ---------------------------------------------------------------------------

const GROUP_NOTES = [
  { id: 'n1', paper_id: 'p1', paper_title: 'Paper One', draft_section_id: 'sec-1', draft_section_title: 'Related Work' },
  { id: 'n2', paper_id: 'p2', paper_title: 'Paper Two', draft_section_id: 'sec-1', draft_section_title: 'Related Work' },
  { id: 'n3', paper_id: 'p1', paper_title: 'Paper One', draft_section_id: 'sec-2', draft_section_title: 'Methods' },
  { id: 'n4', kind: 'ask', source_excerpt: 'unfiled note' }, // no paper/section
];

test('notesGroupModel: groups by section title when groupBy is not "paper"', () => {
  const groups = notesGroupModel(GROUP_NOTES, 'section');
  const keys = groups.map(g => g.key);
  assert.ok(keys.includes('Related Work'));
  assert.ok(keys.includes('Methods'));
  const relatedWork = groups.find(g => g.key === 'Related Work');
  assert.equal(relatedWork.rows.length, 2);
  assert.deepEqual(relatedWork.rows.map(r => r.id), ['n1', 'n2']);
});

test('notesGroupModel: groups by paper title when groupBy is "paper"', () => {
  const groups = notesGroupModel(GROUP_NOTES, 'paper');
  const keys = groups.map(g => g.key);
  assert.ok(keys.includes('Paper One'));
  assert.ok(keys.includes('Paper Two'));
  const paperOne = groups.find(g => g.key === 'Paper One');
  assert.equal(paperOne.rows.length, 2);
  assert.deepEqual(paperOne.rows.map(r => r.id), ['n1', 'n3']);
});

test('notesGroupModel: notes with no sectionTitle/paperTitle land in "Unfiled"', () => {
  const groups = notesGroupModel(GROUP_NOTES, 'section');
  const unfiled = groups.find(g => g.key === 'Unfiled');
  assert.ok(unfiled);
  assert.deepEqual(unfiled.rows.map(r => r.id), ['n4']);
});

test('notesGroupModel: "Unfiled" group is always sorted last', () => {
  const bySection = notesGroupModel(GROUP_NOTES, 'section');
  assert.equal(bySection[bySection.length - 1].key, 'Unfiled');

  const byPaper = notesGroupModel(GROUP_NOTES, 'paper');
  assert.equal(byPaper[byPaper.length - 1].key, 'Unfiled');
});

test('notesGroupModel: each group row is a full noteRowModel (has badgeColor etc.)', () => {
  const groups = notesGroupModel(GROUP_NOTES, 'section');
  const relatedWork = groups.find(g => g.key === 'Related Work');
  for (const row of relatedWork.rows) {
    assert.ok(Object.prototype.hasOwnProperty.call(row, 'badgeColor'));
    assert.ok(Object.prototype.hasOwnProperty.call(row, 'kind'));
    assert.ok(Object.prototype.hasOwnProperty.call(row, 'sourceExcerpt'));
  }
});

test('notesGroupModel: empty array input returns []', () => {
  assert.deepEqual(notesGroupModel([], 'section'), []);
});

test('notesGroupModel: null/undefined/non-array input returns [] and does not throw', () => {
  assert.doesNotThrow(() => notesGroupModel(null, 'section'));
  assert.doesNotThrow(() => notesGroupModel(undefined, 'section'));
  assert.doesNotThrow(() => notesGroupModel('nope', 'section'));
  assert.deepEqual(notesGroupModel(null, 'section'), []);
  assert.deepEqual(notesGroupModel(undefined, 'section'), []);
  assert.deepEqual(notesGroupModel('nope', 'section'), []);
});

test('notesGroupModel: malformed note entries in the array are tolerated', () => {
  const malformed = [null, undefined, 'oops', 42, { id: 'ok', paper_id: 'p1', paper_title: 'Paper One' }];
  assert.doesNotThrow(() => notesGroupModel(malformed, 'paper'));
  const groups = notesGroupModel(malformed, 'paper');
  const paperOne = groups.find(g => g.key === 'Paper One');
  assert.ok(paperOne);
  const unfiled = groups.find(g => g.key === 'Unfiled');
  assert.ok(unfiled);
  assert.equal(unfiled.rows.length, 4);
});

test('noteRowModel resolves a stored origin', () => {
  const m = noteRowModel({
    id: 'n1', kind: 'freeform',
    origin_kind: 'gap', origin_id: 'gap_1', origin_label: 'Expand evaluations',
  });
  assert.equal(m.origin.canOpen, true);
  assert.equal(m.origin.href, '#/gaps?theme=gap_1');
  assert.equal(m.origin.label, 'Expand evaluations');
});

test('noteRowModel gives an origin-less note a non-openable origin', () => {
  // Every note written before origins existed lands here. It must be a
  // usable object, not undefined — _renderCard reads .canOpen off it.
  const m = noteRowModel({ id: 'n1', kind: 'reader' });
  assert.equal(m.origin.canOpen, false);
  assert.equal(m.origin.label, '');
});

test('noteRowModel still yields an origin on its malformed-input fallback', () => {
  for (const bad of [null, undefined, 'note', 7]) {
    const m = noteRowModel(bad);
    assert.ok(m.origin, 'the catch-branch fallback must include origin');
    assert.equal(m.origin.canOpen, false);
  }
});
