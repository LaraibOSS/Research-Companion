/**
 * tests/js/reportHelpers.test.mjs — pure Deep-Research Report (2e-1)
 * display helpers.
 * Run: node --test tests/js/reportHelpers.test.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { reportSectionModel } from '../../research_companion/lab/static/js/reportHelpers.js';

test('reportSectionModel: happy path escapes question/answer and builds citation chips', () => {
  const m = reportSectionModel({
    question: 'What methods <b>are</b> used?',
    answer: 'Graph retrieval is used [S1].',
    citations: [
      { paper_id: 'arxiv:1234.56789', paper_title: 'Graph Retrieval Paper', section_id: 's1',
        char_start: 0, char_end: 100, chunk_index: 0, score: 2.5 },
    ],
    unverified_quotes: [],
  });
  assert.equal(m.question, 'What methods &lt;b&gt;are&lt;/b&gt; used?');
  assert.equal(m.answer, 'Graph retrieval is used [S1].');
  assert.equal(m.hasError, false);
  assert.equal(m.errorMessage, null);
  assert.equal(m.citations.length, 1);
  assert.equal(m.citations[0].label, 'Graph Retrieval Paper');
  assert.equal(m.citations[0].paperId, 'arxiv:1234.56789');
  assert.equal(m.citations[0].sectionId, 's1');
  assert.deepEqual(m.unverifiedQuotes, []);
});

test('reportSectionModel: error section sets hasError and errorMessage', () => {
  const m = reportSectionModel({
    question: 'Bad question?', answer: '', citations: [], unverified_quotes: [],
    error: 'retrieval exploded',
  });
  assert.equal(m.hasError, true);
  assert.equal(m.errorMessage, 'retrieval exploded');
});

test('reportSectionModel: escapes unverified quotes', () => {
  const m = reportSectionModel({
    question: 'Q?', answer: 'A', citations: [],
    unverified_quotes: ['<script>bad</script> a long enough quote span'],
  });
  assert.equal(m.unverifiedQuotes[0], '&lt;script&gt;bad&lt;/script&gt; a long enough quote span');
});

test('reportSectionModel: missing/malformed fields default safely', () => {
  const m = reportSectionModel({});
  assert.equal(m.question, 'Untitled question');
  assert.equal(m.answer, '');
  assert.deepEqual(m.citations, []);
  assert.deepEqual(m.unverifiedQuotes, []);
  assert.equal(m.hasError, false);
});

test('reportSectionModel: citation with missing paper_title defaults to Untitled', () => {
  const m = reportSectionModel({ question: 'Q', answer: 'A', citations: [{}] });
  assert.equal(m.citations[0].label, 'Untitled');
  assert.equal(m.citations[0].paperId, '');
});

test('reportSectionModel: never throws for garbage input', () => {
  assert.doesNotThrow(() => reportSectionModel(null));
  assert.doesNotThrow(() => reportSectionModel(undefined));
  assert.doesNotThrow(() => reportSectionModel(42));
  assert.doesNotThrow(() => reportSectionModel('a string'));
  assert.doesNotThrow(() => reportSectionModel([1, 2, 3]));
});


// ---------------------------------------------------------------------------
// Report Evidence Scoring (RCS) badge sub-model (2e-2)
// ---------------------------------------------------------------------------

test('citation rcs present builds a badge sub-model', () => {
  const m = reportSectionModel({
    question: 'Q?', answer: 'A [S1].',
    citations: [{
      paper_id: 'p1', paper_title: 'Paper One', section_id: 's1',
      rcs: { relevance: 0.87, stance: 'supports', rationale: 'Directly backs the claim.' },
    }],
    unverified_quotes: [],
  });
  const rcs = m.citations[0].rcs;
  assert.ok(rcs);
  assert.equal(rcs.relevancePct, 87);
  assert.equal(rcs.stanceSlug, 'supports');
  assert.equal(rcs.stanceIcon, '▲');
  assert.equal(rcs.rationale, 'Directly backs the claim.');
  assert.equal(rcs.tipRelevance, 'rcs_relevance');
  assert.equal(rcs.tipStance, 'rcs_stance');
});

test('rcs stance contradicts/neutral map to the challenges/alternative icons', () => {
  const m = reportSectionModel({
    question: 'Q', answer: 'A',
    citations: [
      { paper_id: 'p1', paper_title: 'P1', rcs: { relevance: 0.5, stance: 'contradicts', rationale: 'x' } },
      { paper_id: 'p2', paper_title: 'P2', rcs: { relevance: 0.5, stance: 'neutral', rationale: 'y' } },
    ],
  });
  assert.equal(m.citations[0].rcs.stanceIcon, '⚡');
  assert.equal(m.citations[1].rcs.stanceIcon, '◆');
});

test('rcs escapes the rationale', () => {
  const m = reportSectionModel({
    question: 'Q', answer: 'A',
    citations: [{ paper_id: 'p1', paper_title: 'P1',
      rcs: { relevance: 0.5, stance: 'supports', rationale: '<script>bad</script>' } }],
  });
  assert.equal(m.citations[0].rcs.rationale, '&lt;script&gt;bad&lt;/script&gt;');
});

test('absent/null rcs means no badge', () => {
  const m = reportSectionModel({
    question: 'Q', answer: 'A',
    citations: [{ paper_id: 'p1', paper_title: 'P1' }, { paper_id: 'p2', paper_title: 'P2', rcs: null }],
  });
  assert.equal(m.citations[0].rcs, null);
  assert.equal(m.citations[1].rcs, null);
});

test('malformed rcs fields default safely and never throw', () => {
  const m = reportSectionModel({
    question: 'Q', answer: 'A',
    citations: [{ paper_id: 'p1', paper_title: 'P1',
      rcs: { relevance: 'not a number', stance: 'bogus', rationale: 42 } }],
  });
  const rcs = m.citations[0].rcs;
  assert.equal(rcs.relevancePct, 0);
  assert.equal(rcs.stanceSlug, 'neutral');
  assert.equal(rcs.stanceIcon, '◆');
  assert.equal(rcs.rationale, '');
});

test('relevance is clamped to [0,1] before converting to a percent', () => {
  const m = reportSectionModel({
    question: 'Q', answer: 'A',
    citations: [{ paper_id: 'p1', paper_title: 'P1',
      rcs: { relevance: 1.5, stance: 'supports', rationale: 'x' } }],
  });
  assert.equal(m.citations[0].rcs.relevancePct, 100);
});

test('reportSectionModel never throws with garbage rcs values', () => {
  assert.doesNotThrow(() => reportSectionModel({
    citations: [{ rcs: 'not an object' }, { rcs: 42 }, { rcs: [] }],
  }));
});
