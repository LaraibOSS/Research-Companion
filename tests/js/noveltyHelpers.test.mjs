/**
 * tests/js/noveltyHelpers.test.mjs — pure Novelty Gate (Brainstorm 2c)
 * display helpers.
 * Run: node --test tests/js/noveltyHelpers.test.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { noveltyResultModel } from '../../research_companion/lab/static/js/noveltyHelpers.js';

test('noveltyResultModel: novel verdict maps to a positive badge', () => {
  const m = noveltyResultModel({
    verdict: 'novel', confidence: 0.8, rationale: 'No close prior work.',
    closest_prior: [], prior_works: [], query: 'q',
  });
  assert.equal(m.verdictBadge.slug, 'positive');
  assert.equal(m.verdictBadge.label, 'Novel');
  assert.equal(m.confidencePct, 80);
  assert.equal(m.rationale, 'No close prior work.');
  assert.equal(m.hasResult, true);
  assert.equal(m.error, null);
});

test('noveltyResultModel: incremental and overlaps verdicts map to caution', () => {
  const a = noveltyResultModel({ verdict: 'incremental', confidence: 0.5 });
  const b = noveltyResultModel({ verdict: 'overlaps', confidence: 0.5 });
  assert.equal(a.verdictBadge.slug, 'caution');
  assert.equal(a.verdictBadge.label, 'Incremental');
  assert.equal(b.verdictBadge.slug, 'caution');
  assert.equal(b.verdictBadge.label, 'Overlaps');
});

test('noveltyResultModel: anticipated verdict maps to negative', () => {
  const m = noveltyResultModel({ verdict: 'anticipated', confidence: 0.9 });
  assert.equal(m.verdictBadge.slug, 'negative');
  assert.equal(m.verdictBadge.label, 'Anticipated');
});

test('noveltyResultModel: null/unknown verdict maps to a "none" badge', () => {
  const a = noveltyResultModel({ verdict: null });
  const b = noveltyResultModel({ verdict: 'not_a_real_verdict' });
  assert.equal(a.verdictBadge.slug, 'none');
  assert.equal(a.verdictBadge.label, 'No verdict yet');
  assert.equal(b.verdictBadge.slug, 'none');
});

test('noveltyResultModel: confidencePct rounds and clamps to 0-100', () => {
  assert.equal(noveltyResultModel({ confidence: 0.567 }).confidencePct, 57);
  assert.equal(noveltyResultModel({ confidence: 5 }).confidencePct, 100);
  assert.equal(noveltyResultModel({ confidence: -3 }).confidencePct, 0);
  assert.equal(noveltyResultModel({ confidence: 'not-a-number' }).confidencePct, 0);
  assert.equal(noveltyResultModel({}).confidencePct, 0);
});

test('noveltyResultModel: priorWorks maps title/year to a pre-escaped label, raw url', () => {
  const m = noveltyResultModel({
    prior_works: [
      { title: 'A <b>Paper</b>', year: 2021, url: 'https://example.com/a' },
      { title: 'No Year Paper', year: null, url: '' },
    ],
  });
  assert.equal(m.priorWorks.length, 2);
  assert.equal(m.priorWorks[0].label, 'A &lt;b&gt;Paper&lt;/b&gt; (2021)');
  assert.equal(m.priorWorks[0].url, 'https://example.com/a');
  assert.equal(m.priorWorks[1].label, 'No Year Paper');
  assert.equal(m.priorWorks[1].url, '');
});

test('noveltyResultModel: error string is HTML-escaped, absent error is null', () => {
  const withError = noveltyResultModel({ error: '<script>alert(1)</script>' });
  assert.equal(withError.error, '&lt;script&gt;alert(1)&lt;/script&gt;');
  const withoutError = noveltyResultModel({ verdict: 'novel' });
  assert.equal(withoutError.error, null);
});

test('noveltyResultModel: hasResult is false for null/undefined, true for an object', () => {
  assert.equal(noveltyResultModel(null).hasResult, false);
  assert.equal(noveltyResultModel(undefined).hasResult, false);
  assert.equal(noveltyResultModel({}).hasResult, true);
});

test('noveltyResultModel: never throws for garbage input', () => {
  assert.doesNotThrow(() => noveltyResultModel(42));
  assert.doesNotThrow(() => noveltyResultModel('a string'));
  assert.doesNotThrow(() => noveltyResultModel([1, 2, 3]));
  assert.doesNotThrow(() => noveltyResultModel(() => {}));
});
