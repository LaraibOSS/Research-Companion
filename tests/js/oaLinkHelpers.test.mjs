import test from 'node:test';
import assert from 'node:assert/strict';
import { findPdfAffordance, oaLinksLine, pollDecision, acquisitionAllowsHelp } from '../../research_companion/lab/static/js/oaLinkHelpers.js';

test('affordance matrix', () => {
  assert.equal(findPdfAffordance({ status: 'done' }), 'hidden');
  // No acquisition at all -- a legacy "no PDF on disk"/"PDF not found"
  // record from before every acquisition attempt carried a typed
  // Acquisition -- falls back to has_pdf (computed in Python from
  // store.pdf_path, never guessed here): genuinely missing on disk, so
  // the affordance shows.
  assert.equal(findPdfAffordance({ status: 'failed', failure_reason: 'no PDF on disk', has_pdf: false }), 'button');
  assert.equal(findPdfAffordance({ status: 'failed', failure_reason: 'PDF not found: x', has_pdf: false,
    oa_links: [{label:'DOI page', url:'https://doi.org/10.1/x'}]}), 'button-with-links');
  // No acquisition, but the PDF IS present on disk (e.g. a parse/OCR
  // failure) -- must NOT offer to re-fetch and overwrite it.
  assert.equal(findPdfAffordance({ status: 'failed', failure_reason: 'could not parse PDF', has_pdf: true }), 'hidden');
  // No acquisition and no has_pdf signal at all -- must not guess "yes".
  assert.equal(findPdfAffordance({ status: 'failed', failure_reason: 'could not parse PDF' }), 'hidden');
  // An acquisition that explicitly says a person can't help (the machine's
  // problem, e.g. a transient source-unavailable retry) hides it,
  // regardless of has_pdf.
  assert.equal(findPdfAffordance({ status: 'failed', failure_reason: 'timed out',
    acquisition: { human_can_help: false }, has_pdf: false }), 'hidden');
});

test('acquisitionAllowsHelp: trusts the backend acquisition flag when present, regardless of hasPdf', () => {
  assert.equal(acquisitionAllowsHelp({ human_can_help: true }, false), true);
  assert.equal(acquisitionAllowsHelp({ human_can_help: true }, true), true);
  assert.equal(acquisitionAllowsHelp({ human_can_help: false }, false), false);
  assert.equal(acquisitionAllowsHelp({}, undefined), true); // no human_can_help key -> not explicitly false
});

test('acquisitionAllowsHelp: no acquisition falls back to hasPdf, never guesses true', () => {
  assert.equal(acquisitionAllowsHelp(null, false), true, 'genuinely no PDF on disk -> helpable');
  assert.equal(acquisitionAllowsHelp(undefined, false), true);
  assert.equal(acquisitionAllowsHelp(null, true), false, 'a PDF IS on disk -> must not offer to overwrite it');
  assert.equal(acquisitionAllowsHelp(null, undefined), false, 'no signal at all -> safe default is NOT helpable');
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

// ---------------------------------------------------------------------------
// pollDecision — find-pdf job poll state machine
// ---------------------------------------------------------------------------

test('pollDecision: still running, well under the cap -> continue', () => {
  assert.equal(pollDecision({ status: 'running', error: null, consecutiveFailures: 0, elapsedPolls: 1 }), 'continue');
  assert.equal(pollDecision({ status: 'running', error: null, consecutiveFailures: 0, elapsedPolls: 119 }), 'continue');
});

test('pollDecision: poll-count cap reached while still running -> give-up', () => {
  assert.equal(pollDecision({ status: 'running', error: null, consecutiveFailures: 0, elapsedPolls: 120 }), 'give-up');
  assert.equal(pollDecision({ status: 'running', error: null, consecutiveFailures: 0, elapsedPolls: 500 }), 'give-up');
});

test('pollDecision: a definitive 404 always stops, even past the poll cap', () => {
  assert.equal(pollDecision({ error: { status: 404 }, consecutiveFailures: 0, elapsedPolls: 1 }), 'stop-404');
  assert.equal(pollDecision({ error: { status: 404 }, consecutiveFailures: 4, elapsedPolls: 120 }), 'stop-404');
});

test('pollDecision: a non-404 failure retries while under both caps', () => {
  assert.equal(pollDecision({ error: { status: 500 }, consecutiveFailures: 0, elapsedPolls: 3 }), 'retry-transient');
  assert.equal(pollDecision({ error: { status: 500 }, consecutiveFailures: 3, elapsedPolls: 4 }), 'retry-transient');
  // A plain network error (no .status at all) is treated the same as any
  // other non-404 failure -- transient, not a stop signal.
  assert.equal(pollDecision({ error: new Error('network down'), consecutiveFailures: 0, elapsedPolls: 1 }), 'retry-transient');
});

test('pollDecision: consecutive non-404 failures reaching the failure cap -> give-up', () => {
  assert.equal(pollDecision({ error: { status: 500 }, consecutiveFailures: 4, elapsedPolls: 5 }), 'give-up');
  assert.equal(pollDecision({ error: { status: 503 }, consecutiveFailures: 9, elapsedPolls: 10 }), 'give-up');
});

test('pollDecision: the poll-count cap also bounds an otherwise-still-retrying failure streak', () => {
  assert.equal(pollDecision({ error: { status: 500 }, consecutiveFailures: 0, elapsedPolls: 120 }), 'give-up');
});

test('pollDecision: missing/undefined fields default sanely (no error, no counts given)', () => {
  assert.equal(pollDecision({ status: 'running' }), 'continue');
  assert.equal(pollDecision({}), 'continue');
});
