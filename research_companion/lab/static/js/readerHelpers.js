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
 * Build the section navigation list with "n. Title" labels (1-based).
 *
 * @param {Array<{id, title, level}>} sections
 * @returns {Array<{id, label, level}>}
 */
export function sectionNav(sections) {
  const secs = Array.isArray(sections) ? sections : [];
  return secs.map((s, i) => ({
    id: s.id,
    label: `${i + 1}. ${s.title || ''}`.trimEnd(),
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
 * Resolve the effective absolute quote range for the reader from an
 * rc:open-reader event detail, preferring an explicit [charStart, charEnd]
 * span (the Q&A citation "verify it yourself" path) over any quote_range the
 * text payload located.
 *
 * A detail range is used only when both offsets are finite numbers and
 * end > start; zero/degenerate/reversed ranges (e.g. old citations with
 * char_start == char_end == 0) are ignored and we fall back to the payload
 * range. Returns null when neither yields a usable range.
 *
 * @param {{charStart?: number, charEnd?: number}|null} detail
 * @param {number[]|null} payloadQuoteRange — from the /text payload (quote_range)
 * @returns {number[]|null} absolute [start, end] or null
 */
export function effectiveQuoteRange(detail, payloadQuoteRange) {
  const d = detail || {};
  const start = d.charStart;
  const end = d.charEnd;
  if (
    typeof start === 'number' && typeof end === 'number'
    && Number.isFinite(start) && Number.isFinite(end)
    && end > start
  ) {
    return [start, end];
  }
  return (Array.isArray(payloadQuoteRange) && payloadQuoteRange.length >= 2)
    ? payloadQuoteRange
    : null;
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

// ---------------------------------------------------------------------------
// sectionBlocks — segment raw PDF-extracted section text into typed blocks
// ---------------------------------------------------------------------------

const CAPTION_RE = /^(Figure|Fig\.|Table|Chart)\s*\d+[.:]/i;
const PAGE_NUM_RE = /^\d{1,4}$/;
const TERMINAL_RE = /[.!?:;]\s*$/;
const NUMBER_PREFIX_RE = /^\s*\d+(?:\.\d+)*\.?\s+/;
const DISPLAY_MAX_LEN = 60;
const DISPLAY_NUMBERING_RE = /\(\d+\)\s*$/;

function _endsTerminal(s) {
  return TERMINAL_RE.test(s);
}

function _startsLower(s) {
  return /^[a-z]/.test(s);
}

function _startsUpper(s) {
  return /^[A-Z]/.test(s);
}

function _isPageNumber(s) {
  return PAGE_NUM_RE.test(s);
}

function _isCaptionLine(s) {
  return CAPTION_RE.test(s);
}

function _isDisplayLine(s) {
  if (s.length === 0 || s.length > DISPLAY_MAX_LEN) return false;
  // Equation numbering like (3) overrides the period rule
  if (DISPLAY_NUMBERING_RE.test(s)) return true;
  // Must contain = to be considered display
  if (!s.includes('=')) return false;
  // Do not treat as display if it ends with sentence-terminal punctuation
  // (these are prose, not equations)
  if (_endsTerminal(s)) return false;
  return true;
}

function _isColumnarLine(s) {
  if (/	/.test(s)) return true;
  const spaceRuns = (s.match(/ {2,}/g) || []).length;
  // Require 3+ space runs, OR (2 runs AND 3+ numeric tokens)
  if (spaceRuns >= 3) return true;
  const tokens = s.split(/\s+/).filter(Boolean);
  if (tokens.length === 0) return false;
  const numericTokens = tokens.filter(t => /^-?\d+(\.\d+)?%?$/.test(t)).length;
  if (spaceRuns === 2 && numericTokens >= 3) return true;
  return numericTokens >= 3 && numericTokens / tokens.length >= 0.5;
}

// A fragment that would force a paragraph (or caption run) to stop merging,
// because it starts a differently-typed block of its own.
function _isBreakingFragment(s) {
  return _isCaptionLine(s) || _isDisplayLine(s);
}

function _stripNumberPrefix(s) {
  return s.replace(NUMBER_PREFIX_RE, '').trim();
}

function _normalizeForCompare(s) {
  return _stripNumberPrefix(s).toLowerCase().replace(/\s+/g, ' ').trim();
}

function _shouldMergeParagraph(prevTrimmed, nextTrimmed) {
  if (!_endsTerminal(prevTrimmed)) return true;
  if (_startsLower(nextTrimmed)) return true;
  return false;
}

// Extract maximal runs of non-newline characters ("fragments"), each one
// physical wrapped line of PDF-extracted text, with exact offsets into the
// raw text. Handles both doubled (`\n\n`) and single (`\n`) newline layouts
// uniformly, since both simply separate one fragment from the next.
function _extractFragments(text) {
  const fragments = [];
  const re = /[^\n]+/g;
  let m;
  while ((m = re.exec(text)) !== null) {
    const raw = m[0];
    const trimmed = raw.trim();
    if (trimmed.length === 0) continue;
    fragments.push({ trimmed, start: m.index, end: m.index + raw.length });
  }
  return fragments;
}

function _joinFragmentText(idxs, fragments, noiseSet) {
  let result = '';
  for (const idx of idxs) {
    if (noiseSet && noiseSet.has(idx)) continue;
    const frag = fragments[idx].trimmed;
    if (result === '') {
      result = frag;
      continue;
    }
    const hyphMatch = /[A-Za-z]-$/.test(result);
    if (hyphMatch && _startsLower(frag)) {
      result = result.slice(0, -1) + frag;
    } else {
      result = `${result} ${frag}`;
    }
  }
  return result.replace(/\s+/g, ' ').trim();
}

/**
 * Segment a section's raw (PDF-extracted) text into typed, offset-carrying
 * blocks so the Reader can render real paragraphs, tables and captions
 * instead of one giant pre-wrapped blob.
 *
 * Every block carries `[start, end)` offsets into `rawText` and the blocks
 * are guaranteed to tile the entire input with no gaps or overlaps (the
 * coverage property): concatenating `rawText.slice(b.start, b.end)` for
 * every block in order reconstructs `rawText` exactly. This is what lets the
 * quote-highlight machinery re-slice raw text safely (see
 * `blockIntersectsRange`) without ever losing or duplicating characters.
 *
 * Block kinds:
 *   - 'heading-echo' — the section title repeated as the body's first line
 *     (numbered-prefix- and case-insensitive); the renderer drops these.
 *   - 'caption'   — a Figure/Fig./Table/Chart caption line (or its wrapped
 *     continuation), kept as its own block.
 *   - 'display'   — a short standalone equation-like line.
 *   - 'table'     — a run of >=2 consecutive columnar-looking fragments,
 *     preserving internal whitespace/newlines verbatim.
 *   - 'para'      — the default: consecutive line-fragments joined into a
 *     real paragraph, with hyphenation repaired.
 *
 * @param {string} rawText
 * @param {string} [sectionTitle] — used to detect a heading-echo first line
 * @returns {Array<{kind: string, text: string, start: number, end: number}>}
 */
export function sectionBlocks(rawText, sectionTitle) {
  const text = typeof rawText === 'string' ? rawText : '';
  if (text.length === 0) return [];

  const fragments = _extractFragments(text);
  if (fragments.length === 0) {
    return [{ kind: 'para', text: '', start: 0, end: text.length }];
  }

  const titleNorm = sectionTitle ? _normalizeForCompare(sectionTitle) : null;
  const n = fragments.length;
  const groups = [];
  let i = 0;

  while (i < n) {
    const f = fragments[i];

    // heading-echo: only ever the very first block of the section.
    if (groups.length === 0 && titleNorm && _normalizeForCompare(f.trimmed) === titleNorm) {
      groups.push({ kind: 'heading-echo', idxs: [i] });
      i += 1;
      continue;
    }

    // Standalone page-number noise: absorb into whichever block is open
    // (or start a fresh, empty-text paragraph) rather than let it break
    // the surrounding paragraph or become visible clutter.
    if (_isPageNumber(f.trimmed)) {
      if (groups.length > 0) {
        const g = groups[groups.length - 1];
        g.idxs.push(i);
        g.noise = g.noise || new Set();
        g.noise.add(i);
      } else {
        groups.push({ kind: 'para', idxs: [i], noise: new Set([i]) });
      }
      i += 1;
      continue;
    }

    // Caption: absorb wrapped continuation fragments until terminal
    // punctuation, same merge rule as paragraphs, but tagged as 'caption'.
    if (_isCaptionLine(f.trimmed)) {
      const idxs = [i];
      let j = i;
      while (
        !_endsTerminal(fragments[j].trimmed)
        && j + 1 < n
        && !_isBreakingFragment(fragments[j + 1].trimmed)
        && !_isPageNumber(fragments[j + 1].trimmed)
      ) {
        j += 1;
        idxs.push(j);
      }
      groups.push({ kind: 'caption', idxs });
      i = j + 1;
      continue;
    }

    // Table: a run of >=2 consecutive columnar-looking fragments.
    if (_isColumnarLine(f.trimmed) && i + 1 < n && _isColumnarLine(fragments[i + 1].trimmed)) {
      const idxs = [i, i + 1];
      let j = i + 1;
      while (j + 1 < n && _isColumnarLine(fragments[j + 1].trimmed)) {
        j += 1;
        idxs.push(j);
      }
      groups.push({ kind: 'table', idxs });
      i = j + 1;
      continue;
    }

    // Display: short standalone equation-like line, never merged.
    if (_isDisplayLine(f.trimmed)) {
      groups.push({ kind: 'display', idxs: [i] });
      i += 1;
      continue;
    }

    // Paragraph: greedily merge subsequent fragments.
    const idxs = [i];
    let j = i;
    while (j + 1 < n) {
      const nxt = fragments[j + 1];
      if (_isPageNumber(nxt.trimmed)) break; // handled by its own branch next
      if (_isBreakingFragment(nxt.trimmed)) break;
      if (!_shouldMergeParagraph(fragments[j].trimmed, nxt.trimmed)) break;
      j += 1;
      idxs.push(j);
    }
    groups.push({ kind: 'para', idxs });
    i = j + 1;
  }

  const blocks = groups.map((g) => {
    const firstFrag = fragments[g.idxs[0]];
    const lastFrag = fragments[g.idxs[g.idxs.length - 1]];
    const start = firstFrag.start;
    const end = lastFrag.end;
    let blockText;
    if (g.kind === 'table') {
      blockText = text.slice(start, end); // preserve internal formatting verbatim
    } else if (g.kind === 'display' || g.kind === 'heading-echo') {
      blockText = firstFrag.trimmed;
    } else {
      blockText = _joinFragmentText(g.idxs, fragments, g.noise);
    }
    return { kind: g.kind, text: blockText, start, end };
  });

  // Coverage: extend block boundaries so they tile [0, text.length) exactly,
  // absorbing inter-fragment whitespace/newlines into the preceding block.
  blocks[0].start = 0;
  for (let k = 0; k < blocks.length - 1; k += 1) {
    blocks[k].end = blocks[k + 1].start;
  }
  blocks[blocks.length - 1].end = text.length;

  return blocks;
}

/**
 * Pure decision helper for quote-highlight safety: does a block's
 * `[start, end)` span intersect the (absolute-in-section) quote range?
 * Blocks that intersect must render in RAW mode (escaped + `<mark>`-sliced
 * straight from the raw text) so the exact quote span is never disturbed by
 * paragraph joining/hyphen-repair/whitespace collapsing.
 *
 * @param {{start: number, end: number}|null} block
 * @param {number[]|null} range — [start, end)
 * @returns {boolean}
 */
export function blockIntersectsRange(block, range) {
  if (!block || !Array.isArray(range) || range.length < 2) return false;
  return range[1] > block.start && range[0] < block.end;
}
