/**
 * tests/js/reportHelpers.test.mjs — pure Deep-Research Report (2e-1)
 * display helpers.
 * Run: node --test tests/js/reportHelpers.test.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  reportSectionModel,
  reportCoverageModel,
  reportPlanModel,
  reportEmptyState,
  reportCostLine,
  reportPlanStatus,
} from '../../research_companion/lab/static/js/reportHelpers.js';

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

test('array rcs value yields no badge (not a defaulted object)', () => {
  const m = reportSectionModel({
    question: 'Q', answer: 'A',
    citations: [{ paper_id: 'p1', paper_title: 'P1', rcs: [] }],
  });
  assert.equal(m.citations[0].rcs, null);
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


// ---------------------------------------------------------------------------
// Report Coverage / Saturation section + report-level model (2e-3)
// ---------------------------------------------------------------------------

test('section coverage present builds a numeric display model', () => {
  const m = reportSectionModel({
    question: 'Q?', answer: 'A [S1].', citations: [],
    coverage: { pct: 62, cited: 5, relevant_available: 8 },
  });
  assert.deepEqual(m.coverage, { pct: 62, cited: 5, relevantAvailable: 8, tip: 'coverage' });
});

test('section coverage absent means null, no crash', () => {
  const m = reportSectionModel({ question: 'Q', answer: 'A', citations: [] });
  assert.equal(m.coverage, null);
});

test('section coverage malformed (array/string/number) means null, never throws', () => {
  assert.doesNotThrow(() => {
    assert.equal(reportSectionModel({ coverage: [] }).coverage, null);
    assert.equal(reportSectionModel({ coverage: 'nope' }).coverage, null);
    assert.equal(reportSectionModel({ coverage: 42 }).coverage, null);
  });
});

test('section coverage pct is clamped to [0,100] and rounded', () => {
  const m = reportSectionModel({
    question: 'Q', answer: 'A', citations: [],
    coverage: { pct: 142.6, cited: 3, relevant_available: 3 },
  });
  assert.equal(m.coverage.pct, 100);
});

test('section coverage negative/non-numeric counts default to 0', () => {
  const m = reportSectionModel({
    question: 'Q', answer: 'A', citations: [],
    coverage: { pct: 0, cited: -5, relevant_available: 'nope' },
  });
  assert.equal(m.coverage.cited, 0);
  assert.equal(m.coverage.relevantAvailable, 0);
});

test('reportCoverageModel maps the top-level report coverage field with medianPct', () => {
  const m = reportCoverageModel({
    coverage: { pct: 55, cited: 11, relevant_available: 20, median_pct: 60 },
  });
  assert.deepEqual(m, { pct: 55, cited: 11, relevantAvailable: 20, tip: 'coverage', medianPct: 60 });
});

test('reportCoverageModel returns null when the report has no coverage field', () => {
  assert.equal(reportCoverageModel({}), null);
  assert.equal(reportCoverageModel(null), null);
  assert.equal(reportCoverageModel(42), null);
});


// ---------------------------------------------------------------------------
// reportPlanModel (Editable Research Plan, 2e-4)
// ---------------------------------------------------------------------------

test('reportPlanModel: draft status maps questions and filters blanks', () => {
  const m = reportPlanModel({
    topic: 't', status: 'draft',
    questions: ['What methods are used?', '  ', 'What datasets are used?', 42],
  });
  assert.deepEqual(m, { status: 'draft', questions: ['What methods are used?', 'What datasets are used?'] });
});

test('reportPlanModel: answered status escapes question text', () => {
  const m = reportPlanModel({ topic: 't', status: 'answered', questions: ['<b>Q1</b>?'] });
  assert.deepEqual(m, { status: 'answered', questions: ['&lt;b&gt;Q1&lt;/b&gt;?'] });
});

test('reportPlanModel: null/garbage plan returns null', () => {
  assert.equal(reportPlanModel(null), null);
  assert.equal(reportPlanModel(undefined), null);
  assert.equal(reportPlanModel(42), null);
  assert.equal(reportPlanModel('a string'), null);
  assert.equal(reportPlanModel([1, 2, 3]), null);
});

test('reportPlanModel: unknown status returns null', () => {
  assert.equal(reportPlanModel({ status: 'bogus', questions: ['Q?'] }), null);
  assert.equal(reportPlanModel({ questions: ['Q?'] }), null);
});

test('reportPlanModel: non-array questions defaults to empty array', () => {
  const m = reportPlanModel({ status: 'draft', questions: 'not an array' });
  assert.deepEqual(m, { status: 'draft', questions: [] });
});

test('reportPlanModel: never throws with garbage question entries', () => {
  assert.doesNotThrow(() => reportPlanModel({ status: 'draft', questions: [null, 42, {}, ['x']] }));
});

// ---------------------------------------------------------------------------
// Page copy — empty state, cost expectation, plan status.
//
// The property under test is honesty about the two things a user is about to
// spend: their papers and their money. A Generate button that cannot help, and
// a costed pass with no warning, are the two ways this page loses trust.
// ---------------------------------------------------------------------------

test('reportEmptyState: an empty library is a blocking prerequisite, not a caveat', () => {
  const s = reportEmptyState({ paperCount: 0 });
  assert.equal(s.blocked, true);
  assert.match(s.headline, /empty/i);
  // it must say where to go, or the user is stuck on a dead button
  assert.match(s.tip, /Discover|Add paper/);
});

test('reportEmptyState: a small library reads thin, which is not an error', () => {
  const s = reportEmptyState({ paperCount: 3 });
  assert.equal(s.blocked, false);
  assert.match(s.detail, /3 papers/);
  assert.match(s.detail, /thin coverage rather than a wrong answer/);
});

test('reportEmptyState: stops nagging once the library is big enough', () => {
  const s = reportEmptyState({ paperCount: 42 });
  assert.equal(s.blocked, false);
  assert.doesNotMatch(s.detail, /thin/i);
  assert.match(s.detail, /42 papers/);
});

test('reportEmptyState: says "1 paper", not "1 papers"', () => {
  assert.match(reportEmptyState({ paperCount: 1 }).detail, /1 paper\b/);
});

test('reportEmptyState: a nonsense count still produces usable copy', () => {
  for (const bad of [undefined, null, NaN, -5, 'seven']) {
    const s = reportEmptyState({ paperCount: bad });
    assert.equal(typeof s.headline, 'string');
    assert.ok(s.headline.length > 0);
  }
  assert.equal(reportEmptyState().blocked, true);
});

test('reportEmptyState: points at the plan before the costed pass', () => {
  assert.match(reportEmptyState({ paperCount: 20 }).tip, /plan first/i);
});

test('reportCostLine: gives a range when the question count is unknown', () => {
  const line = reportCostLine({});
  assert.match(line, /model call/);
  assert.match(line, /free/);
});

test('reportCostLine: is exact once a plan pins the question count', () => {
  assert.match(reportCostLine({ questionCount: 6 }), /6 model calls/);
  assert.match(reportCostLine({ questionCount: 1 }), /1 model call\b/);
});

test('reportCostLine: always states a cost — silence would read as free', () => {
  for (const n of [null, undefined, 0, -3, 'x']) {
    assert.ok(reportCostLine({ questionCount: n }).length > 0);
  }
});

test('reportCostLine: names the free path in both forms', () => {
  assert.match(reportCostLine({}), /free/);
  assert.match(reportCostLine({ questionCount: 5 }), /free/);
});

test('reportPlanStatus: reads "not yet run", not the internal status word', () => {
  const line = reportPlanStatus({ status: 'draft', questions: ['a', 'b'] });
  assert.match(line, /2 questions, not yet run/);
  // "draft" is a state name, not something a user should have to decode
  assert.doesNotMatch(line, /\(draft\)/);
});

test('reportPlanStatus: distinguishes the free edit from the costed run', () => {
  const line = reportPlanStatus({ status: 'draft', questions: ['a'] });
  assert.match(line, /free/);
  assert.match(line, /answering is not/);
});

test('reportPlanStatus: reports an answered plan as answered', () => {
  assert.match(reportPlanStatus({ status: 'answered', questions: ['a'] }),
    /1 question, answered/);
});

test('reportPlanStatus: returns empty for no plan rather than inventing one', () => {
  assert.equal(reportPlanStatus(null), '');
  assert.equal(reportPlanStatus(undefined), '');
  assert.equal(reportPlanStatus({ status: 'draft' }), '');
});
