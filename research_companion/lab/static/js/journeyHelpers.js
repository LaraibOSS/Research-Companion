/**
 * journeyHelpers.js — Pure helpers for the Home/Journey view.
 * DOM-free: no document/window references. Node-testable.
 */

// ---------------------------------------------------------------------------
// mergeJourney
// ---------------------------------------------------------------------------

/**
 * Merge version history and events into a unified timeline, newest first.
 *
 * @param {Array} versions  — [{version, paper_id, added_at, n_sections, n_claims}]
 * @param {Array} events    — [{at, kind, data}]
 * @returns {Array<{at, icon:'version'|'event', title, sub}>}
 */
export function mergeJourney(versions, events) {
  const entries = [];

  for (const v of (versions || [])) {
    const nClaims = v.n_claims || 0;
    const nSections = v.n_sections || 0;
    entries.push({
      at: v.added_at,
      icon: 'version',
      title: `Draft v${v.version} added — ${nClaims} claim${nClaims === 1 ? '' : 's'}`,
      sub: `${nSections} section${nSections === 1 ? '' : 's'}`,
    });
  }

  for (const e of (events || [])) {
    entries.push({
      at: e.at,
      icon: 'event',
      title: _eventTitle(e.kind, e.data),
      sub: '',
    });
  }

  // Sort newest first
  entries.sort((a, b) => {
    if (a.at > b.at) return -1;
    if (a.at < b.at) return 1;
    return 0;
  });

  return entries;
}

function _eventTitle(kind, data) {
  switch (kind) {
    case 'suggestion_addressed': return 'Suggestion addressed';
    case 'suggestion_dismissed': return 'Suggestion dismissed';
    case 'paper_added': {
      const title = data && data.title ? ': ' + data.title : '';
      return `Paper added${title}`;
    }
    case 'ingest_completed': return 'Ingest completed';
    default: return kind ? kind.replace(/_/g, ' ') : 'Event';
  }
}

// ---------------------------------------------------------------------------
// sparklinePath
// ---------------------------------------------------------------------------

/**
 * Build an SVG path string from counts_over_time open counts.
 *
 * @param {Array}  counts_over_time — [{version, at, open, addressed, dismissed}]
 * @param {number} w — viewport width
 * @param {number} h — viewport height
 * @returns {string} SVG path "M...L..." or ''
 */
export function sparklinePath(counts_over_time, w, h) {
  if (!counts_over_time || counts_over_time.length === 0) return '';

  if (counts_over_time.length === 1) {
    const mid = h / 2;
    return `M 0 ${mid} L ${w} ${mid}`;
  }

  const opens = counts_over_time.map(c => c.open || 0);
  const maxOpen = Math.max(...opens);
  const minOpen = Math.min(...opens);
  const range = maxOpen - minOpen || 1;

  const n = opens.length;
  const padding = 4;

  const points = opens.map((val, i) => {
    const x = (i / (n - 1)) * w;
    const y = padding + ((maxOpen - val) / range) * (h - padding * 2);
    return [x, y];
  });

  const [startX, startY] = points[0];
  let d = `M ${startX.toFixed(1)} ${startY.toFixed(1)}`;
  for (let i = 1; i < points.length; i++) {
    d += ` L ${points[i][0].toFixed(1)} ${points[i][1].toFixed(1)}`;
  }
  return d;
}

// ---------------------------------------------------------------------------
// severityDonut
// ---------------------------------------------------------------------------

/**
 * Compute severity donut segments from suggestion counts.
 *
 * @param {{open:number, by_severity:{high?,medium?,low?}|null}} counts
 * @returns {Array<{color:string, frac:number}>}
 */
export function severityDonut(counts) {
  const open = (counts && counts.open) || 0;
  const bySev = counts && counts.by_severity;

  if (!open || !bySev) {
    return [{ color: 'var(--color-muted)', frac: 1 }];
  }

  const segments = [];
  const order = [
    { key: 'high',   color: 'var(--sev-high)'   },
    { key: 'medium', color: 'var(--sev-medium)'  },
    { key: 'low',    color: 'var(--sev-low)'     },
  ];

  for (const { key, color } of order) {
    const count = bySev[key] || 0;
    if (count > 0) {
      segments.push({ color, frac: count / open });
    }
  }

  if (segments.length === 0) {
    return [{ color: 'var(--color-muted)', frac: 1 }];
  }

  return segments;
}
