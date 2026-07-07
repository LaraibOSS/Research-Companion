/**
 * reducer.test.mjs — TDD tests for the pure-JS reducer.
 * Run from repo root: node --test tests/js/
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, '..', '..');
const { applyEvent } = await import(
  pathToFileURL(path.join(repoRoot, 'research_companion', 'lab', 'static', 'js', 'reducer.js')).href
);

// Helper: build initial state
function makeState() {
  return {
    papers: new Map(),
    draftId: null,
    sections: [],
    lab: { counts: {} },
    jobs: new Map(),
    connection: 'connected',
    failures: {},
    graphSeq: 0,
  };
}

test('paper_added upserts paper with status processing', () => {
  const state = makeState();
  const topics = applyEvent(state, {
    event: 'paper_added',
    paper_id: 'p1',
    title: 'Test Paper',
    source: 'http://example.com',
  });
  assert.ok(state.papers.has('p1'), 'paper p1 should be in papers map');
  const paper = state.papers.get('p1');
  assert.equal(paper.status, 'processing');
  assert.equal(paper.title, 'Test Paper');
  assert.ok(topics.includes('papers'), 'should emit papers topic');
});

test('strength_updated sets paper.strength', () => {
  const state = makeState();
  state.papers.set('p1', { paper_id: 'p1', status: 'processing' });
  const topics = applyEvent(state, {
    event: 'strength_updated',
    paper_id: 'p1',
    score: 0.6,
    band: 'moderate',
    color: '#d29922',
  });
  const paper = state.papers.get('p1');
  assert.deepEqual(paper.strength, { score: 0.6, band: 'moderate', color: '#d29922' });
  assert.ok(topics.includes('papers'));
});

test('ingest_failed sets paper status failed and records failure', () => {
  const state = makeState();
  state.papers.set('local:fixb', { paper_id: 'local:fixb', status: 'processing' });
  const topics = applyEvent(state, {
    event: 'ingest_failed',
    path: 'paper_b.pdf',
    stage: 'extract',
    error: 'fixture extraction error',
    paper_id: 'local:fixb',
  });
  const paper = state.papers.get('local:fixb');
  assert.equal(paper.status, 'failed');
  assert.equal(paper.failure_reason, 'fixture extraction error');
  assert.ok(state.failures['local:fixb'] || state.failures['paper_b.pdf'], 'failure recorded');
  assert.ok(topics.includes('papers'));
});

test('ingest_progress updates jobs map', () => {
  const state = makeState();
  const topics = applyEvent(state, {
    event: 'ingest_progress',
    done: 1,
    total: 3,
    current: 'paper_b.pdf',
  });
  assert.ok(topics.includes('jobs'));
  assert.ok(state.jobs.has('ingest'), 'ingest job should be tracked');
  const job = state.jobs.get('ingest');
  assert.equal(job.done, 1);
  assert.equal(job.total, 3);
});

test('job_done transitions processing papers to done', () => {
  const state = makeState();
  state.papers.set('p1', { paper_id: 'p1', status: 'processing' });
  state.papers.set('p2', { paper_id: 'p2', status: 'processing' });
  state.papers.set('p3', { paper_id: 'p3', status: 'failed' });
  const topics = applyEvent(state, { event: 'job_done', job: 'ingest' });
  assert.equal(state.papers.get('p1').status, 'done');
  assert.equal(state.papers.get('p2').status, 'done');
  // failed stays failed
  assert.equal(state.papers.get('p3').status, 'failed');
  assert.ok(topics.includes('jobs'));
  assert.ok(topics.includes('papers'));
});

test('graph_delta bumps graphSeq', () => {
  const state = makeState();
  assert.equal(state.graphSeq, 0);
  applyEvent(state, {
    event: 'graph_delta',
    paper_id: 'p1',
    nodes_added: [],
    edges_added: [],
  });
  assert.equal(state.graphSeq, 1);
});

test('alignment_ready sets paper.stance and .score', () => {
  const state = makeState();
  state.papers.set('p1', { paper_id: 'p1', status: 'processing' });
  const topics = applyEvent(state, {
    event: 'alignment_ready',
    paper_id: 'p1',
    draft_paper_id: 'draft1',
    verdict: 'strengthens',
    score: 0.8,
  });
  const paper = state.papers.get('p1');
  assert.equal(paper.stance, 'strengthens');
  assert.equal(paper.score, 0.8);
  assert.ok(topics.includes('papers'));
});

test('section_tree_built and section_extracted handled without error', () => {
  const state = makeState();
  // Should not throw; sections events are acknowledged but may not affect state materially
  assert.doesNotThrow(() => {
    applyEvent(state, { event: 'section_tree_built', paper_id: 'p1', n_sections: 2 });
    applyEvent(state, {
      event: 'section_extracted',
      paper_id: 'p1',
      section_id: 's1',
      title: 'Introduction',
      counts: { concepts: 1 },
    });
  });
});

test('unknown event kind is ignored, returns []', () => {
  const state = makeState();
  const topics = applyEvent(state, { event: 'totally_unknown_kind', foo: 'bar' });
  assert.deepEqual(topics, []);
});

// --- Fixture replay test ---
test('fixture replay: final state correct', () => {
  const fixturePath = path.join(repoRoot, 'tests', 'fixtures', 'lab_events.jsonl');
  const lines = fs.readFileSync(fixturePath, 'utf8').trim().split('\n');
  const state = makeState();
  const allTopics = new Set();

  for (const line of lines) {
    const evt = JSON.parse(line);
    const topics = applyEvent(state, evt);
    topics.forEach(t => allTopics.add(t));
  }

  // 3 papers added
  assert.equal(state.papers.size, 3, 'should have 3 papers');

  // local:fixb should be failed with reason
  const fixb = state.papers.get('local:fixb');
  assert.ok(fixb, 'local:fixb should exist');
  assert.equal(fixb.status, 'failed', 'local:fixb should be failed');
  assert.ok(fixb.failure_reason, 'local:fixb should have failure_reason');

  // local:fixa should have strength set
  const fixa = state.papers.get('local:fixa');
  assert.ok(fixa, 'local:fixa should exist');
  assert.ok(fixa.strength, 'local:fixa should have strength');
  assert.equal(fixa.strength.band, 'moderate');

  // job_done should have been processed
  assert.ok(allTopics.has('jobs'), 'jobs topic should have been emitted');
  assert.ok(allTopics.has('papers'), 'papers topic should have been emitted');
});

// ---- W3-F1: suggestions_updated ----

test('suggestions_updated sets open count', () => {
  const state = makeState();
  state.suggestionCounts = { open: 0, by_severity: null };
  const topics = applyEvent(state, { event: 'suggestions_updated', open: 5 });
  assert.equal(state.suggestionCounts.open, 5);
  assert.ok(topics.includes('suggestions'));
});

test('suggestions_updated sets by_severity when present', () => {
  const state = makeState();
  state.suggestionCounts = { open: 0, by_severity: null };
  const topics = applyEvent(state, {
    event: 'suggestions_updated',
    open: 3,
    by_severity: { critical: 1, high: 2 },
  });
  assert.deepEqual(state.suggestionCounts.by_severity, { critical: 1, high: 2 });
  assert.equal(state.suggestionCounts.open, 3);
});

test('suggestions_updated sets by_severity null when absent', () => {
  const state = makeState();
  state.suggestionCounts = { open: 2, by_severity: { critical: 1 } };
  applyEvent(state, { event: 'suggestions_updated', open: 0 });
  assert.strictEqual(state.suggestionCounts.by_severity, null);
});

test('unknown event kind still returns [] after suggestions_updated added', () => {
  const state = makeState();
  state.suggestionCounts = { open: 0, by_severity: null };
  const topics = applyEvent(state, { event: 'completely_unknown', data: 'x' });
  assert.deepEqual(topics, []);
});

// ---- W5-C3: citation_coverage_updated ----

test('citation_coverage_updated: merges counts into state.citationCoverage', () => {
  const state = makeState();
  state.citationCoverage = null;
  const topics = applyEvent(state, {
    event: 'citation_coverage_updated',
    draft_paper_id: 'paper-1',
    total: 10,
    in_library: 4,
    available: 3,
    unchecked: 2,
    unresolved: 1,
    seq: 1,
  });
  assert.ok(state.citationCoverage, 'citationCoverage should be set');
  assert.equal(state.citationCoverage.counts.total, 10);
  assert.equal(state.citationCoverage.counts.in_library, 4);
  assert.equal(state.citationCoverage.counts.available, 3);
  assert.equal(state.citationCoverage.draft_paper_id, 'paper-1');
  assert.ok(topics.includes('citations'), 'should emit citations topic');
});

test('citation_coverage_updated: sets stale:true', () => {
  const state = makeState();
  state.citationCoverage = { counts: { total: 5, in_library: 5 }, stale: false };
  applyEvent(state, {
    event: 'citation_coverage_updated',
    draft_paper_id: 'paper-1',
    total: 8,
    in_library: 3,
    available: 2,
    unchecked: 2,
    unresolved: 1,
    seq: 2,
  });
  assert.ok(state.citationCoverage.stale, 'stale should be true after SSE update');
});

test('citation_coverage_updated: returns ["citations"]', () => {
  const state = makeState();
  state.citationCoverage = null;
  const topics = applyEvent(state, {
    event: 'citation_coverage_updated',
    draft_paper_id: 'p1',
    total: 2,
    in_library: 1,
    available: 1,
    unchecked: 0,
    unresolved: 0,
    seq: 1,
  });
  assert.deepEqual(topics, ['citations']);
});

// ---------------------------------------------------------------------------
// W5-ACT: job_started / job_finished
// ---------------------------------------------------------------------------

test('job_started: adds entry to state.activeJobs and returns ["activity"]', () => {
  const state = makeState();
  state.activeJobs = new Map();
  const topics = applyEvent(state, {
    event: 'job_started',
    job_id: 'abc123',
    kind: 'add',
    label: 'Downloading 1810.04805',
    target: '1810.04805',
    seq: 1,
  });
  assert.ok(topics.includes('activity'), 'should emit activity topic');
  assert.ok(state.activeJobs.has('abc123'), 'job should be in activeJobs');
  const job = state.activeJobs.get('abc123');
  assert.equal(job.kind, 'add');
  assert.equal(job.label, 'Downloading 1810.04805');
  assert.equal(job.target, '1810.04805');
});

test('job_finished: removes entry from state.activeJobs and returns ["activity"]', () => {
  const state = makeState();
  state.activeJobs = new Map();
  state.activeJobs.set('abc123', { kind: 'add', label: 'Downloading', target: '1810.04805' });
  const topics = applyEvent(state, {
    event: 'job_finished',
    job_id: 'abc123',
    kind: 'add',
    status: 'done',
    seq: 2,
  });
  assert.ok(topics.includes('activity'), 'should emit activity topic');
  assert.ok(!state.activeJobs.has('abc123'), 'job should be removed from activeJobs');
});

test('job_finished: unknown job_id does not crash', () => {
  const state = makeState();
  state.activeJobs = new Map();
  assert.doesNotThrow(() => {
    applyEvent(state, {
      event: 'job_finished',
      job_id: 'nonexistent',
      kind: 'add',
      status: 'done',
      seq: 1,
    });
  });
  assert.equal(state.activeJobs.size, 0);
});
