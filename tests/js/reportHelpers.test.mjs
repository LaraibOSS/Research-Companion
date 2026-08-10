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
