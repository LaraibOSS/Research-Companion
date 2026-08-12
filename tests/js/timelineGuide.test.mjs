/**
 * timelineGuide.test.mjs — on-page orientation copy for the Timeline view
 * (research_companion/lab/static/js/timelineGuide.js).
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, '..', '..');
const { TIMELINE_HOWTO, TIMELINE_KINDS, hiddenPapersNote } = await import(pathToFileURL(
  path.join(repoRoot, 'research_companion', 'lab', 'static', 'js', 'timelineGuide.js')).href);

test('the how-to explains row, column and dot — the three things the grid never said', () => {
  assert.match(TIMELINE_HOWTO, /row/i);
  assert.match(TIMELINE_HOWTO, /column/i);
  assert.match(TIMELINE_HOWTO, /dot/i);
  assert.match(TIMELINE_HOWTO, /year/i);
  // and what the reader should take away, not just what it draws
  assert.ok(TIMELINE_HOWTO.length > 180, 'needs to say what to conclude, not just label parts');
});

test('kind key covers exactly the kinds the view colours', () => {
  assert.deepEqual(TIMELINE_KINDS.map(k => k.kind), ['concept', 'method', 'dataset']);
  for (const k of TIMELINE_KINDS) assert.ok(k.label.length > 0);
});

test('hiddenPapersNote: silent when nothing is hidden', () => {
  assert.deepEqual(hiddenPapersNote(0), { count: 0, note: '' });
});

test('hiddenPapersNote: singular/plural and tells the user how to fix it', () => {
  const one = hiddenPapersNote(1);
  assert.equal(one.count, 1);
  assert.match(one.note, /1 paper cannot be placed/);
  assert.match(one.note, /it has no publication year/);
  assert.match(one.note, /Library/);

  const many = hiddenPapersNote(7);
  assert.match(many.note, /7 papers cannot be placed/);
  assert.match(many.note, /they have no publication year/);
});

test('hiddenPapersNote: never throws on junk input', () => {
  assert.doesNotThrow(() => hiddenPapersNote(undefined));
  assert.doesNotThrow(() => hiddenPapersNote(null));
  assert.doesNotThrow(() => hiddenPapersNote('x'));
  assert.equal(hiddenPapersNote(-5).count, 0);
  assert.equal(hiddenPapersNote('x').note, '');
});
