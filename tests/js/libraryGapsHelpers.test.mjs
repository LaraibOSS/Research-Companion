/**
 * One notice for "what is missing from my library".
 *
 * There used to be two, on two surfaces, counting two different things: a top
 * banner for works cited but not held, and a chip inside Library for papers
 * that failed to download. A researcher does not experience those as two
 * problems. They experience one: the library is incomplete, and here is what
 * is missing.
 *
 * Fixtures are the shape `_build_paper_summary` actually serves.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { libraryGaps, gapsBannerModel } from
  '../../research_companion/lab/static/js/libraryGapsHelpers.js';

/** A paper as GET /api/papers serves it. */
const paper = (reason, extra = {}) => ({
  paper_id: `doi:10.1145/${Math.random().toString().slice(2, 8)}`,
  title: 'A Paper',
  status: reason ? 'failed' : 'done',
  acquisition: reason
    ? { obtained: false, reason, human_can_help: reason !== 'source_unavailable',
        attempts: [], source: null }
    : null,
  ...extra,
});

const coverage = (total, inLibrary) => ({ counts: { total, in_library: inLibrary } });

// ---------------------------------------------------------------------------
// counting
// ---------------------------------------------------------------------------

test('a blocked publisher counts as something your browser can fetch', () => {
  const g = libraryGaps([paper('blocked_by_host')], coverage(0, 0));
  assert.equal(g.fetchable, 1);
  assert.equal(g.unavailable, 0);
});

test('a login page where a PDF was promised is also fetchable by hand', () => {
  assert.equal(libraryGaps([paper('not_a_pdf')], coverage(0, 0)).fetchable, 1);
});

test('a paywalled paper counts as having no free copy', () => {
  const g = libraryGaps([paper('paywalled')], coverage(0, 0));
  assert.equal(g.unavailable, 1);
  assert.equal(g.fetchable, 0);
});

test('a paper no index knows about also has no free copy', () => {
  assert.equal(libraryGaps([paper('no_location_found')], coverage(0, 0)).unavailable, 1);
});

test('a transient failure is the machine\'s problem and is never counted', () => {
  // Asking a person to fix a timeout is noise, not information.
  const g = libraryGaps([paper('source_unavailable')], coverage(0, 0));
  assert.equal(g.fetchable, 0);
  assert.equal(g.unavailable, 0);
  assert.equal(g.total, 0);
});

test('works cited but not held come from the coverage payload', () => {
  const g = libraryGaps([], coverage(13, 8));
  assert.equal(g.uncited, 5);
});

test('coverage that holds everything contributes nothing', () => {
  assert.equal(libraryGaps([], coverage(9, 9)).uncited, 0);
});

test('the three counts sum to the total', () => {
  const g = libraryGaps(
    [paper('blocked_by_host'), paper('blocked_by_host'), paper('paywalled'),
     paper('source_unavailable'), paper(null)],
    coverage(10, 6));
  assert.deepEqual(
    { fetchable: g.fetchable, unavailable: g.unavailable, uncited: g.uncited },
    { fetchable: 2, unavailable: 1, uncited: 4 });
  assert.equal(g.total, 7);
});

test('a healthy paper contributes nothing', () => {
  assert.equal(libraryGaps([paper(null), paper(null)], coverage(4, 4)).total, 0);
});

test('cited-but-not-held is only counted against a real bibliography', () => {
  // The retired bannerText said so out loud: without a detected bibliography
  // the coverage denominator is related-work MENTIONS, not references. Counting
  // those as missing citations would invent a gap out of a weaker signal.
  const g = libraryGaps([], { source: 'related_work', counts: { total: 12, in_library: 4 } });
  assert.equal(g.uncited, 0);
});

test('a bibliography-derived coverage counts normally', () => {
  const g = libraryGaps([], { source: 'bibliography', counts: { total: 12, in_library: 4 } });
  assert.equal(g.uncited, 8);
});

test('coverage with no source stated is trusted', () => {
  // The existing payload omits `source` in some paths; absent is not a denial.
  assert.equal(libraryGaps([], { counts: { total: 5, in_library: 2 } }).uncited, 3);
});

// ---------------------------------------------------------------------------
// the banner model
// ---------------------------------------------------------------------------

test('nothing missing means no banner at all', () => {
  const m = gapsBannerModel(libraryGaps([paper(null)], coverage(3, 3)));
  assert.equal(m.show, false);
});

test('the headline counts every gap', () => {
  const m = gapsBannerModel(libraryGaps(
    [paper('blocked_by_host'), paper('paywalled')], coverage(8, 5)));
  assert.equal(m.show, true);
  assert.match(m.headline, /5 gaps in your library/);
});

test('one gap reads as one gap', () => {
  const m = gapsBannerModel(libraryGaps([paper('paywalled')], coverage(0, 0)));
  assert.match(m.headline, /^1 gap in your library/);
});

test('each line names what the reader can do about it', () => {
  const m = gapsBannerModel(libraryGaps(
    [paper('blocked_by_host'), paper('paywalled')], coverage(8, 5)));
  const lines = m.lines.map(l => `${l.count} ${l.text}`).join(' | ');
  assert.match(lines, /1 .*browser can fetch/i);
  assert.match(lines, /1 .*no free copy/i);
  assert.match(lines, /3 .*cited in your draft/i);
});

test('a line with a zero count is omitted, not shown as zero', () => {
  const m = gapsBannerModel(libraryGaps([paper('paywalled')], coverage(0, 0)));
  assert.equal(m.lines.length, 1);
  assert.equal(m.lines[0].count, 1);
});

test('the notice never reports a symptom where a cause is known', () => {
  // The whole reason this project rebuilt acquisition.
  const m = gapsBannerModel(libraryGaps(
    [paper('blocked_by_host'), paper('paywalled')], coverage(8, 5)));
  const all = m.headline + ' ' + m.lines.map(l => l.text).join(' ');
  assert.doesNotMatch(all, /no pdf on disk|on disk/i);
});

// ---------------------------------------------------------------------------
// the one-line summary the top bar actually shows
// ---------------------------------------------------------------------------

test('the summary states the total and the breakdown in one line', () => {
  const m = gapsBannerModel(libraryGaps(
    [paper('blocked_by_host'), paper('paywalled')], coverage(8, 5)));
  assert.match(m.summary, /^5 gaps in your library/);
  assert.match(m.summary, /1 your browser can fetch/);
  assert.match(m.summary, /1 with no free copy/);
  assert.match(m.summary, /3 cited but not held/);
});

test('the summary omits a zero group rather than saying zero', () => {
  const m = gapsBannerModel(libraryGaps([paper('paywalled')], coverage(0, 0)));
  assert.equal(m.summary, '1 gap in your library — 1 with no free copy');
});

test('no gaps means no summary', () => {
  assert.equal(gapsBannerModel(libraryGaps([], coverage(2, 2))).summary, '');
});

// ---------------------------------------------------------------------------
// robustness — this renders on every page load
// ---------------------------------------------------------------------------

test('never throws on malformed input', () => {
  for (const papers of [null, undefined, {}, [null, 3, 'x'], [{}]]) {
    for (const cov of [null, undefined, {}, { counts: null }, 'nope']) {
      assert.doesNotThrow(() => gapsBannerModel(libraryGaps(papers, cov)));
    }
  }
});

test('a paper whose acquisition block is junk is skipped, not counted', () => {
  const g = libraryGaps(
    [{ paper_id: 'x', status: 'failed', acquisition: 'not-a-dict' },
     { paper_id: 'y', status: 'failed', acquisition: { reason: 'unheard_of' } }],
    coverage(0, 0));
  assert.equal(g.total, 0);
});
