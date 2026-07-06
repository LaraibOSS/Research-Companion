/**
 * theme.test.mjs — Unit tests for theme.js pure functions.
 * Run: node --test tests/js/theme.test.mjs
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, '..', '..');
const { themeVars } = await import(
  pathToFileURL(path.join(repoRoot, 'research_companion', 'lab', 'static', 'js', 'theme.js')).href
);

test('themeVars returns defaults when settings is empty', () => {
  const v = themeVars({});
  assert.equal(v.theme, 'dark');
  assert.equal(v.accent, 'blue');
  assert.equal(v.density, 'comfortable');
});

test('themeVars returns defaults when settings is null', () => {
  const v = themeVars(null);
  assert.equal(v.theme, 'dark');
  assert.equal(v.accent, 'blue');
  assert.equal(v.density, 'comfortable');
});

test('themeVars uses settings values when present', () => {
  const v = themeVars({ theme: 'light', accent: 'teal', density: 'compact' });
  assert.equal(v.theme, 'light');
  assert.equal(v.accent, 'teal');
  assert.equal(v.density, 'compact');
});

test('themeVars uses partial settings with defaults for missing keys', () => {
  const v = themeVars({ accent: 'violet' });
  assert.equal(v.theme, 'dark');
  assert.equal(v.accent, 'violet');
  assert.equal(v.density, 'comfortable');
});

test('themeVars returns plain object with exactly theme/accent/density', () => {
  const v = themeVars({ theme: 'light' });
  assert.deepEqual(Object.keys(v).sort(), ['accent', 'density', 'theme']);
});
