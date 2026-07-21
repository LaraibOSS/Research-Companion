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
  sectionBlocks,
  blockIntersectsRange,
} = await import(
  pathToFileURL(path.join(repoRoot, 'research_companion', 'lab', 'static', 'js', 'readerHelpers.js')).href
);

// Coverage helper: concatenating raw slices for each block, in order,
// must reconstruct the original raw text exactly.
function assertCoverage(rawText, blocks) {
  let rebuilt = '';
  let prevEnd = 0;
  for (const b of blocks) {
    assert.equal(b.start, prevEnd, `block starts must be contiguous (got ${b.start}, expected ${prevEnd})`);
    assert.ok(b.end >= b.start, 'block end must be >= start');
    rebuilt += rawText.slice(b.start, b.end);
    prevEnd = b.end;
  }
  if (blocks.length > 0) assert.equal(prevEnd, rawText.length, 'last block must reach end of text');
  assert.equal(rebuilt, rawText);
}

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
    { id: 'a', label: '1. Abstract', level: 1 },
    { id: 'b', label: '2. Methods', level: 2 },
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

// -----------------------------------------------------------------------
// sectionBlocks
// -----------------------------------------------------------------------

test('sectionBlocks: mid-sentence \\n\\n-wrapped fragments join into one paragraph', () => {
  const raw = 'Consider a recurrent neural network R composed of a parametric\n\nstate transition model S that is presented here.';
  const blocks = sectionBlocks(raw);
  assertCoverage(raw, blocks);
  const paras = blocks.filter(b => b.kind === 'para');
  assert.equal(paras.length, 1);
  assert.equal(
    paras[0].text,
    'Consider a recurrent neural network R composed of a parametric state transition model S that is presented here.',
  );
});

test('sectionBlocks: hyphenation repair across a wrapped line', () => {
  const raw = 'This is a compu-\n\ntation example that spans two lines.';
  const blocks = sectionBlocks(raw);
  assertCoverage(raw, blocks);
  assert.equal(blocks.length, 1);
  assert.equal(blocks[0].kind, 'para');
  assert.equal(blocks[0].text, 'This is a computation example that spans two lines.');
});

test('sectionBlocks: single-\\n wrapped input also joins into one paragraph', () => {
  const raw = 'Consider a recurrent neural network R composed of a parametric\nstate transition model S that is presented here.';
  const blocks = sectionBlocks(raw);
  assertCoverage(raw, blocks);
  const paras = blocks.filter(b => b.kind === 'para');
  assert.equal(paras.length, 1);
  assert.equal(
    paras[0].text,
    'Consider a recurrent neural network R composed of a parametric state transition model S that is presented here.',
  );
});

test('sectionBlocks: terminal punctuation + uppercase start begins a new paragraph', () => {
  const raw = 'First sentence ends here.\n\nSecond paragraph starts now and continues\n\non the next line.';
  const blocks = sectionBlocks(raw);
  assertCoverage(raw, blocks);
  const paras = blocks.filter(b => b.kind === 'para');
  assert.equal(paras.length, 2);
  assert.equal(paras[0].text, 'First sentence ends here.');
  assert.equal(paras[1].text, 'Second paragraph starts now and continues on the next line.');
});

test('sectionBlocks: numbered heading-echo is detected and flagged', () => {
  const raw = '2 Adaptive Computation Time\n\nConsider a recurrent neural network R composed of a parametric state transition model.';
  const blocks = sectionBlocks(raw, 'Adaptive Computation Time');
  assertCoverage(raw, blocks);
  assert.equal(blocks[0].kind, 'heading-echo');
  assert.equal(blocks[1].kind, 'para');
});

test('sectionBlocks: unnumbered heading-echo is detected and flagged', () => {
  const raw = 'Introduction\n\nThe amount of time required to pose a problem varies greatly from case to case.';
  const blocks = sectionBlocks(raw, 'Introduction');
  assertCoverage(raw, blocks);
  assert.equal(blocks[0].kind, 'heading-echo');
  assert.equal(blocks[1].kind, 'para');
});

test('sectionBlocks: no heading-echo when title is not supplied', () => {
  const raw = 'Introduction\n\nThe amount of time required to pose a problem varies greatly from case to case.';
  const blocks = sectionBlocks(raw);
  assertCoverage(raw, blocks);
  assert.notEqual(blocks[0].kind, 'heading-echo');
});

test('sectionBlocks: no heading-echo when first fragment does not match the title', () => {
  const raw = 'Adaptive Computation Time\n\nfor Recurrent Neural Networks\n\nAlex Graves\n\nAbstract text goes here and it is long enough.';
  const blocks = sectionBlocks(raw, 'Abstract');
  assertCoverage(raw, blocks);
  assert.ok(!blocks.some(b => b.kind === 'heading-echo'));
});

test('sectionBlocks: figure/table caption becomes its own block, not merged into paragraphs', () => {
  const raw = 'Some paragraph text goes here and it is long.\n\nFigure 1: RNN Computation Graph. An RNN unrolled over two steps.\n\nMore paragraph text follows after the figure.';
  const blocks = sectionBlocks(raw);
  assertCoverage(raw, blocks);
  const captions = blocks.filter(b => b.kind === 'caption');
  assert.equal(captions.length, 1);
  assert.equal(captions[0].text, 'Figure 1: RNN Computation Graph. An RNN unrolled over two steps.');
  const kinds = blocks.map(b => b.kind);
  assert.deepEqual(kinds, ['para', 'caption', 'para']);
});

test('sectionBlocks: Table caption prefix is also recognized', () => {
  const raw = 'Table 1: Binary Truth Tables for the Logic Task';
  const blocks = sectionBlocks(raw);
  assertCoverage(raw, blocks);
  assert.equal(blocks.length, 1);
  assert.equal(blocks[0].kind, 'caption');
});

test('sectionBlocks: a run of >=2 columnar fragments groups into one table block', () => {
  const raw = 'Model sizes used in our experiments.\n\n1 4 6 8 12 20 32 48 64\n\n0.5 1.0 1.5 2.0 2.5 3.0 3.5 4.0 4.5\n\nDiscussion of the results follows.';
  const blocks = sectionBlocks(raw);
  assertCoverage(raw, blocks);
  const tables = blocks.filter(b => b.kind === 'table');
  assert.equal(tables.length, 1);
  // table block preserves internal newlines/spacing verbatim
  assert.ok(tables[0].text.includes('1 4 6 8 12 20 32 48 64'));
  assert.ok(tables[0].text.includes('0.5 1.0 1.5 2.0 2.5 3.0 3.5 4.0 4.5'));
});

test('sectionBlocks: a single columnar-looking line alone does not become a table', () => {
  const raw = 'Some intro text.\n\n1 4 6 8 12\n\nMore prose continues normally after that.';
  const blocks = sectionBlocks(raw);
  assertCoverage(raw, blocks);
  assert.ok(!blocks.some(b => b.kind === 'table'));
});

test('sectionBlocks: a citation-heavy prose line is not mistaken for a table', () => {
  const raw = 'This has been shown before (Brown et al., 2020; Chowdhery et al., 2023; Llama Team, 2024) in many settings.';
  const blocks = sectionBlocks(raw);
  assertCoverage(raw, blocks);
  assert.ok(!blocks.some(b => b.kind === 'table'));
});

test('sectionBlocks: short equation-like line becomes its own display block', () => {
  const raw = 'is for 1 to B:\n\nbi+1 = Ti(bi\n\n, bi-1) (21)\n\nwhere Ti is the truth table indexed by chunk i.';
  const blocks = sectionBlocks(raw);
  assertCoverage(raw, blocks);
  const displays = blocks.filter(b => b.kind === 'display');
  assert.equal(displays.length, 2);
  assert.equal(displays[0].text, 'bi+1 = Ti(bi');
  assert.equal(displays[1].text, ', bi-1) (21)');
});

test('sectionBlocks: coverage property holds for a mixed multi-kind document', () => {
  const raw = [
    '2 Adaptive Computation Time',
    '',
    'Consider a recurrent neural network R composed of a parametric',
    '',
    'state transition model S that is presented here.',
    '',
    'Figure 1: RNN Computation Graph. An RNN unrolled over two steps.',
    '',
    '1 4 6 8 12 20 32 48 64',
    '',
    '0.5 1.0 1.5 2.0 2.5 3.0 3.5 4.0 4.5',
    '',
    'x = y + 1 (3)',
    '',
    'A final paragraph wraps things up nicely.',
  ].join('\n');
  const blocks = sectionBlocks(raw, 'Adaptive Computation Time');
  assertCoverage(raw, blocks);
  assert.ok(blocks.some(b => b.kind === 'heading-echo'));
  assert.ok(blocks.some(b => b.kind === 'caption'));
  assert.ok(blocks.some(b => b.kind === 'table'));
  assert.ok(blocks.some(b => b.kind === 'display'));
  assert.ok(blocks.some(b => b.kind === 'para'));
});

test('sectionBlocks: empty raw text yields no blocks', () => {
  assert.deepEqual(sectionBlocks(''), []);
  assert.deepEqual(sectionBlocks(null), []);
});

test('sectionBlocks: whitespace-only raw text yields one empty para block covering it', () => {
  const raw = '   \n\n  ';
  const blocks = sectionBlocks(raw);
  assertCoverage(raw, blocks);
  assert.equal(blocks.length, 1);
  assert.equal(blocks[0].text, '');
});

test('sectionBlocks: standalone page-number lines do not break paragraph flow', () => {
  const raw = 'It remains necessary for the experimenter to decide a priori on the\n\namount allocated to a particular input vector or sequence.\n\n3\n\nWe now describe the architecture used for this purpose in detail.';
  const blocks = sectionBlocks(raw);
  assertCoverage(raw, blocks);
  // the lone page number "3" should not spawn its own paragraph break /
  // survive as visible clutter in the joined paragraph text.
  const paras = blocks.filter(b => b.kind === 'para');
  assert.ok(!paras.some(p => p.text.trim() === '3'));
});

// -----------------------------------------------------------------------
// blockIntersectsRange (quote-highlight safety decision helper)
// -----------------------------------------------------------------------

test('blockIntersectsRange: overlapping range intersects', () => {
  assert.equal(blockIntersectsRange({ start: 10, end: 20 }, [5, 12]), true);
  assert.equal(blockIntersectsRange({ start: 10, end: 20 }, [15, 25]), true);
  assert.equal(blockIntersectsRange({ start: 10, end: 20 }, [10, 20]), true);
  assert.equal(blockIntersectsRange({ start: 10, end: 20 }, [5, 25]), true);
});

test('blockIntersectsRange: disjoint range does not intersect', () => {
  assert.equal(blockIntersectsRange({ start: 10, end: 20 }, [0, 10]), false);
  assert.equal(blockIntersectsRange({ start: 10, end: 20 }, [20, 30]), false);
  assert.equal(blockIntersectsRange({ start: 10, end: 20 }, [21, 30]), false);
});

test('blockIntersectsRange: null/missing range never intersects', () => {
  assert.equal(blockIntersectsRange({ start: 10, end: 20 }, null), false);
  assert.equal(blockIntersectsRange({ start: 10, end: 20 }, undefined), false);
  assert.equal(blockIntersectsRange(null, [10, 20]), false);
});

// -----------------------------------------------------------------------
// _isDisplayLine heuristic refinement (prose vs. equations)
// -----------------------------------------------------------------------

test('sectionBlocks: short prose with = and terminal period is NOT display (bug fix)', () => {
  // This used to be mis-styled as display, but it's prose: "and this shows y = f(x) clearly."
  const raw = 'Before this. and this shows y = f(x) clearly. After that.';
  const blocks = sectionBlocks(raw);
  assertCoverage(raw, blocks);
  // Should be 1 paragraph (not display + para)
  const paras = blocks.filter(b => b.kind === 'para');
  const displays = blocks.filter(b => b.kind === 'display');
  assert.equal(displays.length, 0);
  assert.equal(paras.length, 1);
});

test('sectionBlocks: equation with numbering still becomes display even with period', () => {
  // "st = S(st−1, Wxxt) (1)" with equation number is still display
  const raw = 'st = S(st−1, Wxxt) (1)\n\nMore text continues.';
  const blocks = sectionBlocks(raw);
  assertCoverage(raw, blocks);
  const displays = blocks.filter(b => b.kind === 'display');
  assert.equal(displays.length, 1);
  assert.equal(displays[0].text, 'st = S(st−1, Wxxt) (1)');
});

test('sectionBlocks: short equation without period is still display', () => {
  // "E = mc2" without terminal punctuation is display
  const raw = 'E = mc2\n\nMore text.';
  const blocks = sectionBlocks(raw);
  assertCoverage(raw, blocks);
  const displays = blocks.filter(b => b.kind === 'display');
  assert.equal(displays.length, 1);
  assert.equal(displays[0].text, 'E = mc2');
});

test('sectionBlocks: prose line with stray double-space is NOT columnar (bug fix)', () => {
  // Single double-space in prose should not trigger table detection
  const raw = 'This has been shown  in many settings.';
  const blocks = sectionBlocks(raw);
  assertCoverage(raw, blocks);
  const tables = blocks.filter(b => b.kind === 'table');
  assert.equal(tables.length, 0);
  // Should be a paragraph, not a table
  const paras = blocks.filter(b => b.kind === 'para');
  assert.equal(paras.length, 1);
});

test('sectionBlocks: two numeric-heavy lines with space runs form a table', () => {
  // Two columnar lines with multiple space runs and numeric tokens
  const raw = '1  2  3  4  5\n\n0.5  1.0  1.5  2.0';
  const blocks = sectionBlocks(raw);
  assertCoverage(raw, blocks);
  const tables = blocks.filter(b => b.kind === 'table');
  // Both lines are columnar → 1 table
  assert.equal(tables.length, 1);
});

test('sectionBlocks: two numeric-heavy lines with 2 space runs form a table', () => {
  // Two lines with 2 space runs + 3+ numeric tokens
  const raw = '1 2 3 4 5\n\n0.5 1.0 1.5';
  const blocks = sectionBlocks(raw);
  assertCoverage(raw, blocks);
  const tables = blocks.filter(b => b.kind === 'table');
  // Both lines meet criteria → 1 table
  assert.equal(tables.length, 1);
});
