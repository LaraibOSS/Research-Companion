/**
 * activityHelpers.test.mjs — TDD tests for pure activity helper functions.
 * Run from repo root: node --test tests/js/
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot  = path.resolve(__dirname, '..', '..');

const { activitySummary, citationDownloadTargets, isResolving } = await import(
  pathToFileURL(path.join(repoRoot, 'research_companion', 'lab', 'static', 'js', 'activityHelpers.js')).href
);

// ---------------------------------------------------------------------------
// activitySummary
// ---------------------------------------------------------------------------

test('activitySummary: null -> {count:0, label:""}', () => {
  const result = activitySummary(null);
  assert.equal(result.count, 0);
  assert.equal(result.label, '');
});

test('activitySummary: empty Map -> {count:0, label:""}', () => {
  const result = activitySummary(new Map());
  assert.equal(result.count, 0);
  assert.equal(result.label, '');
});

test('activitySummary: single job -> {count:1, label: job label}', () => {
  const jobs = new Map();
  jobs.set('job-1', { kind: 'add', label: 'Downloading 1810.04805', target: '1810.04805' });
  const result = activitySummary(jobs);
  assert.equal(result.count, 1);
  assert.equal(result.label, 'Downloading 1810.04805');
});

test('activitySummary: multiple jobs -> {count: N, label: "N tasks running"}', () => {
  const jobs = new Map();
  jobs.set('job-1', { kind: 'add', label: 'Downloading 1810.04805', target: '1810.04805' });
  jobs.set('job-2', { kind: 'citations', label: 'Checking references…', target: '' });
  jobs.set('job-3', { kind: 'gaps', label: 'Analyzing gaps…', target: '' });
  const result = activitySummary(jobs);
  assert.equal(result.count, 3);
  assert.equal(result.label, '3 tasks running');
});

test('activitySummary: two jobs -> "2 tasks running"', () => {
  const jobs = new Map();
  jobs.set('j1', { kind: 'ingest', label: 'Ingesting folder (12 PDFs)…', target: '' });
  jobs.set('j2', { kind: 'add', label: 'Downloading xyz', target: 'xyz' });
  const result = activitySummary(jobs);
  assert.equal(result.count, 2);
  assert.equal(result.label, '2 tasks running');
});

// ---------------------------------------------------------------------------
// citationDownloadTargets
// ---------------------------------------------------------------------------

test('citationDownloadTargets: null -> empty Set', () => {
  const result = citationDownloadTargets(null);
  assert.ok(result instanceof Set);
  assert.equal(result.size, 0);
});

test('citationDownloadTargets: empty Map -> empty Set', () => {
  const result = citationDownloadTargets(new Map());
  assert.equal(result.size, 0);
});

test('citationDownloadTargets: only kind=add with non-empty target -> included', () => {
  const jobs = new Map();
  jobs.set('j1', { kind: 'add', label: 'Downloading 1810.04805', target: '1810.04805' });
  jobs.set('j2', { kind: 'add', label: 'Downloading xyz', target: 'xyz/doi' });
  const result = citationDownloadTargets(jobs);
  assert.equal(result.size, 2);
  assert.ok(result.has('1810.04805'));
  assert.ok(result.has('xyz/doi'));
});

test('citationDownloadTargets: kind=add with empty target -> excluded', () => {
  const jobs = new Map();
  jobs.set('j1', { kind: 'add', label: 'Adding...', target: '' });
  const result = citationDownloadTargets(jobs);
  assert.equal(result.size, 0);
});

test('citationDownloadTargets: non-add kinds -> excluded', () => {
  const jobs = new Map();
  jobs.set('j1', { kind: 'citations', label: 'Checking…', target: 'some-target' });
  jobs.set('j2', { kind: 'gaps', label: 'Analyzing…', target: 'gap-target' });
  jobs.set('j3', { kind: 'ingest', label: 'Ingesting…', target: 'file.pdf' });
  const result = citationDownloadTargets(jobs);
  assert.equal(result.size, 0);
});

test('citationDownloadTargets: mixed kinds -> only add with non-empty target', () => {
  const jobs = new Map();
  jobs.set('j1', { kind: 'add', label: 'Downloading 1810.04805', target: '1810.04805' });
  jobs.set('j2', { kind: 'citations', label: 'Checking references…', target: '' });
  jobs.set('j3', { kind: 'add', label: 'Adding...', target: '' });
  const result = citationDownloadTargets(jobs);
  assert.equal(result.size, 1);
  assert.ok(result.has('1810.04805'));
});

// ---------------------------------------------------------------------------
// isResolving
// ---------------------------------------------------------------------------

test('isResolving: null -> false', () => {
  assert.equal(isResolving(null), false);
});

test('isResolving: empty Map -> false', () => {
  assert.equal(isResolving(new Map()), false);
});

test('isResolving: no citations kind -> false', () => {
  const jobs = new Map();
  jobs.set('j1', { kind: 'add', label: 'Downloading', target: '1234' });
  jobs.set('j2', { kind: 'gaps', label: 'Analyzing gaps…', target: '' });
  assert.equal(isResolving(jobs), false);
});

test('isResolving: has citations kind -> true', () => {
  const jobs = new Map();
  jobs.set('j1', { kind: 'citations', label: 'Checking references…', target: '' });
  assert.equal(isResolving(jobs), true);
});

test('isResolving: mixed jobs with one citations -> true', () => {
  const jobs = new Map();
  jobs.set('j1', { kind: 'add', label: 'Downloading', target: '1234' });
  jobs.set('j2', { kind: 'citations', label: 'Checking references…', target: '' });
  assert.equal(isResolving(jobs), true);
});
