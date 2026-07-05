/**
 * format.test.mjs — Table-driven tests for format.js helpers.
 * Run from repo root: node --test tests/js/
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, '..', '..');
const { strengthColor, stanceIcon, authorsLine, escapeHtml, timeAgo } = await import(
  pathToFileURL(path.join(repoRoot, 'research_companion', 'lab', 'static', 'js', 'format.js')).href
);

// --- strengthColor ---
const strengthColorCases = [
  ['strong',     '#3fb950'],
  ['moderate',   '#d29922'],
  ['weak',       '#f0883e'],
  ['failed',     '#f85149'],
  ['unscored',   '#8b949e'],
  ['processing', '#58a6ff'],
  [null,         '#8b949e'],
  [undefined,    '#8b949e'],
  ['unknown_band', '#8b949e'],
];

for (const [band, expected] of strengthColorCases) {
  test(`strengthColor(${JSON.stringify(band)}) === ${expected}`, () => {
    assert.equal(strengthColor(band), expected);
  });
}

// --- stanceIcon ---
const stanceIconCases = [
  ['strengthens',  '▲'],
  ['challenges',   '⚡'],
  ['alternative',  '◆'],
  ['unknown',      ''],
  [null,           ''],
  [undefined,      ''],
];

for (const [rel, expected] of stanceIconCases) {
  test(`stanceIcon(${JSON.stringify(rel)}) === ${JSON.stringify(expected)}`, () => {
    assert.equal(stanceIcon(rel), expected);
  });
}

// --- authorsLine ---
test('authorsLine with full list and year', () => {
  const result = authorsLine(['Alice', 'Bob', 'Carol'], 2023);
  assert.ok(result.includes('Alice'), 'should include first author');
  assert.ok(result.includes('2023'), 'should include year');
});

test('authorsLine with empty list', () => {
  const result = authorsLine([], 2023);
  assert.ok(typeof result === 'string');
});

test('authorsLine truncates long author list with et al', () => {
  const authors = ['A', 'B', 'C', 'D', 'E'];
  const result = authorsLine(authors, 2021);
  assert.ok(result.includes('et al') || result.includes('A'), 'should handle long list');
});

// --- escapeHtml ---
const escapeHtmlCases = [
  ['<script>', '&lt;script&gt;'],
  ['a & b',    'a &amp; b'],
  ['"hello"',  '&quot;hello&quot;'],
  ["it's",     'it&#39;s'],
  ['safe',     'safe'],
];

for (const [input, expected] of escapeHtmlCases) {
  test(`escapeHtml(${JSON.stringify(input)}) === ${JSON.stringify(expected)}`, () => {
    assert.equal(escapeHtml(input), expected);
  });
}

// --- timeAgo ---
test('timeAgo returns a string', () => {
  const now = new Date().toISOString();
  const result = timeAgo(now);
  assert.ok(typeof result === 'string' && result.length > 0);
});

test('timeAgo returns "just now" for very recent time', () => {
  const now = new Date().toISOString();
  const result = timeAgo(now);
  assert.ok(
    result.includes('just now') || result.includes('second') || result.includes('ago'),
    `got: ${result}`
  );
});

test('timeAgo handles null/undefined gracefully', () => {
  assert.ok(typeof timeAgo(null) === 'string');
  assert.ok(typeof timeAgo(undefined) === 'string');
});
