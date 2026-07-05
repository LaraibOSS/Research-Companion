/**
 * askcompare.test.mjs — Table-driven tests for the F4 pure functions:
 *   renderAnswerHtml (views/ask.js)
 *   resolvePaperInput, betterValue (views/compare.js)
 *
 * Run from repo root:
 *   node --test tests/js/reducer.test.mjs tests/js/sse.test.mjs tests/js/format.test.mjs tests/js/mapping.test.mjs tests/js/snapshotRefresher.test.mjs tests/js/draftdock.test.mjs tests/js/askcompare.test.mjs
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, '..', '..');
const jsRoot = path.join(repoRoot, 'research_companion', 'lab', 'static', 'js');

const { renderAnswerHtml } = await import(
  pathToFileURL(path.join(jsRoot, 'views', 'ask.js')).href
);
const { resolvePaperInput, betterValue } = await import(
  pathToFileURL(path.join(jsRoot, 'views', 'compare.js')).href
);

// ---------------------------------------------------------------------------
// renderAnswerHtml — escaping FIRST (hard security requirement)
// ---------------------------------------------------------------------------

test('renderAnswerHtml escapes a <script> tag — never survives', () => {
  const html = renderAnswerHtml('<script>alert(1)</script>', []);
  assert.ok(!html.includes('<script'), `raw <script survived: ${html}`);
  assert.ok(html.includes('&lt;script&gt;'), `escaped form missing: ${html}`);
});

test('renderAnswerHtml escapes markup inside bold spans', () => {
  const html = renderAnswerHtml('**<img src=x onerror=alert(1)>**', []);
  assert.ok(!html.includes('<img'), `raw <img survived: ${html}`);
  assert.ok(html.includes('<strong>'), 'bold should still apply');
});

test('renderAnswerHtml escapes markup inside code spans', () => {
  const html = renderAnswerHtml('`<b>x</b>`', []);
  assert.ok(!html.includes('<b>'), `raw <b> survived: ${html}`);
  assert.ok(html.includes('<code>'), 'code span should apply');
});

test('renderAnswerHtml escapes quotes and ampersands', () => {
  const html = renderAnswerHtml('a & b "c"', []);
  assert.ok(html.includes('&amp;'));
  assert.ok(html.includes('&quot;c&quot;'));
});

// ---------------------------------------------------------------------------
// renderAnswerHtml — citation tags
// ---------------------------------------------------------------------------

test('renderAnswerHtml replaces [S1] with a cite chip', () => {
  const html = renderAnswerHtml('Fact [S1].', [{ n: 1 }]);
  assert.ok(html.includes('<sup class="cite" data-n="1">[1]</sup>'), html);
  assert.ok(!html.includes('[S1]'), 'raw tag must be replaced');
});

test('renderAnswerHtml replaces bare [2] with a cite chip', () => {
  const html = renderAnswerHtml('Fact [2].', []);
  assert.ok(html.includes('<sup class="cite" data-n="2">[2]</sup>'), html);
});

test('renderAnswerHtml handles multi-digit citation tags', () => {
  const html = renderAnswerHtml('See [S12] and [34].', []);
  assert.ok(html.includes('<sup class="cite" data-n="12">[12]</sup>'), html);
  assert.ok(html.includes('<sup class="cite" data-n="34">[34]</sup>'), html);
});

test('renderAnswerHtml leaves non-citation brackets alone', () => {
  const html = renderAnswerHtml('array[i] and [foo]', []);
  assert.ok(html.includes('array[i]'), html);
  assert.ok(html.includes('[foo]'), html);
});

// ---------------------------------------------------------------------------
// renderAnswerHtml — markdown-lite
// ---------------------------------------------------------------------------

test('renderAnswerHtml splits paragraphs on blank lines', () => {
  const html = renderAnswerHtml('First para.\n\nSecond para.', []);
  const paras = html.match(/<p>/g) || [];
  assert.equal(paras.length, 2, html);
  assert.ok(html.includes('First para.'));
  assert.ok(html.includes('Second para.'));
});

test('renderAnswerHtml renders **bold**', () => {
  const html = renderAnswerHtml('a **bold** word', []);
  assert.ok(html.includes('<strong>bold</strong>'), html);
});

test('renderAnswerHtml renders `code` spans', () => {
  const html = renderAnswerHtml('use `foo()` here', []);
  assert.ok(html.includes('<code>foo()</code>'), html);
});

test('renderAnswerHtml renders "- " lines as a list', () => {
  const html = renderAnswerHtml('- one\n- two', []);
  assert.ok(html.includes('<ul>'), html);
  const items = html.match(/<li>/g) || [];
  assert.equal(items.length, 2, html);
  assert.ok(html.includes('<li>one</li>'), html);
});

test('renderAnswerHtml combines list, bold and citation in one answer', () => {
  const html = renderAnswerHtml('Intro [S1].\n\n- **x** wins\n- see [2]', []);
  assert.ok(html.includes('<p>'), html);
  assert.ok(html.includes('<ul>'), html);
  assert.ok(html.includes('<strong>x</strong>'), html);
  assert.ok(html.includes('data-n="1"'), html);
  assert.ok(html.includes('data-n="2"'), html);
});

test('renderAnswerHtml handles null/empty answers', () => {
  assert.equal(typeof renderAnswerHtml('', []), 'string');
  assert.equal(typeof renderAnswerHtml(null, []), 'string');
});

// ---------------------------------------------------------------------------
// resolvePaperInput
// ---------------------------------------------------------------------------

const PAPERS = [
  { paper_id: '2401.001', title: 'Attention Is All You Need' },
  { paper_id: '2401.002', title: 'Attention Approximations at Scale' },
  { paper_id: '2401.003', title: 'BERT: Pre-training Deep Bidirectional Transformers' },
];

test('resolvePaperInput matches exact paper_id', () => {
  assert.equal(resolvePaperInput('2401.003', PAPERS), '2401.003');
});

test('resolvePaperInput matches unique title prefix (case-insensitive)', () => {
  assert.equal(resolvePaperInput('bert', PAPERS), '2401.003');
  assert.equal(resolvePaperInput('Attention Is', PAPERS), '2401.001');
});

test('resolvePaperInput returns null on ambiguous prefix', () => {
  assert.equal(resolvePaperInput('Attention', PAPERS), null);
});

test('resolvePaperInput ambiguous prefix resolved by exact full title', () => {
  const papers = [
    { paper_id: 'a', title: 'Scaling Laws' },
    { paper_id: 'b', title: 'Scaling Laws for Neural LMs' },
  ];
  assert.equal(resolvePaperInput('Scaling Laws', papers), 'a');
});

test('resolvePaperInput returns null on no match / empty / null', () => {
  assert.equal(resolvePaperInput('zzz nothing', PAPERS), null);
  assert.equal(resolvePaperInput('', PAPERS), null);
  assert.equal(resolvePaperInput('   ', PAPERS), null);
  assert.equal(resolvePaperInput(null, PAPERS), null);
});

test('resolvePaperInput trims whitespace', () => {
  assert.equal(resolvePaperInput('  2401.001  ', PAPERS), '2401.001');
});

// ---------------------------------------------------------------------------
// betterValue — higher wins; leading-float parse; null when unparseable/equal
// ---------------------------------------------------------------------------

const betterValueCases = [
  ['85.2', '83.1', 'a'],
  ['0.1', '0.2', 'b'],
  ['85.2±0.3', '84.9', 'a'],          // leading float parsed from "85.2±0.3"
  ['84.9', '85.2 ± 0.3', 'b'],
  ['-1.5', '-2.5', 'a'],
  ['+3', '2', 'a'],
  ['.5', '0.4', 'a'],
  ['85.2', '85.2', null],             // equal
  ['85.2±0.3', '85.2±0.9', null],     // equal after leading-float parse
  ['n/a', '5', null],                 // unparseable
  ['5', 'n/a', null],
  [null, '5', null],
  [undefined, undefined, null],
  ['', '5', null],
];

for (const [a, b, expected] of betterValueCases) {
  test(`betterValue(${JSON.stringify(a)}, ${JSON.stringify(b)}) === ${JSON.stringify(expected)}`, () => {
    assert.equal(betterValue(a, b), expected);
  });
}

test('betterValue accepts numeric inputs', () => {
  assert.equal(betterValue(2, 1), 'a');
  assert.equal(betterValue(1, 2), 'b');
  assert.equal(betterValue(2, 2), null);
});
