import test from 'node:test';
import assert from 'node:assert/strict';
import { findPdfAffordance, oaLinksLine } from '../../research_companion/lab/static/js/oaLinkHelpers.js';

test('affordance matrix', () => {
  assert.equal(findPdfAffordance({ status: 'done' }), 'hidden');
  assert.equal(findPdfAffordance({ status: 'failed', failure_reason: 'no PDF on disk' }), 'button');
  assert.equal(findPdfAffordance({ status: 'failed', failure_reason: 'PDF not found: x' , oa_links: [{label:'DOI page', url:'https://doi.org/10.1/x'}]}), 'button-with-links');
  assert.equal(findPdfAffordance({ status: 'failed', failure_reason: 'extraction crashed' }), 'hidden');
});

test('oaLinksLine filters junk and caps at 5', () => {
  const items = [
    { label: 'A', url: 'https://a' }, { label: '', url: 'https://b' },
    { label: 'C', url: 'javascript:alert(1)' }, { label: 'D' },
    { label: 'E', url: 'https://e' }, { label: 'F', url: 'https://f' },
    { label: 'G', url: 'https://g' }, { label: 'H', url: 'https://h' },
    { label: 'I', url: 'https://i' },
  ];
  const out = oaLinksLine(items);
  assert.equal(out.show, true);
  assert.ok(out.items.length <= 5);
  assert.ok(out.items.every(l => /^https?:\/\//.test(l.url) && l.label));
  assert.deepEqual(oaLinksLine([]), { show: false, items: [] });
  assert.deepEqual(oaLinksLine(undefined), { show: false, items: [] });
});
