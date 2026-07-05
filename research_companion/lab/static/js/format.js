/**
 * format.js — Pure, DOM-free formatting helpers.
 *
 * All functions are stateless and have no DOM dependencies
 * so they can be tested with node --test.
 */

// Strength palette (canonical from brief)
const STRENGTH_COLORS = {
  strong:     '#3fb950',
  moderate:   '#d29922',
  weak:       '#f0883e',
  failed:     '#f85149',
  unscored:   '#8b949e',
  processing: '#58a6ff',
};

const MUTED_COLOR = '#8b949e';

/**
 * Return the canonical hex color for a strength band.
 * Falls back to muted (#8b949e) for unknown/null/undefined.
 *
 * @param {string|null|undefined} band
 * @returns {string}
 */
export function strengthColor(band) {
  if (!band) return MUTED_COLOR;
  return STRENGTH_COLORS[band] || MUTED_COLOR;
}

// Stance icon mapping (from brief)
const STANCE_ICONS = {
  strengthens:  '▲',
  challenges:   '⚡',
  alternative:  '◆',
};

/**
 * Return the stance icon character for a relation string.
 * Returns '' for unknown/null.
 *
 * @param {string|null|undefined} relation
 * @returns {string}
 */
export function stanceIcon(relation) {
  if (!relation) return '';
  return STANCE_ICONS[relation] || '';
}

/**
 * Format an authors array + year into a single display string.
 * Truncates lists longer than 3 with "et al."
 *
 * @param {string[]} authors
 * @param {number|string|null} year
 * @returns {string}
 */
export function authorsLine(authors, year) {
  if (!authors || authors.length === 0) {
    return year ? String(year) : '';
  }
  let authorStr;
  if (authors.length > 3) {
    authorStr = authors[0] + ' et al.';
  } else {
    authorStr = authors.join(', ');
  }
  return year ? `${authorStr} · ${year}` : authorStr;
}

/**
 * Escape HTML special characters to prevent XSS.
 * Safe for use in innerHTML.
 *
 * @param {string} s
 * @returns {string}
 */
export function escapeHtml(s) {
  if (typeof s !== 'string') s = String(s == null ? '' : s);
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/**
 * Format an ISO date string as a relative time ("2 hours ago", "just now").
 * Falls back to empty string on invalid input.
 *
 * @param {string|null|undefined} iso
 * @returns {string}
 */
export function timeAgo(iso) {
  if (!iso) return '';
  let date;
  try {
    date = new Date(iso);
    if (isNaN(date.getTime())) return '';
  } catch {
    return '';
  }

  const nowMs = Date.now();
  const diffMs = nowMs - date.getTime();
  const diffSec = Math.floor(diffMs / 1000);

  if (diffSec < 10) return 'just now';
  if (diffSec < 60) return `${diffSec} seconds ago`;

  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin} minute${diffMin !== 1 ? 's' : ''} ago`;

  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr} hour${diffHr !== 1 ? 's' : ''} ago`;

  const diffDay = Math.floor(diffHr / 24);
  if (diffDay < 30) return `${diffDay} day${diffDay !== 1 ? 's' : ''} ago`;

  const diffMo = Math.floor(diffDay / 30);
  if (diffMo < 12) return `${diffMo} month${diffMo !== 1 ? 's' : ''} ago`;

  const diffYr = Math.floor(diffMo / 12);
  return `${diffYr} year${diffYr !== 1 ? 's' : ''} ago`;
}
