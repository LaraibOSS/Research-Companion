/**
 * noteRecord.test.mjs — Table-driven tests for Task 2 pure helper:
 *   buildNoteRecord
 *
 * Run from repo root:
 *   node --test tests/js/noteRecord.test.mjs
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot  = path.resolve(__dirname, '..', '..');

const { buildNoteRecord } = await import(
  pathToFileURL(path.join(
    repoRoot,
    'research_companion', 'lab', 'static', 'js', 'noteRecord.js',
  )).href
);

// ---------------------------------------------------------------------------
// Field names always present on the returned record
// ---------------------------------------------------------------------------

const RECORD_FIELDS = [
  'kind', 'paper_id', 'paper_title', 'draft_section_id', 'draft_section_title',
  'relation', 'relevance', 'rationale', 'evidence_quote', 'evidence_section_id',
  'source_excerpt', 'comment',
];

test('buildNoteRecord: always returns every record field', () => {
  const rec = buildNoteRecord('freeform', {});
  for (const f of RECORD_FIELDS) {
    assert.ok(Object.prototype.hasOwnProperty.call(rec, f), `missing field ${f}`);
  }
});

// ---------------------------------------------------------------------------
// opportunity / alignment: paper + section + relation + relevance + rationale
// + evidence_quote + evidence_section_id
// ---------------------------------------------------------------------------

const OPP_DATA = {
  paperId: 'p1', paperTitle: 'Paper One',
  sectionId: 'sec-1', sectionTitle: 'Related Work',
  relation: 'strengthens', relevance: 0.9, rationale: 'Supports the claim.',
  quote: 'quote one', quoteSectionId: 'p1-sec-3',
};

for (const kind of ['opportunity', 'alignment']) {
  test(`buildNoteRecord: ${kind} maps paper/section/relation/relevance/rationale/evidence`, () => {
    const rec = buildNoteRecord(kind, OPP_DATA);
    assert.equal(rec.kind, kind);
    assert.equal(rec.paper_id, 'p1');
    assert.equal(rec.paper_title, 'Paper One');
    assert.equal(rec.draft_section_id, 'sec-1');
    assert.equal(rec.draft_section_title, 'Related Work');
    assert.equal(rec.relation, 'strengthens');
    assert.equal(rec.relevance, 0.9);
    assert.equal(rec.rationale, 'Supports the claim.');
    assert.equal(rec.evidence_quote, 'quote one');
    assert.equal(rec.evidence_section_id, 'p1-sec-3');
    assert.equal(rec.source_excerpt, '');
    assert.equal(rec.comment, '');
  });
}

// ---------------------------------------------------------------------------
// reader: paper + optional source_excerpt/evidence_quote
// ---------------------------------------------------------------------------

test('buildNoteRecord: reader maps paper + source_excerpt/evidence_quote, leaves section/relation empty', () => {
  const rec = buildNoteRecord('reader', {
    paperId: 'p2', paperTitle: 'Paper Two',
    sourceExcerpt: 'an excerpt', quote: 'a quote',
  });
  assert.equal(rec.kind, 'reader');
  assert.equal(rec.paper_id, 'p2');
  assert.equal(rec.paper_title, 'Paper Two');
  assert.equal(rec.source_excerpt, 'an excerpt');
  assert.equal(rec.evidence_quote, 'a quote');
  assert.equal(rec.draft_section_id, '');
  assert.equal(rec.draft_section_title, '');
  assert.equal(rec.relation, '');
});

test('buildNoteRecord: reader with only paper (no excerpt/quote) leaves those empty', () => {
  const rec = buildNoteRecord('reader', { paperId: 'p2', paperTitle: 'Paper Two' });
  assert.equal(rec.source_excerpt, '');
  assert.equal(rec.evidence_quote, '');
});

// ---------------------------------------------------------------------------
// paper: paper only
// ---------------------------------------------------------------------------

test('buildNoteRecord: paper kind maps only paper_id/paper_title, all else empty', () => {
  const rec = buildNoteRecord('paper', { paperId: 'p3', paperTitle: 'Paper Three' });
  assert.equal(rec.kind, 'paper');
  assert.equal(rec.paper_id, 'p3');
  assert.equal(rec.paper_title, 'Paper Three');
  assert.equal(rec.draft_section_id, '');
  assert.equal(rec.relation, '');
  assert.equal(rec.source_excerpt, '');
  assert.equal(rec.comment, '');
});

// ---------------------------------------------------------------------------
// ask: source_excerpt + optional paper
// ---------------------------------------------------------------------------

test('buildNoteRecord: ask kind maps source_excerpt, paper optional', () => {
  const rec = buildNoteRecord('ask', { sourceExcerpt: 'the question context' });
  assert.equal(rec.kind, 'ask');
  assert.equal(rec.source_excerpt, 'the question context');
  assert.equal(rec.paper_id, '');
  assert.equal(rec.paper_title, '');
});

test('buildNoteRecord: ask kind with paper present carries paper through too', () => {
  const rec = buildNoteRecord('ask', {
    sourceExcerpt: 'context', paperId: 'p4', paperTitle: 'Paper Four',
  });
  assert.equal(rec.source_excerpt, 'context');
  assert.equal(rec.paper_id, 'p4');
  assert.equal(rec.paper_title, 'Paper Four');
});

// ---------------------------------------------------------------------------
// freeform: comment + optional paper/section
// ---------------------------------------------------------------------------

test('buildNoteRecord: freeform kind maps comment, paper/section optional', () => {
  const rec = buildNoteRecord('freeform', { comment: 'just a thought' });
  assert.equal(rec.kind, 'freeform');
  assert.equal(rec.comment, 'just a thought');
  assert.equal(rec.paper_id, '');
  assert.equal(rec.draft_section_id, '');
});

test('buildNoteRecord: freeform with paper/section present carries them through', () => {
  const rec = buildNoteRecord('freeform', {
    comment: 'note', paperId: 'p5', sectionId: 'sec-5',
  });
  assert.equal(rec.paper_id, 'p5');
  assert.equal(rec.draft_section_id, 'sec-5');
});

// ---------------------------------------------------------------------------
// unknown kind -> freeform
// ---------------------------------------------------------------------------

test('buildNoteRecord: unknown kind string falls back to freeform', () => {
  assert.equal(buildNoteRecord('bogus-kind', {}).kind, 'freeform');
});

test('buildNoteRecord: missing/null/undefined kind falls back to freeform', () => {
  assert.equal(buildNoteRecord(undefined, {}).kind, 'freeform');
  assert.equal(buildNoteRecord(null, {}).kind, 'freeform');
  assert.equal(buildNoteRecord('', {}).kind, 'freeform');
});

// ---------------------------------------------------------------------------
// missing/malformed data -> empty strings, never throws
// ---------------------------------------------------------------------------

test('buildNoteRecord: no data argument defaults every field to "" (except kind)', () => {
  const rec = buildNoteRecord('paper');
  assert.equal(rec.kind, 'paper');
  assert.equal(rec.paper_id, '');
  assert.equal(rec.paper_title, '');
  assert.equal(rec.draft_section_id, '');
  assert.equal(rec.draft_section_title, '');
  assert.equal(rec.relation, '');
  assert.equal(rec.relevance, '');
  assert.equal(rec.rationale, '');
  assert.equal(rec.evidence_quote, '');
  assert.equal(rec.evidence_section_id, '');
  assert.equal(rec.source_excerpt, '');
  assert.equal(rec.comment, '');
});

test('buildNoteRecord: relevance missing/null yields "" not 0 or NaN', () => {
  assert.equal(buildNoteRecord('opportunity', {}).relevance, '');
  assert.equal(buildNoteRecord('opportunity', { relevance: null }).relevance, '');
});

test('buildNoteRecord: relevance 0 is preserved (falsy but valid)', () => {
  assert.equal(buildNoteRecord('opportunity', { relevance: 0 }).relevance, 0);
});

test('buildNoteRecord: never throws on null/undefined/non-object data', () => {
  assert.doesNotThrow(() => buildNoteRecord('freeform', null));
  assert.doesNotThrow(() => buildNoteRecord('freeform', undefined));
  assert.doesNotThrow(() => buildNoteRecord('freeform', 'not-an-object'));
  assert.doesNotThrow(() => buildNoteRecord('freeform', 42));

  const rec = buildNoteRecord('freeform', null);
  assert.equal(rec.kind, 'freeform');
  assert.equal(rec.comment, '');
});

test('buildNoteRecord: never throws for malformed kind (object/number)', () => {
  assert.doesNotThrow(() => buildNoteRecord({}, {}));
  assert.doesNotThrow(() => buildNoteRecord(42, {}));
  assert.equal(buildNoteRecord({}, {}).kind, 'freeform');
  assert.equal(buildNoteRecord(42, {}).kind, 'freeform');
});

test('buildNoteRecord: non-string field values are coerced via String()', () => {
  const rec = buildNoteRecord('paper', { paperId: 123, paperTitle: 456 });
  assert.equal(rec.paper_id, '123');
  assert.equal(rec.paper_title, '456');
});

// ---------------------------------------------------------------------------
// origin: flattened at the chokepoint (Task 3)
// ---------------------------------------------------------------------------

test('an origin is flattened onto the record', () => {
  const r = buildNoteRecord('freeform', {
    comment: 'worth chasing',
    origin: { kind: 'gap', id: 'gap_85c6f47740cf', label: 'Expand evaluations' },
  });
  assert.equal(r.origin_kind, 'gap');
  assert.equal(r.origin_id, 'gap_85c6f47740cf');
  assert.equal(r.origin_label, 'Expand evaluations');
});

test('a record with no origin still carries three empty origin fields', () => {
  // Five of the six producers pass no origin. They must still produce a
  // valid record — an absent origin is a normal note, not a broken one.
  const r = buildNoteRecord('reader', { paperId: 'arxiv:2205.14135' });
  assert.equal(r.origin_kind, '');
  assert.equal(r.origin_id, '');
  assert.equal(r.origin_label, '');
});

test('a malformed origin degrades to empty rather than throwing', () => {
  for (const origin of [null, 'gap', 7, [], undefined]) {
    assert.doesNotThrow(() => buildNoteRecord('freeform', { origin }));
    const r = buildNoteRecord('freeform', { origin });
    assert.equal(r.origin_kind, '');
    assert.equal(r.origin_id, '');
    assert.equal(r.origin_label, '');
  }
});

test('a partial origin fills what it has and blanks the rest', () => {
  // An Ask note has a question but no durable id for it — label-only is a
  // legitimate origin, not a malformed one.
  const r = buildNoteRecord('ask', { origin: { kind: 'ask', label: 'Why FlashAttention?' } });
  assert.equal(r.origin_kind, 'ask');
  assert.equal(r.origin_id, '');
  assert.equal(r.origin_label, 'Why FlashAttention?');
});

test('origin_kind is NOT constrained to the note KINDS list', () => {
  // kind and origin_kind are different fields. `kind` is validated at the
  // API boundary (lab_api.py:2874) against six values; origin_kind is
  // provenance and is deliberately open, so a future origin needs no
  // schema change. A note FROM a gap is still kind 'freeform'.
  const r = buildNoteRecord('freeform', { origin: { kind: 'gap', id: 'g1', label: 'x' } });
  assert.equal(r.kind, 'freeform');
  assert.equal(r.origin_kind, 'gap');
});
