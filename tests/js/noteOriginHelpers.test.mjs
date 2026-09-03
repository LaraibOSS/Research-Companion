/**
 * Resolving a note's recorded origin to a route.
 *
 * The return path is DERIVED from (kind, id) here rather than stored in the
 * note, so a route rename cannot orphan every note ever written.
 *
 * Stale ids are expected, not exceptional: a theme_id is derived from its
 * member gap_ids, so a re-clustering run can orphan one. That is why an
 * origin carries a label as well as an id — the note stays readable after
 * the link stops resolving.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { originLink, themeFromHash } from
  '../../research_companion/lab/static/js/noteOriginHelpers.js';

// ---------------------------------------------------------------------------
// originLink
// ---------------------------------------------------------------------------

test('a gap origin resolves to the gaps route carrying its theme', () => {
  const r = originLink({ kind: 'gap', id: 'gap_85c6f47740cf', label: 'Expand evaluations' });
  assert.equal(r.href, '#/gaps?theme=gap_85c6f47740cf');
  assert.equal(r.label, 'Expand evaluations');
  assert.equal(r.canOpen, true);
  assert.equal(r.badge, '◇ Gap');
});

test('a theme id is percent-encoded into the href', () => {
  const r = originLink({ kind: 'gap', id: 'a b&c', label: 'x' });
  assert.equal(r.href, '#/gaps?theme=a%20b%26c');
  assert.equal(r.badge, '◇ Gap');
});

test('an unknown kind keeps its label but cannot be opened', () => {
  // Forward compatibility: a note written by a later version, holding an
  // origin this version has no route for, must still read.
  const r = originLink({ kind: 'constellation', id: 'c1', label: 'Some future thing' });
  assert.equal(r.canOpen, false);
  assert.equal(r.href, null);
  assert.equal(r.label, 'Some future thing');
  assert.equal(r.badge, '');
});

test('a known kind with no id cannot be opened but keeps its label', () => {
  // An Ask origin: the question is the only durable handle, there is no id.
  const r = originLink({ kind: 'ask', id: '', label: 'Why FlashAttention?' });
  assert.equal(r.canOpen, false);
  assert.equal(r.href, null);
  assert.equal(r.label, 'Why FlashAttention?');
  assert.equal(r.badge, '? Question');
});

test('an empty origin is not an origin', () => {
  const r = originLink({ kind: '', id: '', label: '' });
  assert.equal(r.canOpen, false);
  assert.equal(r.label, '');
});

test('resolving an origin never throws', () => {
  for (const o of [null, undefined, {}, 'gap', 7, []]) {
    assert.doesNotThrow(() => originLink(o));
    const r = originLink(o);
    assert.equal(r.canOpen, false);
    assert.equal(r.label, '');
    assert.equal(r.href, null);
  }
});

test('a non-string label is refused rather than coerced', () => {
  // String(7) would render "7" as if it were a real label.
  const r = originLink({ kind: 'gap', id: 'g1', label: 7 });
  assert.equal(r.label, '');
});

test('an id with unpaired UTF-16 surrogate does not throw', () => {
  // encodeURIComponent('\uD800') throws URIError: URI malformed.
  // Degrade to non-openable, preserving label, like any other encoding failure.
  assert.doesNotThrow(() => originLink({ kind: 'gap', id: '\uD800', label: 'x' }));
  const r = originLink({ kind: 'gap', id: '\uD800', label: 'My Gap' });
  assert.equal(r.canOpen, false);
  assert.equal(r.href, null);
  assert.equal(r.label, 'My Gap');
  assert.equal(r.badge, '◇ Gap');
});

// ---------------------------------------------------------------------------
// themeFromHash — mirrors sectionFromHash in handoffHelpers.js
// ---------------------------------------------------------------------------

test('a theme is read out of the hash', () => {
  assert.equal(themeFromHash('#/gaps?theme=gap_1'), 'gap_1');
});

test('an encoded theme id is decoded', () => {
  assert.equal(themeFromHash('#/gaps?theme=a%20b'), 'a b');
});

test('the theme is found alongside other params, in any order', () => {
  assert.equal(themeFromHash('#/gaps?sort=score&theme=g2'), 'g2');
  assert.equal(themeFromHash('#/gaps?theme=g2&sort=score'), 'g2');
});

test('no theme param means no theme', () => {
  for (const h of ['#/gaps', '#/gaps?sort=score', '', '#']) {
    assert.equal(themeFromHash(h), null);
  }
});

test('an empty theme param is not a theme', () => {
  assert.equal(themeFromHash('#/gaps?theme='), null);
});

test('a param that merely ends in "theme" is not matched', () => {
  // `subtheme=` must not satisfy a request for `theme=`.
  assert.equal(themeFromHash('#/gaps?subtheme=g9'), null);
});

test('reading a theme never throws', () => {
  for (const h of [null, undefined, 3, {}, '#/gaps?theme=%E0%A4%A']) {
    assert.doesNotThrow(() => themeFromHash(h));
  }
});

test('a round trip survives itself', () => {
  const id = 'gap_85c6f47740cf';
  assert.equal(themeFromHash(originLink({ kind: 'gap', id, label: 'x' }).href), id);
});
