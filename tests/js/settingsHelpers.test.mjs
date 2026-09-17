/**
 * settingsHelpers.test.mjs — Unit tests for settingsHelpers.js pure functions.
 * Run: node --test tests/js/settingsHelpers.test.mjs
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, '..', '..');
const { buildSettingsPatch, validateSettings } = await import(
  pathToFileURL(path.join(repoRoot, 'research_companion', 'lab', 'static', 'js', 'settingsHelpers.js')).href
);

// ---- buildSettingsPatch ----

test('buildSettingsPatch returns empty object when nothing changed', () => {
  const original = { provider: 'anthropic', model: 'claude-3-5-sonnet', theme: 'dark', accent: 'blue', density: 'comfortable', k_sections: 6, char_budget: 8000 };
  const formState = { ...original, anthropic_api_key: '', openai_api_key: '', hf_token: '' };
  const patch = buildSettingsPatch(formState, original);
  assert.deepEqual(patch, {});
});

test('buildSettingsPatch includes only changed non-secret fields', () => {
  const original = { provider: 'anthropic', theme: 'dark', accent: 'blue', density: 'comfortable', k_sections: 6, char_budget: 8000 };
  const formState = { provider: 'openai', theme: 'dark', accent: 'blue', density: 'comfortable', k_sections: 6, char_budget: 8000, anthropic_api_key: '', openai_api_key: '', hf_token: '' };
  const patch = buildSettingsPatch(formState, original);
  assert.equal(patch.provider, 'openai');
  assert.ok(!('theme' in patch), 'unchanged theme should not be in patch');
});

test('buildSettingsPatch omits empty-string secret fields', () => {
  const original = { provider: 'anthropic' };
  const formState = { provider: 'anthropic', anthropic_api_key: '', openai_api_key: '', hf_token: '' };
  const patch = buildSettingsPatch(formState, original);
  assert.ok(!('keys' in patch), 'empty secrets should not produce a keys block');
});

test('buildSettingsPatch includes non-empty secret fields in keys block', () => {
  const original = { provider: 'anthropic' };
  const formState = { provider: 'anthropic', anthropic_api_key: 'sk-abc123', openai_api_key: '', hf_token: '' };
  const patch = buildSettingsPatch(formState, original);
  assert.ok('keys' in patch, 'keys block should exist');
  assert.equal(patch.keys.anthropic_api_key, 'sk-abc123');
  assert.ok(!('openai_api_key' in patch.keys), 'empty openai key should not appear');
});

test('buildSettingsPatch includes explicit null for clear action', () => {
  // formState encodes "clear this key" as the special sentinel null
  const original = { provider: 'anthropic' };
  const formState = { provider: 'anthropic', anthropic_api_key: null, openai_api_key: '', hf_token: '' };
  const patch = buildSettingsPatch(formState, original);
  assert.ok('keys' in patch, 'keys block should exist for explicit null');
  assert.strictEqual(patch.keys.anthropic_api_key, null);
});

test('buildSettingsPatch detects theme change', () => {
  const original = { theme: 'dark', accent: 'blue', density: 'comfortable' };
  const formState = { theme: 'light', accent: 'blue', density: 'comfortable', anthropic_api_key: '', openai_api_key: '', hf_token: '' };
  const patch = buildSettingsPatch(formState, original);
  assert.equal(patch.theme, 'light');
  assert.ok(!('accent' in patch));
  assert.ok(!('density' in patch));
});

// ---- validateSettings ----

test('validateSettings returns [] for valid patch', () => {
  const errors = validateSettings({ k_sections: 10, char_budget: 5000 });
  assert.deepEqual(errors, []);
});

test('validateSettings catches k_sections below 1', () => {
  const errors = validateSettings({ k_sections: 0 });
  assert.ok(errors.length > 0, 'should have error');
  assert.ok(errors[0].includes('k_sections'));
});

test('validateSettings catches k_sections above 20', () => {
  const errors = validateSettings({ k_sections: 21 });
  assert.ok(errors.length > 0);
  assert.ok(errors[0].includes('k_sections'));
});

test('validateSettings catches char_budget below 1000', () => {
  const errors = validateSettings({ char_budget: 500 });
  assert.ok(errors.length > 0);
  assert.ok(errors[0].includes('char_budget'));
});

test('validateSettings catches char_budget above 50000', () => {
  const errors = validateSettings({ char_budget: 60000 });
  assert.ok(errors.length > 0);
  assert.ok(errors[0].includes('char_budget'));
});

test('validateSettings returns [] for empty patch', () => {
  const errors = validateSettings({});
  assert.deepEqual(errors, []);
});

test('buildSettingsPatch carries downloads_dir', () => {
  // Spec 7.6: one setting, detected, shown, EDITABLE. Missing from
  // REGULAR_FIELDS it was silently dropped from every PUT.
  const patch = buildSettingsPatch(
    { downloads_dir: 'D:/Downloads', anthropic_api_key: '', openai_api_key: '', hf_token: '' },
    { downloads_dir: '' });
  assert.deepEqual(patch, { downloads_dir: 'D:/Downloads' });
});
