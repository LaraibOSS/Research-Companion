// The Home research path: five stages and one next step.
//
// Every case below is a real snapshot of the Lab's endpoints, recorded by
// scripts/generate_home_path_fixtures.py while it builds a throwaway research
// step by step. Hand-written payloads would only test what we assume the
// endpoints return.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const here = path.dirname(fileURLToPath(import.meta.url));
const { researchPath, pathFacts, STAGES, STATUS_TEXT } =
  await import('../../research_companion/lab/static/js/pathHelpers.js');

const CASES = JSON.parse(readFileSync(path.join(here, 'fixtures_home_path.json'), 'utf8'));

const MODEL = { provider_ready: true };
const NO_MODEL = { provider_ready: false };

/** Build the helper's input from a recorded case, the way home.js does. */
function inputFor(name, settings = MODEL, overrides = {}) {
  const c = CASES[name];
  const papers = new Map(c.papers.map((p) => [p.paper_id, p]));
  return {
    papers, draftId: c.lab.draft_id, settings,
    lab: c.lab, gaps: c.gaps, brainstorm: c.brainstorm, agents: c.agents,
    ...overrides,
  };
}

const statusOf = (res) => Object.fromEntries(res.stages.map((s) => [s.key, s.status]));

// ---------------------------------------------------------------------------
// Shape
// ---------------------------------------------------------------------------

test('five stages, in the documented order, each with a status word and a reason', () => {
  const res = researchPath(inputFor('understood'));
  assert.deepEqual(res.stages.map((s) => s.title),
    ['Collect', 'Understand', 'Find your angle', 'Write', 'Check']);
  assert.deepEqual(STAGES.map((s) => s.key), res.stages.map((s) => s.key));
  for (const s of res.stages) {
    assert.equal(s.statusText, STATUS_TEXT[s.status]);
    assert.ok(s.reason.length > 0, `${s.key} has no reason`);
  }
});

test('at most one stage is current, and it is the one the helper names', () => {
  for (const name of Object.keys(CASES)) {
    for (const settings of [MODEL, NO_MODEL]) {
      const res = researchPath(inputFor(name, settings));
      const current = res.stages.filter((s) => s.status === 'current');
      assert.ok(current.length <= 1, name);
      assert.equal(current.length ? current[0].key : null, res.current, name);
    }
  }
});

test('every case yields exactly one next step with a cost and a target', () => {
  for (const name of Object.keys(CASES)) {
    for (const settings of [MODEL, NO_MODEL]) {
      const { next } = researchPath(inputFor(name, settings));
      assert.ok(next.title && next.what && next.costText && next.button, name);
      assert.ok(['free', 'network', 'model'].includes(next.cost), name);
      assert.ok(next.route || next.action, `${name}: step goes nowhere`);
      assert.ok(!(next.route && next.action), `${name}: step has two targets`);
      // No invented call counts.
      assert.doesNotMatch(next.costText, /\d/, `${name}: cost states a number`);
    }
  }
});

// ---------------------------------------------------------------------------
// Stage transitions, one recorded step at a time
// ---------------------------------------------------------------------------

test('empty research: Collect is current, the step is to add papers', () => {
  const res = researchPath(inputFor('empty'));
  assert.deepEqual(statusOf(res), {
    collect: 'current', understand: 'not_started', angle: 'not_started',
    write: 'not_started', check: 'not_started',
  });
  assert.equal(res.next.id, 'add-papers');
  assert.equal(res.next.action, 'open-ingest');
  assert.equal(res.stages[0].reason, 'No papers in your library yet.');
});

test('papers added but unread: Collect done, Understand current', () => {
  const res = researchPath(inputFor('collected_unread'));
  assert.equal(statusOf(res).collect, 'done');
  assert.equal(res.current, 'understand');
  assert.equal(res.stages[0].reason, '2 papers in your library.');
  assert.match(res.stages[1].reason, /None of your 2 papers has been read yet\. 1 paper could not be read\./);
  assert.equal(res.next.id, 'read-papers');
  assert.equal(res.next.route, '#/library');
  assert.equal(res.next.cost, 'model');
});

test('a paper read but the graph still empty is NOT understood', () => {
  const res = researchPath(inputFor('read_no_graph'));
  assert.equal(statusOf(res).understand, 'current');
  assert.match(res.stages[1].reason, /1 of 2 papers read, but the concept graph is empty/);
  assert.equal(res.next.id, 'open-graph');
});

test('read and mapped: Understand done, Find your angle current', () => {
  const res = researchPath(inputFor('understood'));
  assert.equal(statusOf(res).understand, 'done');
  assert.equal(res.current, 'angle');
  assert.equal(res.next.id, 'find-gaps');
  assert.equal(res.next.route, '#/gaps');
  assert.match(res.next.costText, /only when you click Refresh gaps/);
});

test('per-paper gaps that were never grouped do not finish Find your angle', () => {
  const res = researchPath(inputFor('gaps_unthemed'));
  assert.equal(statusOf(res).angle, 'current');
  assert.match(res.stages[2].reason, /1 open problem found in your papers, not yet grouped/);
});

test('gap themes finish Find your angle; Write becomes current', () => {
  const res = researchPath(inputFor('gaps_themed'));
  assert.equal(statusOf(res).angle, 'done');
  assert.equal(res.stages[2].reason, '1 gap theme.');
  assert.equal(res.current, 'write');
  assert.equal(res.next.id, 'add-draft');
  assert.equal(res.next.action, 'open-ingest-draft');
});

test('generated directions also finish Find your angle', () => {
  const res = researchPath(inputFor('directions', MODEL, {
    gaps: { ...CASES.directions.gaps, themes: [] },
  }));
  assert.equal(statusOf(res).angle, 'done');
  assert.equal(res.stages[2].reason, '1 research direction.');
});

test('a draft that has not been read does not finish Write', () => {
  const res = researchPath(inputFor('draft_unread'));
  assert.equal(statusOf(res).write, 'current');
  assert.equal(res.stages[3].reason, 'Your draft has been added but not read yet.');
  assert.equal(res.next.id, 'read-draft');
});

test('with a draft set, Find your angle is optional and never current', () => {
  // In the recorded state, adding the draft made the cached themes stale, so
  // GET /api/gaps returns none. Strip the directions too: the angle stage is
  // not done, and still Write — not Find your angle — is current.
  const res = researchPath(inputFor('draft_unread', MODEL, { brainstorm: { session: null } }));
  assert.equal(statusOf(res).angle, 'not_started');
  assert.equal(res.current, 'write');
  assert.match(res.stages[2].reason, /Optional once you have a draft\./);
});

test('draft read, no checks: Check current, the step is the free checks', () => {
  const res = researchPath(inputFor('draft_read'));
  assert.equal(statusOf(res).write, 'done');
  assert.equal(res.current, 'check');
  assert.equal(res.next.id, 'run-free-checks');
  assert.equal(res.next.route, '#/agents');
  assert.equal(res.next.cost, 'network');
});

test('the Reader alone checks nothing: Check is not done', () => {
  const res = researchPath(inputFor('draft_reader_only'));
  assert.equal(statusOf(res).check, 'current');
  assert.match(res.stages[4].reason, /No check has completed/);
});

test('a failed check is not a completed one', () => {
  const res = researchPath(inputFor('draft_check_failed'));
  assert.equal(statusOf(res).check, 'current');
  assert.match(res.stages[4].reason, /1 check failed\./);
  assert.match(res.next.what, /A check failed last time/);
});

test('a completed check finishes the path; the step is to review it', () => {
  const res = researchPath(inputFor('draft_checked'));
  assert.equal(statusOf(res).check, 'done');
  assert.equal(res.stages[4].reason, '1 check has run on this draft.');
  assert.equal(res.current, null);
  assert.equal(res.next.id, 'review-checks');
  assert.equal(res.next.cost, 'free');
});

test('a scaffolded outline is reported done by the API but is not a written draft', () => {
  const c = CASES.draft_read;
  const papers = c.papers.map((p) => (p.is_draft ? { ...p, parse_source: 'scaffold' } : p));
  const res = researchPath(inputFor('draft_read', MODEL, {
    papers: new Map(papers.map((p) => [p.paper_id, p])),
  }));
  assert.equal(statusOf(res).write, 'current');
  assert.equal(statusOf(res).check, 'not_started');
  assert.equal(res.next.id, 'write-draft');
});

test('a draft that failed to read sends the person to Library, free', () => {
  const c = CASES.draft_unread;
  const papers = c.papers.map((p) => (p.is_draft ? { ...p, status: 'failed' } : p));
  const res = researchPath(inputFor('draft_unread', MODEL, {
    papers: new Map(papers.map((p) => [p.paper_id, p])),
  }));
  assert.equal(res.stages[3].reason, 'Your draft could not be read.');
  assert.equal(res.next.id, 'fix-draft');
  assert.equal(res.next.cost, 'free');
});

// ---------------------------------------------------------------------------
// No model configured: free first, and say what a model would add
// ---------------------------------------------------------------------------

test('no model, empty: adding papers is free, and the step says what a model adds', () => {
  const { next } = researchPath(inputFor('empty', NO_MODEL));
  assert.equal(next.id, 'add-papers');
  assert.equal(next.cost, 'free');
  assert.match(next.costText, /stored but not read/);
  assert.match(next.withModel, /With a model/);
});

test('no model, read draft, unread library: the free checks come before connecting a model', () => {
  const c = CASES.draft_read;
  const papers = c.papers.map((p) => (p.is_draft ? p : { ...p, status: 'pending' }));
  const res = researchPath(inputFor('draft_read', NO_MODEL, {
    papers: new Map(papers.map((p) => [p.paper_id, p])),
  }));
  assert.equal(res.current, 'understand');
  assert.equal(res.next.id, 'run-free-checks');
  assert.notEqual(res.next.cost, 'model');
  assert.match(res.next.withModel, /With a model/);
});

test('no model and nothing free can move the path: connect one, which is free to do', () => {
  const { next } = researchPath(inputFor('collected_unread', NO_MODEL));
  assert.equal(next.id, 'connect-model');
  assert.equal(next.route, '#/settings');
  assert.equal(next.cost, 'free');
});

test('no model at Find your angle: explore the graph for free instead of a paid step', () => {
  const { next } = researchPath(inputFor('understood', NO_MODEL));
  assert.equal(next.id, 'explore-graph');
  assert.equal(next.cost, 'free');
  assert.match(next.withModel, /Gaps groups/);
});

test('no model, draft read: the free checks are the step', () => {
  const { next } = researchPath(inputFor('draft_read', NO_MODEL));
  assert.equal(next.id, 'run-free-checks');
});

test('no step is a paid one when no model is configured', () => {
  for (const name of Object.keys(CASES)) {
    const { next } = researchPath(inputFor(name, NO_MODEL));
    assert.notEqual(next.cost, 'model', name);
  }
});

test('with a model, the "what a model adds" note is not shown', () => {
  for (const name of Object.keys(CASES)) {
    assert.equal(researchPath(inputFor(name, MODEL)).next.withModel, '', name);
  }
});

// ---------------------------------------------------------------------------
// Never done on weak or missing evidence
// ---------------------------------------------------------------------------

test('an unloaded graph count never makes Understand done', () => {
  const res = researchPath(inputFor('understood', MODEL, { lab: null }));
  assert.equal(statusOf(res).understand, 'current');
  assert.match(res.stages[1].reason, /has not been checked yet/);
});

test('unloaded gaps and brainstorm never make Find your angle done', () => {
  const res = researchPath(inputFor('gaps_themed', MODEL, { gaps: null, brainstorm: null }));
  assert.equal(statusOf(res).angle, 'current');
  assert.equal(res.stages[2].reason, 'Not checked yet.');
});

test('unloaded agent results never make Check done', () => {
  const res = researchPath(inputFor('draft_checked', MODEL, { agents: null }));
  assert.equal(statusOf(res).check, 'current');
  assert.match(res.stages[4].reason, /have not been loaded/);
});

test('a draft id the library does not hold is not a draft', () => {
  const res = researchPath(inputFor('understood', MODEL, { draftId: 'local:gone' }));
  assert.equal(statusOf(res).write, 'current');
  assert.match(res.stages[3].reason, /not in its library/);
  assert.equal(res.next.id, 'add-draft');
});

test('the draft is never counted as a library paper', () => {
  const f = pathFacts(inputFor('draft_read'));
  assert.equal(f.papers, 2);
  assert.equal(f.read, 1);
});

// ---------------------------------------------------------------------------
// Malformed and empty input
// ---------------------------------------------------------------------------

test('malformed input never throws and never claims a stage', () => {
  const junk = [
    undefined, null, 42, 'x', [],
    { papers: 'nope', lab: [], gaps: 'x', brainstorm: 7, agents: { agents: 'x' } },
    { papers: [null, 3, { title: 'no id' }], lab: { node_count: 'many' } },
    { papers: new Map([['a', null]]), gaps: { themes: 'x', papers: [null, { gaps: 'y' }] } },
    { agents: { agents: [null, { stage: 'check', last: 'done' }] }, draftId: 5 },
  ];
  for (const input of junk) {
    const res = researchPath(input);
    assert.equal(res.stages.length, 5);
    assert.ok(res.stages.every((s) => s.status !== 'done'), JSON.stringify(input));
    assert.equal(res.current, 'collect');
    assert.equal(res.next.id, 'add-papers');
    assert.equal(res.modelReady, false);
  }
});

test('papers may be passed as an array as well as a Map', () => {
  const c = CASES.understood;
  const res = researchPath({ ...inputFor('understood'), papers: c.papers });
  assert.equal(statusOf(res).understand, 'done');
});
