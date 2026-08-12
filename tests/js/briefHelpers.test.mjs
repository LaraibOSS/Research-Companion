/**
 * briefHelpers.test.mjs — pure model + edit ops for the Brainstorm Brief panel
 * (research_companion/lab/static/js/briefHelpers.js).
 *
 * Run from repo root:
 *   node --test tests/js/briefHelpers.test.mjs
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, '..', '..');

const H = await import(pathToFileURL(path.join(
  repoRoot, 'research_companion', 'lab', 'static', 'js', 'briefHelpers.js')).href);
const { briefModel, setBulletText, deleteBullet, addBullet, deleteSection, moveBullet } = H;

function makeBrief() {
  return {
    brief_id: 'brief_abc',
    topic: 'temporal knowledge graphs',
    sections: [
      { title: 'Background', bullets: [
        { text: 'TKGs store episodic memory', citations: [{ paper_id: 'arxiv:1', title: 'Zep', year: 2025 }] },
        { text: 'Recall decays over long dialogues', citations: [{ paper_id: 'arxiv:2', title: 'LongMemEval', year: 2024 }] },
      ] },
      { title: 'Method', bullets: [
        { text: 'Build the graph incrementally', citations: [{ paper_id: 'arxiv:1', title: 'Zep', year: 2025 }] },
      ] },
    ],
  };
}

test('briefModel: pre-escapes text/title and builds citation labels', () => {
  const b = makeBrief();
  b.sections[0].bullets[0].text = 'a <b> & "c"';
  const m = briefModel(b);
  assert.equal(m.isEmpty, false);
  assert.equal(m.sectionCount, 2);
  assert.equal(m.bulletCount, 3);
  assert.equal(m.sections[0].bullets[0].text, 'a &lt;b&gt; &amp; &quot;c&quot;');
  assert.equal(m.sections[0].bullets[0].rawText, 'a <b> & "c"'); // raw kept for the editor
  assert.match(m.sections[0].bullets[1].citations[0].label, /LongMemEval 2024/);
  assert.equal(m.sections[0].bullets[1].citations[0].paperId, 'arxiv:2');
});

test('briefModel: empty brief and never throws on junk', () => {
  assert.equal(briefModel({ sections: [] }).isEmpty, true);
  assert.doesNotThrow(() => briefModel(null));
  assert.doesNotThrow(() => briefModel({ sections: 'nope' }));
  assert.equal(briefModel(null).isEmpty, true);
});

test('setBulletText: replaces text, returns a NEW brief, out-of-range is a no-op', () => {
  const b = makeBrief();
  const next = setBulletText(b, 0, 1, 'edited point');
  assert.equal(next.sections[0].bullets[1].text, 'edited point');
  assert.equal(b.sections[0].bullets[1].text, 'Recall decays over long dialogues'); // original untouched
  assert.equal(setBulletText(b, 9, 9, 'x'), b); // no-op returns same ref
});

test('deleteBullet / addBullet: mutate a copy; added bullet has empty citations', () => {
  const b = makeBrief();
  const afterDel = deleteBullet(b, 0, 0);
  assert.equal(afterDel.sections[0].bullets.length, 1);
  assert.equal(b.sections[0].bullets.length, 2);
  const afterAdd = addBullet(b, 1, 'my own point');
  assert.equal(afterAdd.sections[1].bullets.length, 2);
  assert.deepEqual(afterAdd.sections[1].bullets[1], { text: 'my own point', citations: [] });
  // model flags a citation-less bullet as user-added
  assert.equal(briefModel(afterAdd).sections[1].bullets[1].userAdded, true);
});

test('deleteSection: removes a section; out-of-range no-op', () => {
  const b = makeBrief();
  const next = deleteSection(b, 0);
  assert.equal(next.sections.length, 1);
  assert.equal(next.sections[0].title, 'Method');
  assert.equal(deleteSection(b, 5), b);
});

test('moveBullet: swaps within section, clamps at edges', () => {
  const b = makeBrief();
  const down = moveBullet(b, 0, 0, 1);
  assert.equal(down.sections[0].bullets[0].text, 'Recall decays over long dialogues');
  assert.equal(down.sections[0].bullets[1].text, 'TKGs store episodic memory');
  assert.equal(moveBullet(b, 0, 0, -1), b); // already at top -> no-op
  assert.equal(moveBullet(b, 0, 1, 1), b);  // already at bottom -> no-op
});
