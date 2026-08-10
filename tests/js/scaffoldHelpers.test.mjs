/**
 * tests/js/scaffoldHelpers.test.mjs — pure "Draft this direction"
 * (Brainstorm 2d) display helpers.
 * Run: node --test tests/js/scaffoldHelpers.test.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { scaffoldPanelModel } from '../../research_companion/lab/static/js/scaffoldHelpers.js';

test('scaffoldPanelModel: null/undefined state is the idle button state', () => {
  const a = scaffoldPanelModel(null);
  const b = scaffoldPanelModel(undefined);
  assert.equal(a.status, 'idle');
  assert.equal(a.openDraftRoute, '#/draft');
  assert.equal(a.errorMessage, null);
  assert.equal(a.successMessage, null);
  assert.deepEqual(b, a);
});

test('scaffoldPanelModel: no result yet (empty object) is idle', () => {
  assert.equal(scaffoldPanelModel({}).status, 'idle');
  assert.equal(scaffoldPanelModel({ loading: false, error: null, result: null }).status, 'idle');
});

test('scaffoldPanelModel: loading state', () => {
  const m = scaffoldPanelModel({ loading: true });
  assert.equal(m.status, 'loading');
  assert.equal(m.errorMessage, null);
});

test('scaffoldPanelModel: error state escapes the message', () => {
  const m = scaffoldPanelModel({ loading: false, error: '<script>alert(1)</script>', result: null });
  assert.equal(m.status, 'error');
  assert.equal(m.errorMessage, '&lt;script&gt;alert(1)&lt;/script&gt;');
});

test('scaffoldPanelModel: success state with sectionCount and not replaced', () => {
  const m = scaffoldPanelModel({
    loading: false, error: null,
    result: { section_count: 6, replaced_draft: false },
  });
  assert.equal(m.status, 'success');
  assert.equal(m.sectionCount, 6);
  assert.equal(m.replaced, false);
  assert.equal(m.successMessage, 'Draft created with 6 sections.');
  assert.equal(m.openDraftRoute, '#/draft');
});

test('scaffoldPanelModel: success state singular section', () => {
  const m = scaffoldPanelModel({ result: { section_count: 1, replaced_draft: false } });
  assert.equal(m.successMessage, 'Draft created with 1 section.');
});

test('scaffoldPanelModel: replaced_draft true says so plainly', () => {
  const m = scaffoldPanelModel({ result: { section_count: 8, replaced_draft: true } });
  assert.equal(m.replaced, true);
  assert.equal(m.successMessage, 'Replaced your previous draft — 8 sections.');
});

test('scaffoldPanelModel: missing/malformed result fields default safely', () => {
  const m = scaffoldPanelModel({ result: {} });
  assert.equal(m.status, 'success');
  assert.equal(m.sectionCount, 0);
  assert.equal(m.replaced, false);
  assert.equal(m.successMessage, 'Draft created with 0 sections.');
});

test('scaffoldPanelModel: never throws for garbage input', () => {
  assert.doesNotThrow(() => scaffoldPanelModel(42));
  assert.doesNotThrow(() => scaffoldPanelModel('a string'));
  assert.doesNotThrow(() => scaffoldPanelModel([1, 2, 3]));
  assert.doesNotThrow(() => scaffoldPanelModel(() => {}));
});
