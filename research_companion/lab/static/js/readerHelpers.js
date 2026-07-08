/**
 * readerHelpers.js — Pure, DOM-free helpers for the Reader overlay.
 *
 * The Reader shows a paper's full text split into sections, optionally
 * highlighting a quote. All functions here are stateless and DOM-free so
 * they can be tested with `node --test`.
 */

/**
 * Clamp a value into [lo, hi] as an integer, defaulting to lo when not finite.
 * @param {*} v
 * @param {number} lo
 * @param {number} hi
 * @returns {number}
 */
function _clampInt(v, lo, hi) {
  const n = Number.isFinite(v) ? Math.trunc(v) : lo;
  return Math.max(lo, Math.min(n, hi));
}

/**
 * Build the reader view-model from a GET /api/papers/{id}/text payload.
 *
 * @param {object|null} payload
 * @returns {{ title: string, hasPdf: boolean, quoteRange: number[]|null,
 *             sections: Array<{id, title, level, text}> }}
 */
export function buildReaderModel(payload) {
  const p = payload || {};
  const title = p.title || 'Untitled';
  const hasPdf = !!p.has_pdf;
  const quoteRange = Array.isArray(p.quote_range) ? p.quote_range : null;
  const fullText = typeof p.full_text === 'string' ? p.full_text : '';
  const rawSections = Array.isArray(p.sections) ? p.sections : [];

  // No readable text at all — always render something.
  if (fullText.length === 0) {
    return {
      title,
      hasPdf,
      quoteRange,
      sections: [{ id: 's1', title: title || 'Full text', level: 1, text: '' }],
    };
  }

  const len = fullText.length;
  let sections = rawSections.map((s, i) => {
    let start = _clampInt(s.char_start, 0, len);
    let end = _clampInt(s.char_end, 0, len);
    if (start > end) end = start; // guard start <= end (degenerate -> empty)
    return {
      id: s.section_id != null ? s.section_id : `s${i + 1}`,
      title: s.title || '',
      level: s.level || 1,
      text: fullText.slice(start, end),
    };
  });

  // No sections declared — present the whole document as one section.
  if (sections.length === 0) {
    return {
      title,
      hasPdf,
      quoteRange,
      sections: [{ id: 's1', title: 'Full text', level: 1, text: fullText }],
    };
  }

  // Drop empty/whitespace-only sections, but never all of them.
  if (sections.length > 1) {
    const kept = sections.filter(s => s.text.trim().length > 0);
    sections = kept.length > 0 ? kept : [sections[0]];
  }

  return { title, hasPdf, quoteRange, sections };
}

/**
 * Whether a reader model has any non-whitespace body text. False for papers
 * whose extraction produced nothing (e.g. scanned PDFs) — the overlay then
 * shows an empty-state and points the reader at the original PDF.
 *
 * @param {{sections: Array<{text: string}>}} model
 * @returns {boolean}
 */
export function hasReadableText(model) {
  const secs = model && Array.isArray(model.sections) ? model.sections : [];
  return secs.some(s => typeof s.text === 'string' && s.text.trim().length > 0);
}

/**
 * Build the section navigation list with "§n Title" labels (1-based).
 *
 * @param {Array<{id, title, level}>} sections
 * @returns {Array<{id, label, level}>}
 */
export function sectionNav(sections) {
  const secs = Array.isArray(sections) ? sections : [];
  return secs.map((s, i) => ({
    id: s.id,
    label: `§${i + 1} ${s.title || ''}`.trimEnd(),
    level: s.level || 1,
  }));
}

/**
 * Resolve the id of the section to highlight, working on the RAW payload
 * sections (which carry char_start/char_end offsets).
 *   1. explicit targetId if it exists;
 *   2. else the section whose offset range contains quoteRange[0];
 *   3. else the first section (or null if none).
 *
 * @param {Array<{section_id, char_start, char_end}>} payloadSections
 * @param {string|null|undefined} targetId
 * @param {number[]|null} quoteRange
 * @returns {string|null}
 */
export function resolveActiveSection(payloadSections, targetId, quoteRange) {
  const secs = Array.isArray(payloadSections) ? payloadSections : [];
  if (targetId != null) {
    const hit = secs.find(s => s.section_id === targetId);
    if (hit) return hit.section_id;
  }
  if (Array.isArray(quoteRange) && quoteRange.length >= 2) {
    const q = quoteRange[0];
    const hit = secs.find(s => q >= s.char_start && q < s.char_end);
    if (hit) return hit.section_id;
  }
  return secs.length ? secs[0].section_id : null;
}

/**
 * Translate an absolute quote range into offsets relative to a section's own
 * sliced text, clamped to that text. Returns null when the quote is missing or
 * falls entirely outside the section.
 *
 * @param {number} sectionCharStart — absolute char offset the section starts at
 * @param {string} sectionText      — the section's sliced text
 * @param {number[]|null} quoteRange — absolute [start, end]
 * @returns {number[]|null} relative [start, end] or null
 */
export function quoteRangeWithinSection(sectionCharStart, sectionText, quoteRange) {
  if (!Array.isArray(quoteRange) || quoteRange.length < 2) return null;
  const len = typeof sectionText === 'string' ? sectionText.length : 0;
  const relStart = quoteRange[0] - sectionCharStart;
  const relEnd = quoteRange[1] - sectionCharStart;
  // Entirely before or after this section.
  if (relEnd <= 0 || relStart >= len) return null;
  const clampedStart = Math.max(0, Math.min(relStart, len));
  const clampedEnd = Math.max(clampedStart, Math.min(relEnd, len));
  if (clampedStart === clampedEnd) return null;
  return [clampedStart, clampedEnd];
}
