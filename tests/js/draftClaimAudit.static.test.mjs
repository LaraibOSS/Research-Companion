/**
 * tests/js/draftClaimAudit.static.test.mjs — source guards for claim audit in
 * the Draft view.
 *
 * The failure this area is prone to is silence: a shape mismatch between what
 * the audit stores and what the view looks up produces no badges and no error,
 * which is indistinguishable from "nothing to flag". These pin the wiring.
 *
 * Run: node --test tests/js/draftClaimAudit.static.test.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const JS = path.join(HERE, '..', '..', 'research_companion', 'lab', 'static', 'js');
const DRAFT = fs.readFileSync(path.join(JS, 'views', 'draft.js'), 'utf8');
const CSS = fs.readFileSync(
  path.join(HERE, '..', '..', 'research_companion', 'lab', 'static', 'css', 'lab.css'), 'utf8');

test('the Draft view audits the draft target, not the report', () => {
  assert.match(DRAFT, /runClaimAudit\('draft'\)/);
  assert.match(DRAFT, /getClaimAudit\('draft'\)/);
  assert.doesNotMatch(DRAFT, /runClaimAudit\('report'\)/);
});

test('it reuses the shared badge helpers rather than restating the rules', () => {
  // The rule that NOT_SUPPORTED is the only adverse outcome lives in one
  // place; a second copy here could drift and start accusing correct citations.
  assert.match(DRAFT, /from '\.\.\/claimAuditHelpers\.js'/);
  assert.match(DRAFT, /claimAuditBadge\(/);
  assert.match(DRAFT, /claimAuditSummaryLine\(/);
});

test('the advisory disclaimer is shown with the summary', () => {
  assert.match(DRAFT, /CLAIM_AUDIT_DISCLAIMER/);
});

test('lookup walks sections -> alignments -> evidence, the draft shape', () => {
  // audit_draft_alignment nests one level deeper than a per-paper alignment.
  // Looking evidence up directly on the section would silently find nothing.
  const fn = DRAFT.slice(DRAFT.indexOf('function _auditFor('),
                         DRAFT.indexOf('function _auditBadgeHtml('));
  assert.match(fn, /\.alignments\b/);
  assert.match(fn, /\.evidence\b/);
  assert.match(fn, /section_id/);
  assert.match(fn, /paper_id/);
});

test('a non-matching lookup yields no badge rather than a wrong one', () => {
  const fn = DRAFT.slice(DRAFT.indexOf('function _auditFor('),
                         DRAFT.indexOf('function _auditBadgeHtml('));
  assert.match(fn, /return null/);
});

test('the check is a separate opt-in action, not folded into Analyze', () => {
  // It costs a model call per cited passage; bundling it into Analyze would
  // spend money the user did not ask to spend.
  assert.match(DRAFT, /draft-audit-btn/);
  assert.match(DRAFT, /id="draft-analyze-btn"/);
  const toolbar = DRAFT.slice(DRAFT.indexOf('function _toolbarHtml('),
                              DRAFT.indexOf('function _wireToolbar('));
  assert.match(toolbar, /Check citations/);
});

test('the audit button is disabled until there is something to check', () => {
  const toolbar = DRAFT.slice(DRAFT.indexOf('function _toolbarHtml('),
                              DRAFT.indexOf('function _wireToolbar('));
  assert.match(toolbar, /hasAlignments/);
  assert.match(toolbar, /auditDisabled/);
});

test('an in-flight run does not clear the last stored result', () => {
  assert.match(DRAFT, /if \(!_auditing\) \{/);
});

test('the in-flight flag clears when the job finishes', () => {
  // Otherwise the button stays "Checking citations…" forever and the badges
  // never appear without a manual reload.
  assert.match(DRAFT, /kind === 'claim-audit'/);
  assert.match(DRAFT, /stillRunning/);
});

test('view state is reset on unmount so a stale audit cannot leak across drafts', () => {
  const unmount = DRAFT.slice(DRAFT.indexOf('export function unmount('),
                              DRAFT.indexOf('// ---', DRAFT.indexOf('export function unmount(')));
  assert.match(unmount, /_audit = null/);
  assert.match(unmount, /_auditing = false/);
});

test('the badge tones have styles in all three states', () => {
  for (const tone of ['ok', 'warn', 'muted']) {
    // `\.` inside a template literal is NOT an escape — it collapses to a bare
    // `.`, so this regex used to mean "any character" where a literal dot was
    // intended, matching far more than the selector it claims to pin. `\\.`
    // puts a real `\.` into the pattern.
    assert.match(CSS, new RegExp(`\\.draft-audit-badge\\.audit-${tone}`),
      `no style for audit-${tone}; the badge would render unstyled`);
  }
});
