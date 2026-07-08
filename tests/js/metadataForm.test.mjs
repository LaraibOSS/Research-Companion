/**
 * metadataForm.test.mjs — Tests for the manual metadata-edit pure helpers:
 *   parseAuthorsInput, parseYearInput, buildPaperPatch (js/metadataForm.js)
 *
 * Run from repo root:
 *   node --test tests/js/metadataForm.test.mjs
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot  = path.resolve(__dirname, '..', '..');

const { parseAuthorsInput, parseYearInput, buildPaperPatch } = await import(
  pathToFileURL(path.join(repoRoot, 'research_companion', 'lab', 'static', 'js', 'metadataForm.js')).href
);

// ---------------------------------------------------------------------------
// parseAuthorsInput
// ---------------------------------------------------------------------------

test('parseAuthorsInput: splits on commas and trims', () => {
  assert.deepEqual(parseAuthorsInput('Alice, Bob, Carol'), ['Alice', 'Bob', 'Carol']);
});

test('parseAuthorsInput: drops blanks and extra whitespace', () => {
  assert.deepEqual(parseAuthorsInput('Alice ,, ,  Bob  ,'), ['Alice', 'Bob']);
});

test('parseAuthorsInput: empty/blank -> []', () => {
  assert.deepEqual(parseAuthorsInput(''), []);
  assert.deepEqual(parseAuthorsInput('   '), []);
  assert.deepEqual(parseAuthorsInput(',,,'), []);
});

test('parseAuthorsInput: null/undefined -> []', () => {
  assert.deepEqual(parseAuthorsInput(null), []);
  assert.deepEqual(parseAuthorsInput(undefined), []);
});

test('parseAuthorsInput: single author', () => {
  assert.deepEqual(parseAuthorsInput('  Jane Doe  '), ['Jane Doe']);
});

// ---------------------------------------------------------------------------
// parseYearInput
// ---------------------------------------------------------------------------

test('parseYearInput: blank -> ok null (clear)', () => {
  assert.deepEqual(parseYearInput(''), { ok: true, value: null });
  assert.deepEqual(parseYearInput('   '), { ok: true, value: null });
  assert.deepEqual(parseYearInput(null), { ok: true, value: null });
  assert.deepEqual(parseYearInput(undefined), { ok: true, value: null });
});

test('parseYearInput: valid int in range -> ok int', () => {
  assert.deepEqual(parseYearInput('2020'), { ok: true, value: 2020 });
  assert.deepEqual(parseYearInput(' 1999 '), { ok: true, value: 1999 });
});

test('parseYearInput: boundary years 1900 and 2100 are valid', () => {
  assert.deepEqual(parseYearInput('1900'), { ok: true, value: 1900 });
  assert.deepEqual(parseYearInput('2100'), { ok: true, value: 2100 });
});

test('parseYearInput: out of range -> error', () => {
  assert.equal(parseYearInput('1899').ok, false);
  assert.equal(parseYearInput('2101').ok, false);
  assert.ok(parseYearInput('1899').error);
});

test('parseYearInput: non-numeric -> error', () => {
  assert.equal(parseYearInput('abc').ok, false);
  assert.equal(parseYearInput('20a0').ok, false);
  assert.equal(parseYearInput('20.5').ok, false);
  assert.equal(parseYearInput('-2000').ok, false);
});

// ---------------------------------------------------------------------------
// buildPaperPatch
// ---------------------------------------------------------------------------

test('buildPaperPatch: full valid input', () => {
  const res = buildPaperPatch({ title: 'A Title', authorsStr: 'Alice, Bob', yearStr: '2021' });
  assert.deepEqual(res, { body: { title: 'A Title', authors: ['Alice', 'Bob'], year: 2021 } });
});

test('buildPaperPatch: empty title is omitted (never send title:null)', () => {
  const res = buildPaperPatch({ title: '   ', authorsStr: 'Alice', yearStr: '2021' });
  assert.ok(!('title' in res.body), 'title must be omitted when blank');
  assert.deepEqual(res.body.authors, ['Alice']);
  assert.equal(res.body.year, 2021);
});

test('buildPaperPatch: empty authors -> [] (clears)', () => {
  const res = buildPaperPatch({ title: 'T', authorsStr: '', yearStr: '2021' });
  assert.deepEqual(res.body.authors, []);
});

test('buildPaperPatch: blank year -> null (clears)', () => {
  const res = buildPaperPatch({ title: 'T', authorsStr: 'Alice', yearStr: '' });
  assert.equal(res.body.year, null);
  assert.ok('year' in res.body, 'year key must be present to clear');
});

test('buildPaperPatch: invalid year -> {error}, no body', () => {
  const res = buildPaperPatch({ title: 'T', authorsStr: 'Alice', yearStr: '1500' });
  assert.ok(res.error, 'must return an error');
  assert.ok(!('body' in res), 'must not return a body on error');
});

test('buildPaperPatch: title trimmed', () => {
  const res = buildPaperPatch({ title: '  Trimmed  ', authorsStr: '', yearStr: '' });
  assert.equal(res.body.title, 'Trimmed');
});

test('buildPaperPatch: no args -> clears authors and year', () => {
  const res = buildPaperPatch();
  assert.deepEqual(res.body.authors, []);
  assert.equal(res.body.year, null);
  assert.ok(!('title' in res.body));
});
