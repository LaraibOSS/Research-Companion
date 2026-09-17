/**
 * Navigating to another surface and carrying an argument.
 *
 * Two real bugs motivated these being one tested place rather than seven
 * hand-rolled ones:
 *
 *   1. `views/library.js` read `e.detail.paperId`, while gaps, report,
 *      timeline and brainstorm all dispatched `paper_id`. Five of the seven
 *      "open this paper" edges in the product were dead through the event
 *      path, and only appeared to work because each one also wrote a
 *      `window.__rcPendingPaper` fallback that is drained on mount. Already on
 *      Library, the hash never changes, the view never remounts, and the click
 *      did nothing at all.
 *
 *   2. `views/suggestions.js` linked to `#/draft?section=<id>`, and
 *      `views/draft.js` never read the hash — so a suggestion that says "this
 *      is about section 4" landed you on section 1.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { paperIdFromDetail, paperIdsFromDetail, sectionFromHash } from
  '../../research_companion/lab/static/js/handoffHelpers.js';

// ---------------------------------------------------------------------------
// paperIdFromDetail — accepts either spelling on purpose
// ---------------------------------------------------------------------------

test('the canonical camelCase key is read', () => {
  assert.equal(paperIdFromDetail({ paperId: 'arxiv:2205.14135' }), 'arxiv:2205.14135');
});

test('the snake_case key five dispatchers used is also read', () => {
  // Accepting both is deliberate. The alternative — normalise every caller and
  // trust it stays normalised — is what broke, silently, across five files.
  assert.equal(paperIdFromDetail({ paper_id: 'doi:10.1145/1' }), 'doi:10.1145/1');
});

test('when both are present the canonical one wins', () => {
  assert.equal(paperIdFromDetail({ paperId: 'a', paper_id: 'b' }), 'a');
});

test('an empty id is not an id', () => {
  for (const d of [{ paperId: '' }, { paper_id: '' }, { paperId: '   ' }]) {
    assert.equal(paperIdFromDetail(d), null);
  }
});

test('a non-string id is refused rather than coerced', () => {
  for (const d of [{ paperId: 7 }, { paper_id: {} }, { paperId: ['x'] }]) {
    assert.equal(paperIdFromDetail(d), null);
  }
});

test('reading an id never throws', () => {
  for (const d of [null, undefined, {}, 'nope', 3, []]) {
    assert.doesNotThrow(() => paperIdFromDetail(d));
    assert.equal(paperIdFromDetail(d), null);
  }
});

// ---------------------------------------------------------------------------
// paperIdsFromDetail — Compare hands over two at once
// ---------------------------------------------------------------------------

test('a list of ids comes back as a list', () => {
  assert.deepEqual(paperIdsFromDetail({ paperIds: ['a', 'b'] }), ['a', 'b']);
});

test('a single id comes back as a list of one, either spelling', () => {
  assert.deepEqual(paperIdsFromDetail({ paperId: 'a' }), ['a']);
  assert.deepEqual(paperIdsFromDetail({ paper_id: 'b' }), ['b']);
});

test('blanks and non-strings are dropped from a list', () => {
  assert.deepEqual(paperIdsFromDetail({ paperIds: ['a', '', null, 4, ' ', 'b'] }), ['a', 'b']);
});

test('duplicates collapse — opening the same paper twice is one drawer', () => {
  assert.deepEqual(paperIdsFromDetail({ paperIds: ['a', 'a', 'b'] }), ['a', 'b']);
});

test('reading ids never throws', () => {
  for (const d of [null, undefined, {}, 'nope', { paperIds: 'a' }, { paperIds: null }]) {
    assert.doesNotThrow(() => paperIdsFromDetail(d));
    assert.ok(Array.isArray(paperIdsFromDetail(d)));
  }
});

// ---------------------------------------------------------------------------
// sectionFromHash — mirrors what graph.js already does correctly
// ---------------------------------------------------------------------------

test('a section is read out of the hash', () => {
  assert.equal(sectionFromHash('#/draft?section=s4'), 's4');
});

test('an encoded section id is decoded', () => {
  assert.equal(sectionFromHash('#/draft?section=2%20Background'), '2 Background');
});

test('the section is found alongside other params, in any order', () => {
  assert.equal(sectionFromHash('#/draft?mode=x&section=s2'), 's2');
  assert.equal(sectionFromHash('#/draft?section=s2&mode=x'), 's2');
});

test('no section param means no section', () => {
  for (const h of ['#/draft', '#/draft?mode=x', '', '#']) {
    assert.equal(sectionFromHash(h), null);
  }
});

test('an empty section param is not a section', () => {
  assert.equal(sectionFromHash('#/draft?section='), null);
});

test('a param that merely ends in "section" is not matched', () => {
  // `subsection=` must not satisfy a request for `section=`.
  assert.equal(sectionFromHash('#/draft?subsection=s9'), null);
});

test('reading a section never throws', () => {
  for (const h of [null, undefined, 3, {}, '#/draft?section=%E0%A4%A']) {
    assert.doesNotThrow(() => sectionFromHash(h));
  }
});
