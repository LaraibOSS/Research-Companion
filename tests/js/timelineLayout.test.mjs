/**
 * timelineLayout.test.mjs — TDD tests for js/timeline/layout.js pure geometry.
 * Run from repo root: node --test tests/js/timelineLayout.test.mjs
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot  = path.resolve(__dirname, '..', '..');

const { layoutTimeline } = await import(
  pathToFileURL(
    path.join(repoRoot, 'research_companion', 'lab', 'static', 'js', 'timeline', 'layout.js')
  ).href
);

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeTemporal(overrides = {}) {
  return {
    years: [2020, 2021, 2022],
    papers_per_year: [
      { year: 2020, count: 2 },
      { year: 2021, count: 3 },
      { year: 2022, count: 1 },
    ],
    tracks: [
      {
        kind: 'concept',
        label: 'Attention',
        first_seen: 2020,
        introduced_by: 'p1',
        appearances: [
          { paper_id: 'p1', year: 2020 },
          { paper_id: 'p2', year: 2021 },
          { paper_id: 'p3', year: 2022 },
        ],
      },
      {
        kind: 'method',
        label: 'BERT',
        first_seen: 2021,
        introduced_by: 'p2',
        appearances: [
          { paper_id: 'p2', year: 2021 },
          { paper_id: 'p3', year: 2022 },
        ],
      },
    ],
    skipped_papers_without_year: 0,
    truncated_tracks: false,
    ...overrides,
  };
}

function makeGapsOverview(overrides = {}) {
  return {
    papers: [
      {
        paper_id: 'p1',
        title: 'Paper One',
        year: 2020,
        gaps: [
          {
            gap_id: 'gap_aaa',
            statement: 'We did not cover X.',
            kind: 'limitation',
            evidence: { quote: 'did not cover X', verified: true, match: 'did not cover X' },
            resolution: { status: 'open', resolved_by: null, rationale: 'not yet addressed' },
          },
          {
            gap_id: 'gap_bbb',
            statement: 'Future work needed on Y.',
            kind: 'future_work',
            evidence: { quote: 'Future work', verified: false, match: '' },
            resolution: { status: 'addressed', resolved_by: 'p3', rationale: 'covered by p3' },
          },
        ],
      },
      {
        paper_id: 'p2',
        title: 'Paper Two',
        year: 2021,
        gaps: [
          {
            gap_id: 'gap_ccc',
            statement: 'Dataset was limited.',
            kind: 'limitation',
            evidence: { quote: 'Dataset was limited', verified: true, match: 'Dataset was limited' },
            resolution: { status: 'partially', resolved_by: null, rationale: 'partial coverage' },
          },
        ],
      },
    ],
    draft_addresses: ['gap_bbb'],
    stale: false,
    ...overrides,
  };
}

const DEFAULT_OPTS = { yearWidth: 140, laneHeight: 56, labelWidth: 180 };

// Helper: expected x for year index
function expectedX(idx, opts = DEFAULT_OPTS) {
  return opts.labelWidth + idx * opts.yearWidth + opts.yearWidth / 2;
}

// ---------------------------------------------------------------------------
// Tests: x monotonic + spacing
// ---------------------------------------------------------------------------

test('yearTicks have monotonically increasing x values', () => {
  const { yearTicks } = layoutTimeline(makeTemporal(), null, DEFAULT_OPTS);
  assert.equal(yearTicks.length, 3);
  for (let i = 1; i < yearTicks.length; i++) {
    assert.ok(
      yearTicks[i].x > yearTicks[i - 1].x,
      `x[${i}] should be > x[${i - 1}]: ${yearTicks[i].x} vs ${yearTicks[i - 1].x}`
    );
  }
});

test('yearTick x spacing equals yearWidth', () => {
  const opts = { yearWidth: 140, laneHeight: 56, labelWidth: 180 };
  const { yearTicks } = layoutTimeline(makeTemporal(), null, opts);
  for (let i = 1; i < yearTicks.length; i++) {
    assert.equal(yearTicks[i].x - yearTicks[i - 1].x, opts.yearWidth);
  }
});

test('yearTick x formula: labelWidth + yearIndex*yearWidth + yearWidth/2', () => {
  const opts = { yearWidth: 140, laneHeight: 56, labelWidth: 180 };
  const { yearTicks } = layoutTimeline(makeTemporal(), null, opts);
  assert.equal(yearTicks[0].x, expectedX(0, opts)); // 2020 -> index 0
  assert.equal(yearTicks[1].x, expectedX(1, opts)); // 2021 -> index 1
  assert.equal(yearTicks[2].x, expectedX(2, opts)); // 2022 -> index 2
});

test('lane points have monotonically increasing x (sorted)', () => {
  const { lanes } = layoutTimeline(makeTemporal(), null, DEFAULT_OPTS);
  for (const lane of lanes) {
    for (let i = 1; i < lane.points.length; i++) {
      assert.ok(
        lane.points[i].x >= lane.points[i - 1].x,
        `lane "${lane.label}" point x not sorted at index ${i}`
      );
    }
  }
});

// ---------------------------------------------------------------------------
// Tests: segments only between consecutive appearances
// ---------------------------------------------------------------------------

test('segments connect only consecutive (adjacent) appearances, not all pairs', () => {
  // Track with 3 appearances: should produce 2 segments, not 3
  const { lanes } = layoutTimeline(makeTemporal(), null, DEFAULT_OPTS);
  const conceptLane = lanes.find(l => l.kind === 'concept');
  assert.ok(conceptLane, 'concept lane should exist');
  assert.equal(conceptLane.points.length, 3);
  assert.equal(conceptLane.segments.length, 2, 'should have 2 segments for 3 consecutive points');
});

test('segment x1 is always < x2', () => {
  const { lanes } = layoutTimeline(makeTemporal(), null, DEFAULT_OPTS);
  for (const lane of lanes) {
    for (const seg of lane.segments) {
      assert.ok(seg.x1 < seg.x2, `segment in lane "${lane.label}" has x1 >= x2`);
    }
  }
});

test('segments connect same-y (lane y)', () => {
  const { lanes } = layoutTimeline(makeTemporal(), null, DEFAULT_OPTS);
  for (const lane of lanes) {
    for (const seg of lane.segments) {
      assert.equal(seg.y, lane.y, `segment y should match lane y in "${lane.label}"`);
    }
  }
});

test('track with 1 appearance has 0 segments', () => {
  const temporal = makeTemporal({
    tracks: [
      {
        kind: 'concept', label: 'Solo', first_seen: 2020, introduced_by: 'p1',
        appearances: [{ paper_id: 'p1', year: 2020 }],
      },
    ],
  });
  const { lanes } = layoutTimeline(temporal, null, DEFAULT_OPTS);
  assert.equal(lanes[0].segments.length, 0, 'single-point lane should have no segments');
});

// ---------------------------------------------------------------------------
// Tests: gap markers at stating paper year with status/draft flags
// ---------------------------------------------------------------------------

test('gap markers placed at stating paper year x', () => {
  const { gapLane } = layoutTimeline(makeTemporal(), makeGapsOverview(), DEFAULT_OPTS);
  // gap_aaa and gap_bbb come from paper p1, year 2020 (index 0)
  const markersAtP1 = gapLane.markers.filter(m => m.paper_id === 'p1');
  assert.equal(markersAtP1.length, 2, 'two gaps from p1');
  for (const m of markersAtP1) {
    assert.equal(m.x, expectedX(0, DEFAULT_OPTS), 'marker x should be 2020 x');
  }
});

test('gap marker status reflects resolution.status', () => {
  const { gapLane } = layoutTimeline(makeTemporal(), makeGapsOverview(), DEFAULT_OPTS);
  const openMarker = gapLane.markers.find(m => m.gap_id === 'gap_aaa');
  assert.ok(openMarker, 'gap_aaa marker should exist');
  assert.equal(openMarker.status, 'open');

  const addressedMarker = gapLane.markers.find(m => m.gap_id === 'gap_bbb');
  assert.ok(addressedMarker, 'gap_bbb marker should exist');
  assert.equal(addressedMarker.status, 'addressed');

  const partialMarker = gapLane.markers.find(m => m.gap_id === 'gap_ccc');
  assert.ok(partialMarker, 'gap_ccc marker should exist');
  assert.equal(partialMarker.status, 'partially');
});

test('draftAddresses flag true only for gap in draft_addresses list', () => {
  const { gapLane } = layoutTimeline(makeTemporal(), makeGapsOverview(), DEFAULT_OPTS);
  const markerBbb = gapLane.markers.find(m => m.gap_id === 'gap_bbb');
  assert.ok(markerBbb.draftAddresses, 'gap_bbb should be flagged as draft-addressed');

  const markerAaa = gapLane.markers.find(m => m.gap_id === 'gap_aaa');
  assert.ok(!markerAaa.draftAddresses, 'gap_aaa should NOT be draft-addressed');
});

test('verified flag carried from gap evidence', () => {
  const { gapLane } = layoutTimeline(makeTemporal(), makeGapsOverview(), DEFAULT_OPTS);
  const verifiedMarker = gapLane.markers.find(m => m.gap_id === 'gap_aaa');
  assert.ok(verifiedMarker.verified, 'gap_aaa evidence.verified = true');

  const unverifiedMarker = gapLane.markers.find(m => m.gap_id === 'gap_bbb');
  assert.ok(!unverifiedMarker.verified, 'gap_bbb evidence.verified = false');
});

test('gap from paper with year not in temporal years array is excluded', () => {
  // p1 year = 2020, but we remove 2020 from temporal.years
  const temporal = makeTemporal({ years: [2021, 2022] });
  const gaps = makeGapsOverview(); // p1 has year 2020
  const { gapLane } = layoutTimeline(temporal, gaps, DEFAULT_OPTS);
  const p1Markers = gapLane.markers.filter(m => m.paper_id === 'p1');
  assert.equal(p1Markers.length, 0, 'p1 year 2020 not in temporal.years — should be excluded');
});

// ---------------------------------------------------------------------------
// Tests: missing-year exclusion + skipped count
// ---------------------------------------------------------------------------

test('appearances with year missing from temporal.years are excluded from points', () => {
  const temporal = makeTemporal({
    years: [2020, 2022],  // 2021 deliberately missing
    tracks: [
      {
        kind: 'concept', label: 'Track', first_seen: 2020, introduced_by: 'p1',
        appearances: [
          { paper_id: 'p1', year: 2020 },
          { paper_id: 'p2', year: 2021 },  // missing year
          { paper_id: 'p3', year: 2022 },
        ],
      },
    ],
  });
  const { lanes, skipped } = layoutTimeline(temporal, null, DEFAULT_OPTS);
  assert.equal(lanes[0].points.length, 2, 'p2 (year 2021 missing) should be excluded');
  assert.ok(skipped >= 1, 'skipped should count the missing-year appearance');
});

test('skipped_papers_without_year from temporal is included in skipped count', () => {
  const temporal = makeTemporal({ skipped_papers_without_year: 5 });
  const { skipped } = layoutTimeline(temporal, null, DEFAULT_OPTS);
  assert.ok(skipped >= 5, 'skipped should include temporal.skipped_papers_without_year');
});

// ---------------------------------------------------------------------------
// Tests: empty input never throws
// ---------------------------------------------------------------------------

test('empty temporal returns zero-width layout without throwing', () => {
  const result = layoutTimeline({}, null, DEFAULT_OPTS);
  assert.equal(result.width, 0);
  assert.deepEqual(result.lanes, []);
  assert.equal(result.yearTicks.length, 0);
  assert.equal(result.gapLane.markers.length, 0);
});

test('null temporal returns zero-width layout without throwing', () => {
  const result = layoutTimeline(null, null, DEFAULT_OPTS);
  assert.equal(result.width, 0);
});

test('temporal with empty years array returns zero-width layout', () => {
  const result = layoutTimeline({ years: [] }, null, DEFAULT_OPTS);
  assert.equal(result.width, 0);
  assert.equal(result.yearTicks.length, 0);
});

test('null gapsOverview produces empty gapLane markers without throwing', () => {
  const result = layoutTimeline(makeTemporal(), null, DEFAULT_OPTS);
  assert.equal(result.gapLane.markers.length, 0);
});

// ---------------------------------------------------------------------------
// Tests: density row math
// ---------------------------------------------------------------------------

test('paperDensity entries match temporal.papers_per_year', () => {
  const { paperDensity } = layoutTimeline(makeTemporal(), null, DEFAULT_OPTS);
  assert.equal(paperDensity.length, 3);
  const d2020 = paperDensity.find(d => d.year === 2020);
  assert.ok(d2020, 'density entry for 2020 must exist');
  assert.equal(d2020.count, 2);
  assert.equal(d2020.x, expectedX(0, DEFAULT_OPTS));
});

test('paperDensity entries only include years present in temporal.years', () => {
  // papers_per_year has a year (2019) not in temporal.years
  const temporal = makeTemporal({
    years: [2020, 2021],
    papers_per_year: [
      { year: 2019, count: 99 },  // not in years array
      { year: 2020, count: 2 },
      { year: 2021, count: 3 },
    ],
  });
  const { paperDensity } = layoutTimeline(temporal, null, DEFAULT_OPTS);
  const d2019 = paperDensity.find(d => d.year === 2019);
  assert.equal(d2019, undefined, 'year 2019 not in temporal.years — should be filtered out');
  assert.equal(paperDensity.length, 2);
});

test('total width = labelWidth + years.length * yearWidth', () => {
  const opts = { yearWidth: 140, laneHeight: 56, labelWidth: 180 };
  const temporal = makeTemporal({ years: [2020, 2021, 2022] });
  const { width } = layoutTimeline(temporal, null, opts);
  assert.equal(width, opts.labelWidth + 3 * opts.yearWidth);
});

// ---------------------------------------------------------------------------
// Tests: relX — view-side coordinate offset (canvas-inner uses full-width coords
// minus labelWidth; last year dot must fit inside innerW)
// ---------------------------------------------------------------------------

test('relX: 3 years labelWidth=180 yearWidth=140 — last year rendered x fits inside innerW', () => {
  // Hand-math:
  //   totalW = 180 + 3*140 = 600
  //   innerW = totalW - labelWidth = 600 - 180 = 420
  //   last year (2022) x = 180 + 2*140 + 70 = 180 + 280 + 70 = 530  (full-width)
  //   relX(530) = 530 - 180 = 350
  //   dot half-width = 5px (10px diameter)
  //   rendered right edge = 350 + 5 = 355 <= innerW (420) — fits
  const opts = { yearWidth: 140, laneHeight: 56, labelWidth: 180 };
  const temporal = makeTemporal({ years: [2020, 2021, 2022] });
  const { width, yearTicks } = layoutTimeline(temporal, null, opts);

  const innerW = width - opts.labelWidth;
  assert.equal(innerW, 420, 'innerW should be 420');

  const lastTick = yearTicks[yearTicks.length - 1];
  assert.equal(lastTick.year, 2022, 'last tick year should be 2022');
  assert.equal(lastTick.x, 530, 'last tick full-width x should be 530');

  // Simulate the view's relX helper
  const renderedX = lastTick.x - opts.labelWidth;
  assert.equal(renderedX, 350, 'renderedX (relX) for 2022 should be 350');

  // Rendered right edge (dot half-width = 5) must not overflow innerW
  const dotHalfWidth = 5;
  assert.ok(
    renderedX + dotHalfWidth <= innerW,
    `last dot right edge (${renderedX + dotHalfWidth}) must fit within innerW (${innerW})`
  );
});
