/**
 * tests/js/glossary.test.mjs — Node test for js/glossary.js
 * Run: node --test tests/js/glossary.test.mjs
 */
import { strict as assert } from 'node:assert';
import { test } from 'node:test';
import { GLOSSARY, tip } from '../../research_companion/lab/static/js/glossary.js';

const CANONICAL = [
  'verified', 'unverified', 'band', 'strength', 'stance',
  'strengthens', 'challenges', 'alternative',
  'grounded', 'cited', 'gap', 'severity', 'hybrid', 'bm25',
  'rcs_relevance', 'rcs_stance',
];

test('every canonical term has a non-empty definition', () => {
  for (const term of CANONICAL) {
    assert.ok(
      GLOSSARY[term] && GLOSSARY[term].length > 0,
      `GLOSSARY missing or empty: "${term}"`,
    );
  }
});

test('tip() returns data-tip attribute string for known term', () => {
  const result = tip('strength');
  assert.ok(
    result.startsWith(' data-tip="'),
    `tip() must return " data-tip=\\"...\\"", got: ${result}`,
  );
  assert.ok(result.endsWith('"'), `tip() must close with double-quote`);
});

test('tip() returns empty string for unknown term', () => {
  assert.strictEqual(tip('__unknown__term__'), '');
});

test('tip() escapes double-quotes in tooltip text', () => {
  // Temporarily inject a test entry with quotes
  const saved = GLOSSARY['__test_quote__'];
  GLOSSARY['__test_quote__'] = 'Has "quotes" inside';
  const result = tip('__test_quote__');
  assert.ok(
    !result.includes('"quotes"'),
    'tip() must not leave raw double-quotes in attribute value',
  );
  assert.ok(
    result.includes('&quot;') || result.includes('&#34;'),
    'tip() must use HTML entity for double-quotes',
  );
  if (saved !== undefined) {
    GLOSSARY['__test_quote__'] = saved;
  } else {
    delete GLOSSARY['__test_quote__'];
  }
});
