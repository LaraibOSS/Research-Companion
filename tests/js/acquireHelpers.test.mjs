/**
 * The queue row display model.
 *
 * Fixtures are GENERATED from the Python model (scripts/generate_acquisition_fixtures.py).
 * Hand-written ones have encoded assumed shapes four times in this project.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { queueRowModel, needsYouCount } from
  '../../research_companion/lab/static/js/acquireHelpers.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const F = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures_acquisition.json'), 'utf8'));

const paper = (acq, extra = {}) => ({
  paper_id: 'doi:10.1145/3732941', title: 'A Paper', acquisition: acq, ...extra });

test('a blocked paper offers the publisher link', () => {
  const m = queueRowModel(paper(F.blocked));
  assert.equal(m.show, true);
  assert.equal(m.canOpen, true);
  assert.equal(m.openUrl, 'https://dl.acm.org/doi/pdf/10.1145/3732941');
});

test('a blocked paper never reads as a missing file', () => {
  const m = queueRowModel(paper(F.blocked));
  assert.doesNotMatch(m.headline + ' ' + m.detail, /no pdf|not found|missing/i);
});

test('a transient failure is not in the queue at all', () => {
  assert.equal(queueRowModel(paper(F.transient)).show, false);
});

test('an obtained paper is not in the queue', () => {
  assert.equal(queueRowModel(paper(F.obtained)).show, false);
});

test('membership comes from the backend flag, never re-derived here', () => {
  const lying = { ...F.blocked, human_can_help: false };
  assert.equal(queueRowModel(paper(lying)).show, false,
    'the JS must trust human_can_help');
});

test('a paper with no URL to open shows upload only', () => {
  assert.equal(queueRowModel(paper(F.not_attempted)).canOpen, false);
});

test('needsYouCount counts only queue members', () => {
  assert.equal(needsYouCount([paper(F.blocked), paper(F.transient),
                              paper(F.paywalled), paper(F.obtained)]), 2);
});

test('a paper with no acquisition block is not in the queue', () => {
  assert.equal(queueRowModel({ paper_id: 'x', title: 'y' }).show, false);
});

test('never throws on malformed input', () => {
  for (const bad of [null, undefined, {}, { acquisition: null }, { acquisition: 3 }]) {
    assert.doesNotThrow(() => queueRowModel(bad));
  }
  assert.equal(needsYouCount(null), 0);
});
