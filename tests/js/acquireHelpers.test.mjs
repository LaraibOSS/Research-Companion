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

import { queueRowModel, browserOpenUrl, queueAfterMatches, nextMatchedIds, formatCountdown, statusBannerModel, createAcquirePoller } from
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

test('queueAfterMatches (with no matches) counts every queue member -- the chip/filter membership rule', () => {
  const list = [paper(F.blocked), paper(F.transient), paper(F.paywalled), paper(F.obtained)];
  assert.equal(queueAfterMatches(list, []).length, 2);
});

test('a paper with no acquisition block is not in the queue', () => {
  assert.equal(queueRowModel({ paper_id: 'x', title: 'y' }).show, false);
});

test('never throws on malformed input', () => {
  for (const bad of [null, undefined, {}, { acquisition: null }, { acquisition: 3 }]) {
    assert.doesNotThrow(() => queueRowModel(bad));
  }
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
// nextMatchedIds — bounding the optimistic "just matched, hide it" set
// ---------------------------------------------------------------------------

test('while still armed, a matched id that resolved (no longer queued) is dropped', () => {
  const next = nextMatchedIds(['doi:a', 'doi:b'], { armed: true }, (id) => id !== 'doi:a');
  assert.deepEqual([...next], ['doi:b']);
});

test('while still armed, a matched id that is STILL queued is kept -- grace period for the re-ingest', () => {
  const next = nextMatchedIds(['doi:a'], { armed: true }, () => true);
  assert.deepEqual([...next], ['doi:a']);
});

test('once the window is over, EVERY id is forgotten regardless of queue state -- this is the actual bound', () => {
  // isStillQueued says "still needs help" for every id (the worst case the
  // reviewer flagged: a re-ingest failure that re-arms the same paper for a
  // genuinely new reason, status staying 'failed' throughout) -- armed:false
  // must still clear the set unconditionally, so the paper is never hidden
  // past the current, user-visible arming window.
  const next = nextMatchedIds(['doi:a', 'doi:b'], { armed: false }, () => true);
  assert.equal(next.size, 0);
});

test('nextMatchedIds treats a missing/null model the same as armed:false', () => {
  assert.equal(nextMatchedIds(['doi:a'], null, () => true).size, 0);
  assert.equal(nextMatchedIds(['doi:a'], undefined, () => true).size, 0);
});

test('nextMatchedIds accepts a Set or an array for currentMatchedIds', () => {
  const fromSet = nextMatchedIds(new Set(['doi:a']), { armed: true }, () => true);
  assert.deepEqual([...fromSet], ['doi:a']);
});

test('nextMatchedIds never throws on malformed input, including a throwing isStillQueued', () => {
  assert.doesNotThrow(() => nextMatchedIds(null, { armed: true }, () => true));
  assert.equal(nextMatchedIds(null, { armed: true }, () => true).size, 0);
  assert.doesNotThrow(() => nextMatchedIds(['doi:a'], { armed: true }, undefined));
  assert.doesNotThrow(() => nextMatchedIds(['doi:a'], { armed: true }, () => { throw new Error('boom'); }));
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

// ---------------------------------------------------------------------------
// createAcquirePoller — the poll loop's lifecycle (Task 10D fix round 1).
//
// A fake `schedule`/`cancel` capture the timer calls instead of using a real
// clock, so a "next tick" is driven by the test invoking the captured
// callback itself. This is the DOM-free, injected-timer style the coordinator
// asked for -- no real setTimeout, no real fetch, anywhere in this section.
// ---------------------------------------------------------------------------

function fakeScheduler() {
  const scheduled = []; // [{ id, fn, ms }]
  let nextId = 1;
  const cancelled = new Set();
  return {
    scheduled,
    cancelled,
    schedule: (fn, ms) => {
      const id = nextId++;
      scheduled.push({ id, fn, ms });
      return id;
    },
    cancel: (id) => { cancelled.add(id); },
  };
}

test('a still-armed response schedules exactly one next tick', async () => {
  const sched = fakeScheduler();
  const fetchStatus = async () => ({ armed: true, seconds_left: 100,
    matched: [], unmatched: [], unreadable: [] });
  const poller = createAcquirePoller({
    fetchStatus, schedule: sched.schedule, cancel: sched.cancel, intervalMs: 5000,
  });

  await poller.start();

  assert.equal(poller.isPolling(), true);
  assert.equal(sched.scheduled.length, 1, 'exactly one next tick, not zero and not more');
  assert.equal(sched.scheduled[0].ms, 5000);
});

test('a response reporting armed:false stops the loop and schedules nothing further', async () => {
  const sched = fakeScheduler();
  const fetchStatus = async () => ({ armed: false, seconds_left: 0,
    matched: [], unmatched: [], unreadable: [] });
  let lastModel = null;
  const poller = createAcquirePoller({
    fetchStatus, schedule: sched.schedule, cancel: sched.cancel, intervalMs: 5000,
    onUpdate: (model) => { lastModel = model; },
  });

  await poller.start();

  assert.equal(poller.isPolling(), false);
  assert.equal(sched.scheduled.length, 0);
  assert.equal(lastModel.armed, false, 'onUpdate still fires for the final, disarming response');
});

test('stop() (disarm / unmount) stops the loop -- a straggler already-scheduled tick becomes a no-op', async () => {
  const sched = fakeScheduler();
  let fetchCalls = 0;
  const fetchStatus = async () => {
    fetchCalls += 1;
    return { armed: true, seconds_left: 100, matched: [], unmatched: [], unreadable: [] };
  };
  const poller = createAcquirePoller({
    fetchStatus, schedule: sched.schedule, cancel: sched.cancel, intervalMs: 5000,
  });

  await poller.start();
  assert.equal(fetchCalls, 1);
  assert.equal(sched.scheduled.length, 1);

  poller.stop(); // models both the Disarm button and unmount() in views/library.js
  assert.equal(poller.isPolling(), false);
  assert.deepEqual([...sched.cancelled], [sched.scheduled[0].id], 'the pending timer must actually be cancelled');

  // Even if the real timer fired anyway (best-effort clearTimeout), the
  // loop's own internal guard must still make it a no-op.
  await sched.scheduled[0].fn();
  assert.equal(fetchCalls, 1, 'no further fetch after stop()');
  assert.equal(sched.scheduled.length, 1, 'no further tick gets scheduled after stop()');
});

test('calling start() twice does not start a second, parallel loop', async () => {
  const sched = fakeScheduler();
  let fetchCalls = 0;
  const fetchStatus = async () => {
    fetchCalls += 1;
    return { armed: true, seconds_left: 100, matched: [], unmatched: [], unreadable: [] };
  };
  const poller = createAcquirePoller({
    fetchStatus, schedule: sched.schedule, cancel: sched.cancel, intervalMs: 5000,
  });

  await poller.start();
  await poller.start(); // e.g. a second "Open at publisher" click while already armed
  assert.equal(fetchCalls, 1, 'the second start() must not trigger a second immediate fetch');
});

test('repeated fetch failures hit the bounded give-up and stop, rather than retrying forever', async () => {
  const sched = fakeScheduler();
  const fetchStatus = async () => { throw new Error('network down'); };
  let giveUps = 0;
  const poller = createAcquirePoller({
    fetchStatus, schedule: sched.schedule, cancel: sched.cancel, intervalMs: 5000,
    onGiveUp: () => { giveUps += 1; },
  });

  await poller.start();

  let iterations = 0;
  const HARD_CAP = 200; // this test's own safety net, not the implementation's
  while (poller.isPolling() && sched.scheduled.length > 0 && iterations < HARD_CAP) {
    const next = sched.scheduled.shift();
    await next.fn();
    iterations += 1;
  }

  assert.equal(poller.isPolling(), false, 'polling must eventually stop on repeated failures');
  assert.equal(giveUps, 1, 'onGiveUp fires exactly once');
  assert.ok(iterations < HARD_CAP, 'must give up well before the test\'s own hard cap');
});

test('onUpdate is never called for a failed fetch -- only onGiveUp, and only once, at the end', async () => {
  const sched = fakeScheduler();
  const fetchStatus = async () => { throw new Error('network down'); };
  let updates = 0;
  let giveUps = 0;
  const poller = createAcquirePoller({
    fetchStatus, schedule: sched.schedule, cancel: sched.cancel, intervalMs: 5000,
    onUpdate: () => { updates += 1; },
    onGiveUp: () => { giveUps += 1; },
  });

  await poller.start();
  let iterations = 0;
  while (poller.isPolling() && sched.scheduled.length > 0 && iterations < 200) {
    const next = sched.scheduled.shift();
    await next.fn();
    iterations += 1;
  }

  assert.equal(updates, 0);
  assert.equal(giveUps, 1);
});

test('a transient failure followed by a recovery does not give up -- polling continues normally', async () => {
  const sched = fakeScheduler();
  let call = 0;
  const fetchStatus = async () => {
    call += 1;
    if (call === 1) throw new Error('blip');
    return { armed: true, seconds_left: 100, matched: [], unmatched: [], unreadable: [] };
  };
  let giveUps = 0;
  const poller = createAcquirePoller({
    fetchStatus, schedule: sched.schedule, cancel: sched.cancel, intervalMs: 5000,
    onGiveUp: () => { giveUps += 1; },
  });

  await poller.start();               // call 1: fails, schedules a retry
  assert.equal(poller.isPolling(), true);
  assert.equal(sched.scheduled.length, 1);
  await sched.scheduled.shift().fn(); // call 2: succeeds, still armed

  assert.equal(poller.isPolling(), true);
  assert.equal(giveUps, 0);
});


// --- which URL "Open at publisher" opens (spec 7.2) --------------------------

test('the DOI resolver is the fallback, never the pick', () => {
  // acquire() tries doi.org FIRST for a DOI paper, so attempts[0] is always
  // the resolver -- taking it sent every user to doi.org instead of to the
  // copy an index actually found.
  const url = browserOpenUrl([
    { url: 'https://doi.org/10.1145/3732941', host_class: 'publisher', outcome: '403' },
    { url: 'https://dl.acm.org/doi/pdf/10.1145/3732941', host_class: 'publisher', outcome: '403' },
  ]);
  assert.equal(url, 'https://dl.acm.org/doi/pdf/10.1145/3732941');
});

test('the highest-ranked host class wins', () => {
  const url = browserOpenUrl([
    { url: 'https://dl.acm.org/a.pdf', host_class: 'publisher', outcome: '403' },
    { url: 'https://zenodo.org/b.pdf', host_class: 'repository', outcome: '404' },
    { url: 'https://arxiv.org/pdf/2501.02600', host_class: 'native', outcome: '404' },
  ]);
  assert.equal(url, 'https://arxiv.org/pdf/2501.02600');
});

test('same-class candidates keep the order they were tried in', () => {
  const url = browserOpenUrl([
    { url: 'https://a.example.org/1.pdf', host_class: 'publisher' },
    { url: 'https://b.example.org/2.pdf', host_class: 'publisher' },
  ]);
  assert.equal(url, 'https://a.example.org/1.pdf');
});

test('the resolver is still offered when it is the only candidate', () => {
  const url = browserOpenUrl([
    { url: 'https://doi.org/10.1145/3732941', host_class: 'publisher', outcome: '403' },
  ]);
  assert.equal(url, 'https://doi.org/10.1145/3732941');
});

test('a non-http url is never handed to window.open', () => {
  // oaLinksLine has validated links against HTTP_URL_RE all along, for
  // exactly this reason; this URL is opened, not merely rendered.
  for (const bad of ['javascript:alert(1)', 'data:text/html,<script>', 'file:///etc/passwd', '', null, 42]) {
    assert.equal(browserOpenUrl([{ url: bad, host_class: 'publisher' }]), '');
  }
  assert.equal(
    queueRowModel({ acquisition: { human_can_help: true, attempts: [{ url: 'javascript:alert(1)' }] } }).canOpen,
    false);
});

test('an unknown host class sorts last rather than throwing', () => {
  const url = browserOpenUrl([
    { url: 'https://weird.example.org/1.pdf', host_class: 'martian' },
    { url: 'https://dl.acm.org/2.pdf', host_class: 'publisher' },
  ]);
  assert.equal(url, 'https://dl.acm.org/2.pdf');
});

test('no attempts at all means nothing to open', () => {
  for (const bad of [null, undefined, [], 'nope', [null, 3]]) {
    assert.equal(browserOpenUrl(bad), '');
  }
});
