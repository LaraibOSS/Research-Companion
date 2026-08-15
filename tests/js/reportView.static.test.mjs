/**
 * tests/js/reportView.static.test.mjs — source-level guards for the Report tab.
 *
 * The Report tab has one cheap, reversible action (write a plan) and one that
 * spends a model call per question (answer it). Which of the two looks like
 * the default is a product decision, and it is expressed in a single CSS class
 * that a later edit can flip without any test noticing. These pin it.
 *
 * Run: node --test tests/js/reportView.static.test.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const JS = path.join(HERE, '..', '..', 'research_companion', 'lab', 'static', 'js');
const REPORT = fs.readFileSync(path.join(JS, 'views', 'report.js'), 'utf8');
const HELP = fs.readFileSync(path.join(JS, 'helpContent.js'), 'utf8');

/** The class expression on the button carrying `marker`. */
function classesFor(marker) {
  const m = REPORT.match(new RegExp(`class="([^"]*${marker}[^"]*)"`));
  assert.ok(m, `no button found carrying ${marker}`);
  return m[1];
}

/** Source with JS string-concatenation joins collapsed, so a match is not
 *  defeated by where the author happened to wrap the line. */
function joined(src) {
  return src.replace(/'\s*\+\s*'/g, '');
}

test('Generate plan is the primary action', () => {
  // Planning is one call and free to edit; it must be the path that looks
  // default, or users take the expensive route by following the button styling.
  assert.match(classesFor('report-generate-plan-btn'), /\bbtn-primary\b/);
});

test('Generate report is secondary, not primary', () => {
  const cls = classesFor('report-generate-btn');
  assert.match(cls, /\bbtn-secondary\b/);
  assert.doesNotMatch(cls, /\bbtn-primary\b/);
});

test('never two unconditional primaries — nothing would read as the default', () => {
  // The plan editor's Run is primary, so the controls' Generate plan must be
  // conditional. An unconditional second primary means both compete on screen.
  const primaries = REPORT.match(/class="btn btn-primary [a-z-]+"/g) || [];
  assert.equal(primaries.length, 1, `found ${primaries.length}: ${primaries.join(', ')}`);
});

test('the costed pass is priced before the click, not after', () => {
  assert.match(REPORT, /reportCostLine\(/);
  assert.match(REPORT, /report-cost-line/);
});

test('the empty state is derived, not a hardcoded sentence', () => {
  assert.match(REPORT, /reportEmptyState\(/);
  // the old copy said neither what it costs nor what to do with no papers
  assert.doesNotMatch(REPORT, /Enter a topic and generate a report from your library/);
});

test('the empty state re-renders when the library changes underneath it', () => {
  // a workspace switch re-snapshots papers while this view is mounted; without
  // this subscription the advice contradicts what the Library tab shows
  assert.match(REPORT, /store\.subscribe\(\['papers'\]/);
});

test('the plan status is derived, not the raw internal status word', () => {
  assert.match(REPORT, /reportPlanStatus\(/);
  assert.doesNotMatch(REPORT, /\(\$\{planModel\.status\}\)/);
});

test('the Report help entry sets the cost expectation', () => {
  const entry = joined(HELP.slice(HELP.indexOf('report: {'), HELP.indexOf('ask: {')));
  assert.match(entry, /plan first/i);
  assert.match(entry, /call per question/);
});
