/**
 * timeline/layout.js — Pure geometry engine for the Timeline view.
 * DOM-free; testable with node --test.
 *
 * layoutTimeline(temporal, gapsOverview, opts) ->
 *   { width, yearTicks, lanes, gapLane, paperDensity, skipped }
 *
 * Coordinate system:
 *   x = labelWidth + (yearIndex * yearWidth) + yearWidth/2
 *   Year index is into the SORTED years array from temporal.years.
 *   Points whose paper has no year are excluded and counted in skipped.
 */

/**
 * @typedef {{ year: number, x: number }} YearTick
 * @typedef {{ x: number, paper_id: string, year: number }} LanePoint
 * @typedef {{ x1: number, x2: number, y: number }} Segment
 * @typedef {{ label: string, kind: string, y: number, points: LanePoint[], segments: Segment[] }} Lane
 * @typedef {{ x: number, gap_id: string, paper_id: string, status: string, draftAddresses: boolean, verified: boolean }} GapMarker
 * @typedef {{ y: number, markers: GapMarker[] }} GapLane
 * @typedef {{ x: number, year: number, count: number }} DensityPoint
 */

const DEFAULT_OPTS = {
  yearWidth:   140,
  laneHeight:  56,
  labelWidth:  180,
};

/**
 * Compute the full timeline layout from backend data.
 *
 * @param {object} temporal     — GET /api/temporal response
 * @param {object} gapsOverview — GET /api/gaps response (may be null/empty)
 * @param {object} [opts]       — { yearWidth, laneHeight, labelWidth }
 * @returns {{ width: number, yearTicks: YearTick[], lanes: Lane[], gapLane: GapLane, paperDensity: DensityPoint[], skipped: number }}
 */
export function layoutTimeline(temporal, gapsOverview, opts = {}) {
  const { yearWidth, laneHeight, labelWidth } = { ...DEFAULT_OPTS, ...opts };

  // Guard: empty/null temporal
  if (!temporal || !temporal.years || temporal.years.length === 0) {
    return {
      width: 0,
      yearTicks: [],
      lanes: [],
      gapLane: { y: 0, markers: [] },
      paperDensity: [],
      skipped: 0,
    };
  }

  // --------------------------------------------------------------------------
  // 1. Build sorted year array and x-coordinate lookup
  // --------------------------------------------------------------------------
  const sortedYears = [...temporal.years].sort((a, b) => a - b);
  const yearIndexMap = new Map(); // year -> index
  for (let i = 0; i < sortedYears.length; i++) {
    yearIndexMap.set(sortedYears[i], i);
  }

  /**
   * Compute x for a given year.
   * @param {number} year
   * @returns {number}
   */
  function xForYear(year) {
    const idx = yearIndexMap.get(year);
    if (idx === undefined) return null;
    return labelWidth + idx * yearWidth + yearWidth / 2;
  }

  const totalWidth = labelWidth + sortedYears.length * yearWidth;

  // --------------------------------------------------------------------------
  // 2. Year ticks
  // --------------------------------------------------------------------------
  const yearTicks = sortedYears.map(year => ({ year, x: xForYear(year) }));

  // --------------------------------------------------------------------------
  // 3. Lanes
  // --------------------------------------------------------------------------
  const tracks = temporal.tracks || [];
  let skipped = temporal.skipped_papers_without_year || 0;

  // Gap lane is the first row (y = laneHeight/2), then each track lane below.
  // gapLane.y = laneHeight/2
  // tracks start at row index 1 (y = laneHeight + laneHeight/2)
  const gapLaneY = laneHeight / 2;

  const lanes = [];
  for (let ti = 0; ti < tracks.length; ti++) {
    const track = tracks[ti];
    const y = laneHeight + ti * laneHeight + laneHeight / 2;

    const points = [];
    let localSkipped = 0;

    for (const appearance of (track.appearances || [])) {
      const x = xForYear(appearance.year);
      if (x === null) {
        // year missing from the years array — exclude + count
        localSkipped++;
        continue;
      }
      points.push({ x, paper_id: appearance.paper_id, year: appearance.year });
    }
    skipped += localSkipped;

    // Sort points by x (ascending) to make segment logic simple
    points.sort((a, b) => a.x - b.x);

    // Segments: connect CONSECUTIVE appearances (adjacent by sorted order, x1 < x2)
    const segments = [];
    for (let pi = 0; pi < points.length - 1; pi++) {
      const p1 = points[pi];
      const p2 = points[pi + 1];
      // x1 < x2 guaranteed by sort
      if (p1.x < p2.x) {
        segments.push({ x1: p1.x, x2: p2.x, y });
      }
    }

    lanes.push({
      label: track.label || '',
      kind:  track.kind  || 'concept',
      y,
      points,
      segments,
    });
  }

  // --------------------------------------------------------------------------
  // 4. Gap markers
  // --------------------------------------------------------------------------
  const draftAddressSet = new Set((gapsOverview && gapsOverview.draft_addresses) || []);
  const gapMarkers = [];

  if (gapsOverview && Array.isArray(gapsOverview.papers)) {
    for (const paperEntry of gapsOverview.papers) {
      const paperId = paperEntry.paper_id;
      const year    = paperEntry.year;

      if (year == null) continue;  // no year — can't place on timeline
      const x = xForYear(year);
      if (x === null) continue;    // year not in the temporal years array

      for (const gap of (paperEntry.gaps || [])) {
        const resolution = gap.resolution || { status: 'open' };
        gapMarkers.push({
          x,
          gap_id:         gap.gap_id,
          paper_id:       paperId,
          status:         resolution.status || 'open',
          draftAddresses: draftAddressSet.has(gap.gap_id),
          verified:       !!(gap.evidence && gap.evidence.verified),
        });
      }
    }
  }

  const gapLane = { y: gapLaneY, markers: gapMarkers };

  // --------------------------------------------------------------------------
  // 5. Paper density row
  // --------------------------------------------------------------------------
  const papersPerYear = temporal.papers_per_year || [];
  const paperDensity = papersPerYear
    .filter(entry => yearIndexMap.has(entry.year))
    .map(entry => ({
      x:     xForYear(entry.year),
      year:  entry.year,
      count: entry.count,
    }));

  return {
    width: totalWidth,
    yearTicks,
    lanes,
    gapLane,
    paperDensity,
    skipped,
  };
}
