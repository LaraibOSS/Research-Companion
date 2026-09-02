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

import { queueRowModel, needsYouCount, queueAfterMatches, formatCountdown, statusBannerModel } from
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

// ---------------------------------------------------------------------------
// queueAfterMatches — "a caught match removes a paper from the queue set"
// ---------------------------------------------------------------------------

test('a caught match removes a paper from the queue set', () => {
  const blocked = paper(F.blocked);
  const still = paper(F.paywalled, { paper_id: 'doi:still-needs-you' });
  const before = queueAfterMatches([blocked, still], []);
  assert.equal(before.length, 2, 'both are queue members before any match');

  const after = queueAfterMatches([blocked, still], [blocked.paper_id]);
  assert.equal(after.length, 1);
  assert.equal(after[0].paper_id, still.paper_id);
});

test('queueAfterMatches accepts a Set as well as an array of matched ids', () => {
  const blocked = paper(F.blocked);
  const asSet = queueAfterMatches([blocked], new Set([blocked.paper_id]));
  assert.equal(asSet.length, 0);
});

test('queueAfterMatches never widens membership -- a matched id that was never in the queue changes nothing', () => {
  const obtainedPaper = paper(F.obtained);
  const result = queueAfterMatches([obtainedPaper], [obtainedPaper.paper_id]);
  assert.equal(result.length, 0, 'an obtained paper was never a queue member to begin with');
});

test('queueAfterMatches never throws on malformed input', () => {
  assert.doesNotThrow(() => queueAfterMatches(null, null));
  assert.equal(queueAfterMatches(null, null).length, 0);
  assert.doesNotThrow(() => queueAfterMatches([paper(F.blocked)], undefined));
});

// ---------------------------------------------------------------------------
// formatCountdown
// ---------------------------------------------------------------------------

test('formatCountdown renders minutes:seconds, zero-padded', () => {
  assert.equal(formatCountdown(599), '9:59');
  assert.equal(formatCountdown(7), '0:07');
  assert.equal(formatCountdown(60), '1:00');
  assert.equal(formatCountdown(0), '0:00');
});

test('formatCountdown never goes negative or throws on bad input', () => {
  assert.equal(formatCountdown(-5), '0:00');
  assert.equal(formatCountdown(null), '0:00');
  assert.equal(formatCountdown(undefined), '0:00');
  assert.equal(formatCountdown('not a number'), '0:00');
});

// ---------------------------------------------------------------------------
// statusBannerModel — deciding what a GET /api/acquire/status poll shows
// ---------------------------------------------------------------------------

test('an armed status reports the countdown', () => {
  const m = statusBannerModel({ armed: true, seconds_left: 125, paper_ids: ['a'],
    matched: [], unmatched: [], unreadable: [] });
  assert.equal(m.armed, true);
  assert.equal(m.countdownText, '2:05');
  assert.deepEqual(m.messages, []);
});

test('a disarmed status is not armed regardless of what else it carries', () => {
  const m = statusBannerModel({ armed: false, seconds_left: 0, paper_ids: [],
    matched: [], unmatched: [], unreadable: [] });
  assert.equal(m.armed, false);
});

test('a matched file produces a success message and is reported as caught', () => {
  const m = statusBannerModel({
    armed: true, seconds_left: 300, paper_ids: ['doi:x'],
    matched: [{ paper_id: 'doi:x', filename: '3676641.3716025.pdf', job_id: 'job-9' }],
    unmatched: [], unreadable: [],
  });
  assert.deepEqual(m.matchedPaperIds, ['doi:x']);
  assert.equal(m.messages.length, 1);
  assert.equal(m.messages[0].type, 'success');
  assert.match(m.messages[0].text, /3676641\.3716025\.pdf/);
  assert.match(m.messages[0].text, /doi:x/);
});

test('an unmatched file is surfaced honestly, not dropped', () => {
  const m = statusBannerModel({
    armed: true, seconds_left: 300, paper_ids: ['doi:x'],
    matched: [], unmatched: ['bank-statement.pdf'], unreadable: [],
  });
  assert.equal(m.messages.length, 1);
  assert.equal(m.messages[0].type, 'warning');
  assert.match(m.messages[0].text, /bank-statement\.pdf/);
  assert.equal(m.matchedPaperIds.length, 0);
});

test('an unreadable file is surfaced with its error, not dropped', () => {
  const m = statusBannerModel({
    armed: true, seconds_left: 300, paper_ids: ['doi:x'],
    matched: [], unmatched: [], unreadable: [{ filename: 'locked.pdf', error: 'PermissionError' }],
  });
  assert.equal(m.messages.length, 1);
  assert.equal(m.messages[0].type, 'warning');
  assert.match(m.messages[0].text, /locked\.pdf/);
  assert.match(m.messages[0].text, /PermissionError/);
});

test('matched, unmatched and unreadable are all surfaced together in one poll', () => {
  const m = statusBannerModel({
    armed: true, seconds_left: 300, paper_ids: ['doi:x', 'doi:y'],
    matched: [{ paper_id: 'doi:x', filename: 'a.pdf', job_id: 'job-1' }],
    unmatched: ['b.pdf'],
    unreadable: [{ filename: 'c.pdf', error: 'OSError' }],
  });
  assert.equal(m.messages.length, 3);
  assert.deepEqual(m.matchedPaperIds, ['doi:x']);
});

test('statusBannerModel never throws on malformed input', () => {
  for (const bad of [null, undefined, {}, { matched: 'x' }, 3, 'oops']) {
    assert.doesNotThrow(() => statusBannerModel(bad));
  }
  assert.equal(statusBannerModel(null).armed, false);
  assert.deepEqual(statusBannerModel(null).messages, []);
});
