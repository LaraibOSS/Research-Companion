/**
 * claimAuditHelpers.test.mjs — display model for claim-audit outcomes.
 * The rendering must never turn "could not check" into either an accusation
 * or a clean tick.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, '..', '..');
const { claimAuditBadge, claimAuditSummaryLine, CLAIM_AUDIT_DISCLAIMER } =
  await import(pathToFileURL(path.join(
    repoRoot, 'research_companion', 'lab', 'static', 'js', 'claimAuditHelpers.js')).href);

test('only not_supported renders as adverse', () => {
  assert.equal(claimAuditBadge({ outcome: 'not_supported', is_adverse: true }).isAdverse, true);
  for (const outcome of ['supported', 'unverifiable', 'anchorless', 'not_checked']) {
    const b = claimAuditBadge({ outcome, is_adverse: false });
    assert.equal(b.isAdverse, false, outcome);
  }
});

test('inconclusive outcomes are muted and say they are not a finding', () => {
  for (const outcome of ['unverifiable', 'anchorless', 'not_checked']) {
    const b = claimAuditBadge({ outcome, is_adverse: false });
    assert.equal(b.tone, 'muted', outcome);
    assert.doesNotMatch(b.label, /supported/i, outcome);
  }
  assert.match(claimAuditBadge({ outcome: 'unverifiable' }).title, /NOT a finding/i);
});

test('supported and not_supported get distinct tones', () => {
  assert.equal(claimAuditBadge({ outcome: 'supported' }).tone, 'ok');
  assert.equal(claimAuditBadge({ outcome: 'not_supported' }).tone, 'warn');
});

test('adverse wording names it an AI judgement, not a fact', () => {
  assert.match(claimAuditBadge({ outcome: 'not_supported' }).title, /AI judgement/i);
  assert.match(CLAIM_AUDIT_DISCLAIMER, /advisory/i);
  assert.match(CLAIM_AUDIT_DISCLAIMER, /can be wrong/i);
});

test('nothing to show when there is no audit', () => {
  assert.equal(claimAuditBadge(null).show, false);
  assert.equal(claimAuditBadge(undefined).show, false);
  assert.equal(claimAuditBadge({}).show, false);
  assert.doesNotThrow(() => claimAuditBadge('junk'));
});

test('summary reports what was settled without conflating it with what was not', () => {
  const line = claimAuditSummaryLine({ total: 10, checked: 6, adverse: 2, inconclusive: 4 });
  assert.match(line, /6 of 10 citations checked/);
  assert.match(line, /2 flagged as unsupported/);
  assert.match(line, /4 could not be checked/);
});

test('a clean run does not claim more than it checked', () => {
  const line = claimAuditSummaryLine({ total: 3, checked: 3, adverse: 0, inconclusive: 0 });
  assert.match(line, /3 of 3/);
  assert.match(line, /none flagged as unsupported/);
  assert.doesNotMatch(line, /could not be checked/);
});

test('summary is empty for nothing, and never throws', () => {
  assert.equal(claimAuditSummaryLine(null), '');
  assert.equal(claimAuditSummaryLine({ total: 0 }), '');
  assert.doesNotThrow(() => claimAuditSummaryLine('junk'));
});
