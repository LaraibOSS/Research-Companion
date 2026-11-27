// Pure logic for the Agents page. The fixture is the real catalogue, generated
// by `research-companion agents --json` (see scripts/generate_agents_fixture.py),
// not hand-written rows.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const here = path.dirname(fileURLToPath(import.meta.url));
const {
  costLabel, expandSelection, groupByStage, lastResultLabel, refusalReasons, selectionSummary,
} = await import('../../research_companion/lab/static/js/agentsHelpers.js');

const AGENTS = JSON.parse(readFileSync(path.join(here, 'fixtures_agents.json'), 'utf8')).agents;
const titleOf = (name) => AGENTS.find((a) => a.name === name).title;

test('groups follow the stage order and lose no agent', () => {
  const groups = groupByStage(AGENTS);
  assert.deepEqual(groups.map((g) => g.stage),
    ['prepare', 'check', 'position', 'prioritise', 'respond']);
  assert.equal(groups.reduce((n, g) => n + g.agents.length, 0), AGENTS.length);
  assert.equal(groups[1].heading, 'Check the paper');
});

test('dependencies are added and named', () => {
  const s = selectionSummary(AGENTS, ['novelty'], { paperId: 'p', modelConfigured: true });
  assert.ok(s.willRun.includes('ingest') && s.willRun.includes('priorart'));
  assert.deepEqual([...s.added].sort(), [titleOf('ingest'), titleOf('priorart')].sort());
  assert.equal(s.usesModel, true);
  assert.match(s.costLine, /paid/);
  assert.equal(s.canRun, true);
});

test('a free selection says it is free', () => {
  const s = selectionSummary(AGENTS, ['statsoundness'], { paperId: 'p', modelConfigured: false });
  assert.equal(s.usesModel, false);
  assert.equal(s.canRun, true);
  assert.match(s.costLine, /^Free/);
});

test('every blocker is listed before the click', () => {
  const s = selectionSummary(AGENTS, ['novelty', 'compliance', 'problem'],
    { paperId: '', modelConfigured: false, inputs: {} });
  assert.equal(s.canRun, false);
  const text = s.blockers.join(' ');
  assert.match(text, /Choose a paper/);
  assert.match(text, /needs a venue/);
  assert.match(text, /needs a problem statement/);
  assert.match(text, /no model is set up/);
});

test('supplied inputs clear their blockers', () => {
  const s = selectionSummary(AGENTS, ['compliance', 'problem'], {
    paperId: 'p', modelConfigured: true,
    inputs: { venue: 'neurips', problem_statement: 'We study X.' },
  });
  assert.deepEqual(s.blockers, []);
  assert.deepEqual([...s.needs].sort(), ['problem statement', 'venue']);
});

test('an agent only the command line can run is blocked, not silently dropped', () => {
  const s = selectionSummary(AGENTS, ['rebuttal'], { paperId: 'p', modelConfigured: true });
  assert.equal(s.canRun, false);
  assert.match(s.blockers.join(' '), /command line/);
});

test('an empty selection cannot run', () => {
  assert.equal(selectionSummary(AGENTS, [], { paperId: 'p' }).canRun, false);
});

test('expandSelection ignores unknown names', () => {
  assert.deepEqual([...expandSelection(AGENTS, ['nope'])], []);
});

test('an unknown cost is never shown as free', () => {
  assert.equal(costLabel('free').text, 'Free');
  assert.equal(costLabel('model').tone, 'warn');
  assert.notEqual(costLabel('mystery').text, 'Free');
});

test('last results', () => {
  assert.equal(lastResultLabel(undefined).text, 'Not run yet');
  assert.equal(lastResultLabel({ state: 'done' }).tone, 'ok');
  const failed = lastResultLabel({ state: 'failed', error: ' timed out ' });
  assert.equal(failed.tone, 'fail');
  assert.equal(failed.detail, 'timed out');
});

test('a refusal lists every reason the server gave', () => {
  const err = new Error('x');
  err.detail = { problems: ['a', 'b'] };
  assert.deepEqual(refusalReasons(err), ['a', 'b']);
  assert.deepEqual(refusalReasons(new Error('plain')), ['plain']);
  assert.equal(refusalReasons(null).length, 1);
});

test('a finished agent shows what it found, not just "Done"', () => {
  assert.equal(lastResultLabel({ state: 'done', headline: '3 found, 0 not found, of 3 references.' }).text,
    '3 found, 0 not found, of 3 references.');
  assert.equal(lastResultLabel({ state: 'done', headline: null }).text, 'Done');
});
