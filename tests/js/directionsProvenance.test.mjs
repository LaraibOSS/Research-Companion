/**
 * directionsProvenance.test.mjs — ingest gating + provenance copy for
 * "Generate directions" (research_companion/lab/static/js/directionsProvenance.js).
 *
 * Run from repo root:
 *   node --test tests/js/directionsProvenance.test.mjs
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, '..', '..');

const { ingestStatus, provenanceLine, DIRECTIONS_INTRO, DIRECTIONS_DISCLAIMER } =
  await import(pathToFileURL(path.join(
    repoRoot, 'research_companion', 'lab', 'static', 'js', 'directionsProvenance.js')).href);

function papers(...specs) {
  return new Map(specs.map((s, i) => [`p${i}`, { paper_id: `p${i}`, ...s }]));
}

test('ingestStatus: busy only while a job is actually running', () => {
  const st = ingestStatus({
    papers: papers({ status: 'done' }, { status: 'pending' }, { status: 'pending' }),
    activeJobs: new Map([['job-1', { kind: 'add' }]]),
  });
  assert.equal(st.busy, true);
  assert.equal(st.ready, 1);
  assert.match(st.message, /still being added/);
  assert.match(st.message, /only use the 1 already analyzed/);
});

test('ingestStatus: pending with NO running job is "not analyzed yet", not "being added"', () => {
  // Papers stuck at pending with nothing in flight are not arriving — saying
  // "still being added" would make the user wait forever.
  const st = ingestStatus({
    papers: papers({ status: 'done' }, { status: 'pending' }, { status: 'pending' }),
    activeJobs: new Map(),
  });
  assert.equal(st.busy, false);
  assert.doesNotMatch(st.message, /still being added/);
  assert.match(st.message, /not been analyzed yet/);
  assert.match(st.message, /Retry them from the Library/);
});

test('ingestStatus: a running add job counts as busy even with no pending papers', () => {
  const st = ingestStatus({
    papers: papers({ status: 'done' }),
    activeJobs: new Map([['job-1', { kind: 'add' }]]),
  });
  assert.equal(st.busy, true);
  assert.equal(st.pending, 1);
});

test('ingestStatus: not busy, but reports failures with a manual-add instruction', () => {
  const st = ingestStatus({
    papers: papers({ status: 'done' }, { status: 'done' }, { status: 'failed' }),
    activeJobs: new Map(),
  });
  assert.equal(st.busy, false);
  assert.equal(st.failed, 1);
  assert.equal(st.ready, 2);
  assert.match(st.message, /2 of 3/);
  assert.match(st.message, /manually/i);
});

test('ingestStatus: all done and none failed -> no message at all', () => {
  const st = ingestStatus({
    papers: papers({ status: 'done' }, { status: 'done' }),
    activeJobs: new Map(),
  });
  assert.equal(st.busy, false);
  assert.equal(st.message, '');
});

test('ingestStatus: ignores the draft paper and never throws', () => {
  const st = ingestStatus({
    papers: new Map([['d', { paper_id: 'd', is_draft: true, status: 'pending' }]]),
    activeJobs: new Map(),
  });
  assert.equal(st.busy, false);
  assert.doesNotThrow(() => ingestStatus(undefined));
  assert.doesNotThrow(() => ingestStatus({}));
  assert.doesNotThrow(() => ingestStatus({ papers: 'nope', activeJobs: 5 }));
});

test('provenanceLine: names every source that actually contributed', () => {
  assert.equal(provenanceLine({ papers: 12, concepts: 3, gaps: 2 }),
    'Grounded in 12 papers, 3 concepts from your graph, and 2 open gaps.');
  assert.equal(provenanceLine({ papers: 1, concepts: 0, gaps: 0 }),
    'Grounded in 1 paper.');
  assert.equal(provenanceLine({ papers: 4, concepts: 1, gaps: 0 }),
    'Grounded in 4 papers and 1 concept from your graph.');
});

test('provenanceLine: empty for nothing/absent, never throws', () => {
  assert.equal(provenanceLine({ papers: 0, concepts: 0, gaps: 0 }), '');
  assert.equal(provenanceLine(null), '');
  assert.doesNotThrow(() => provenanceLine(undefined));
  assert.doesNotThrow(() => provenanceLine('x'));
});

test('intro explains the inputs; disclaimer warns it is not exhaustive', () => {
  assert.match(DIRECTIONS_INTRO, /papers you added/i);
  assert.match(DIRECTIONS_INTRO, /graph/i);
  assert.match(DIRECTIONS_INTRO, /gaps/i);
  assert.match(DIRECTIONS_DISCLAIMER, /not exhaustive/i);
  assert.match(DIRECTIONS_DISCLAIMER, /verify/i);
});
