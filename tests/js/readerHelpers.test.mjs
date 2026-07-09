/**
 * readerHelpers.test.mjs — tests for the pure Reader overlay helpers.
 *   buildReaderModel, sectionNav, resolveActiveSection, quoteRangeWithinSection
 *
 * Run from repo root:
 *   node --test tests/js/readerHelpers.test.mjs
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, '..', '..');

const {
  buildReaderModel,
  sectionNav,
  resolveActiveSection,
  quoteRangeWithinSection,
  hasReadableText,
  effectiveQuoteRange,
} = await import(
  pathToFileURL(path.join(repoRoot, 'research_companion', 'lab', 'static', 'js', 'readerHelpers.js')).href
);

// -----------------------------------------------------------------------
// buildReaderModel
// -----------------------------------------------------------------------

test('buildReaderModel: multi-section slice matches offsets', () => {
  const full = 'ABSTRACTbody-intro-textmethods-here';
  //            0       8              23
  const payload = {
    title: 'Paper A',
    has_pdf: true,
    full_text: full,
    quote_range: null,
    sections: [
      { section_id: 'a', title: 'Abstract', level: 1, char_start: 0,  char_end: 8 },
      { section_id: 'b', title: 'Intro',    level: 1, char_start: 8,  char_end: 23 },
      { section_id: 'c', title: 'Methods',  level: 2, char_start: 23, char_end: full.length },
    ],
  };
  const model = buildReaderModel(payload);
  assert.equal(model.title, 'Paper A');
  assert.equal(model.hasPdf, true);
  assert.equal(model.quoteRange, null);
  assert.equal(model.sections.length, 3);
  assert.deepEqual(
    model.sections.map(s => s.text),
    ['ABSTRACT', 'body-intro-text', 'methods-here'],
  );
  assert.deepEqual(
    model.sections.map(s => ({ id: s.id, title: s.title, level: s.level })),
    [
      { id: 'a', title: 'Abstract', level: 1 },
      { id: 'b', title: 'Intro', level: 1 },
      { id: 'c', title: 'Methods', level: 2 },
    ],
  );
});

test('buildReaderModel: no sections yields a single Full text section', () => {
  const model = buildReaderModel({ title: 'T', full_text: 'hello world', sections: [] });
  assert.equal(model.sections.length, 1);
  assert.equal(model.sections[0].title, 'Full text');
  assert.equal(model.sections[0].text, 'hello world');
  assert.equal(model.sections[0].id, 's1');
});

test('buildReaderModel: out-of-range char_end is clamped', () => {
  const model = buildReaderModel({
    title: 'T',
    full_text: 'abcdef',
    sections: [{ section_id: 'x', title: 'X', level: 1, char_start: 2, char_end: 999 }],
  });
  assert.equal(model.sections[0].text, 'cdef');
});

test('buildReaderModel: empty full_text returns one empty section, no crash', () => {
  const model = buildReaderModel({ title: 'Empty Paper', full_text: '', sections: [] });
  assert.equal(model.sections.length, 1);
  assert.equal(model.sections[0].text, '');
  assert.equal(model.sections[0].id, 's1');
  assert.equal(model.sections[0].title, 'Empty Paper');
});

test('buildReaderModel: null payload does not crash', () => {
  const model = buildReaderModel(null);
  assert.equal(model.title, 'Untitled');
  assert.equal(model.hasPdf, false);
  assert.equal(model.sections.length, 1);
  assert.equal(model.sections[0].text, '');
});

test('buildReaderModel: empty non-sole sections dropped, sole section kept', () => {
  const full = 'realtext';
  const model = buildReaderModel({
    title: 'T',
    full_text: full,
    sections: [
      { section_id: 'a', title: 'A', level: 1, char_start: 0, char_end: 8 },
      { section_id: 'b', title: 'B', level: 1, char_start: 8, char_end: 8 }, // empty slice
    ],
  });
  assert.equal(model.sections.length, 1);
  assert.equal(model.sections[0].id, 'a');
});

test('buildReaderModel: all-empty multi-section keeps at least one', () => {
  const full = 'xxxxx';
  const model = buildReaderModel({
    title: 'T',
    full_text: full,
    sections: [
      { section_id: 'a', title: 'A', level: 1, char_start: 5, char_end: 5 },
      { section_id: 'b', title: 'B', level: 1, char_start: 5, char_end: 5 },
    ],
  });
  assert.equal(model.sections.length, 1);
});

test('buildReaderModel: title/has_pdf/quote_range passthrough', () => {
  const model = buildReaderModel({
    full_text: 'abc',
    has_pdf: 0,
    quote_range: [1, 2],
    sections: [{ section_id: 'a', title: 'A', level: 1, char_start: 0, char_end: 3 }],
  });
  assert.equal(model.title, 'Untitled');
  assert.equal(model.hasPdf, false);
  assert.deepEqual(model.quoteRange, [1, 2]);
});

// -----------------------------------------------------------------------
// sectionNav
// -----------------------------------------------------------------------

test('sectionNav: numbered labels, level preserved', () => {
  const nav = sectionNav([
    { id: 'a', title: 'Abstract', level: 1 },
    { id: 'b', title: 'Methods', level: 2 },
  ]);
  assert.deepEqual(nav, [
    { id: 'a', label: '§1 Abstract', level: 1 },
    { id: 'b', label: '§2 Methods', level: 2 },
  ]);
});

test('sectionNav: null/empty is []', () => {
  assert.deepEqual(sectionNav(null), []);
  assert.deepEqual(sectionNav([]), []);
});

// -----------------------------------------------------------------------
// resolveActiveSection
// -----------------------------------------------------------------------

const RAW = [
  { section_id: 'a', char_start: 0, char_end: 10 },
  { section_id: 'b', char_start: 10, char_end: 20 },
  { section_id: 'c', char_start: 20, char_end: 30 },
];

test('resolveActiveSection: explicit target wins', () => {
  assert.equal(resolveActiveSection(RAW, 'b', [25, 27]), 'b');
});

test('resolveActiveSection: absent target falls through to quote', () => {
  assert.equal(resolveActiveSection(RAW, 'zzz', [25, 27]), 'c');
});

test('resolveActiveSection: quote picks containing section', () => {
  assert.equal(resolveActiveSection(RAW, null, [12, 15]), 'b');
});

test('resolveActiveSection: nothing resolves to first section', () => {
  assert.equal(resolveActiveSection(RAW, null, null), 'a');
});

test('resolveActiveSection: empty sections returns null', () => {
  assert.equal(resolveActiveSection([], null, null), null);
});

// -----------------------------------------------------------------------
// quoteRangeWithinSection
// -----------------------------------------------------------------------

test('quoteRangeWithinSection: inside gives relative range', () => {
  // section starts at abs 10, text length 10; quote at abs [12,15]
  assert.deepEqual(quoteRangeWithinSection(10, '0123456789', [12, 15]), [2, 5]);
});

test('quoteRangeWithinSection: quote before the section is null', () => {
  assert.equal(quoteRangeWithinSection(10, '0123456789', [2, 6]), null);
});

test('quoteRangeWithinSection: quote after the section is null', () => {
  assert.equal(quoteRangeWithinSection(10, '0123456789', [22, 25]), null);
});

test('quoteRangeWithinSection: null quoteRange is null', () => {
  assert.equal(quoteRangeWithinSection(10, '0123456789', null), null);
});

test('quoteRangeWithinSection: partial overlap clamps to section text', () => {
  // quote spans [8,15]; section abs 10..20 -> relative clamps to [0,5]
  assert.deepEqual(quoteRangeWithinSection(10, '0123456789', [8, 15]), [0, 5]);
});

// -----------------------------------------------------------------------
// hasReadableText
// -----------------------------------------------------------------------

test('hasReadableText: true when any section has non-whitespace text', () => {
  assert.equal(hasReadableText({ sections: [{ text: '' }, { text: '  hi ' }] }), true);
});

test('hasReadableText: false when all sections are empty/whitespace', () => {
  assert.equal(hasReadableText({ sections: [{ text: '' }, { text: '   \n\t' }] }), false);
});

test('hasReadableText: false for empty/absent model', () => {
  assert.equal(hasReadableText({ sections: [] }), false);
  assert.equal(hasReadableText({}), false);
  assert.equal(hasReadableText(null), false);
});

// -----------------------------------------------------------------------
// effectiveQuoteRange
// -----------------------------------------------------------------------

test('effectiveQuoteRange: explicit detail range wins over payload', () => {
  assert.deepEqual(effectiveQuoteRange({ charStart: 12, charEnd: 40 }, [1, 5]), [12, 40]);
});

test('effectiveQuoteRange: explicit range at offset 0 is honoured', () => {
  assert.deepEqual(effectiveQuoteRange({ charStart: 0, charEnd: 8 }, null), [0, 8]);
});

test('effectiveQuoteRange: falls back to payload quote_range when no detail range', () => {
  assert.deepEqual(effectiveQuoteRange({}, [3, 9]), [3, 9]);
  assert.deepEqual(effectiveQuoteRange({ quote: 'x' }, [3, 9]), [3, 9]);
});

test('effectiveQuoteRange: zero/degenerate detail range ignored, falls back', () => {
  assert.deepEqual(effectiveQuoteRange({ charStart: 0, charEnd: 0 }, [2, 6]), [2, 6]);
  assert.deepEqual(effectiveQuoteRange({ charStart: 50, charEnd: 50 }, [2, 6]), [2, 6]);
  assert.deepEqual(effectiveQuoteRange({ charStart: 40, charEnd: 10 }, [2, 6]), [2, 6]);
});

test('effectiveQuoteRange: non-numeric detail range ignored', () => {
  assert.deepEqual(effectiveQuoteRange({ charStart: '12', charEnd: '40' }, [2, 6]), [2, 6]);
  assert.equal(effectiveQuoteRange({ charStart: NaN, charEnd: 40 }, null), null);
});

test('effectiveQuoteRange: null everywhere is null', () => {
  assert.equal(effectiveQuoteRange({}, null), null);
  assert.equal(effectiveQuoteRange(null, null), null);
  assert.equal(effectiveQuoteRange(null, undefined), null);
});
