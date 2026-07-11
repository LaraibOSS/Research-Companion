/**
 * keyPromptHelpers.test.mjs — Unit tests for keyPromptHelpers.js pure functions.
 * Run: node --test tests/js/keyPromptHelpers.test.mjs
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, '..', '..');
const {
  activeKeyName, missingLlmKey, missingHfToken, noKeyBannerModel, shouldShowWelcome,
} = await import(
  pathToFileURL(path.join(repoRoot, 'research_companion', 'lab', 'static', 'js', 'keyPromptHelpers.js')).href
);

const withKeys = (provider, set) => ({
  provider,
  keys: {
    anthropic_api_key: { set: !!set.anthropic },
    openai_api_key: { set: !!set.openai },
    hf_token: { set: !!set.hf },
  },
});

// ---- activeKeyName ----

test('activeKeyName defaults to anthropic', () => {
  assert.equal(activeKeyName({}), 'anthropic_api_key');
  assert.equal(activeKeyName({ provider: 'anthropic' }), 'anthropic_api_key');
});

test('activeKeyName picks openai when provider is openai', () => {
  assert.equal(activeKeyName({ provider: 'openai' }), 'openai_api_key');
});

// ---- missingLlmKey ----

test('missingLlmKey false before settings loaded', () => {
  assert.equal(missingLlmKey(null), false);
  assert.equal(missingLlmKey({}), false);
});

test('missingLlmKey true when active provider key not set', () => {
  assert.equal(missingLlmKey(withKeys('anthropic', {})), true);
  assert.equal(missingLlmKey(withKeys('anthropic', { anthropic: true })), false);
});

test('missingLlmKey follows provider selection', () => {
  // Anthropic set but provider is openai -> still missing.
  assert.equal(missingLlmKey(withKeys('openai', { anthropic: true })), true);
  assert.equal(missingLlmKey(withKeys('openai', { openai: true })), false);
});

// ---- missingHfToken ----

test('missingHfToken reflects hf_token.set', () => {
  assert.equal(missingHfToken(withKeys('anthropic', {})), true);
  assert.equal(missingHfToken(withKeys('anthropic', { hf: true })), false);
});

// ---- noKeyBannerModel ----

test('noKeyBannerModel blocks (amber) when LLM key missing', () => {
  const m = noKeyBannerModel(withKeys('anthropic', { hf: true }));
  assert.equal(m.visible, true);
  assert.equal(m.tone, 'block');
  assert.match(m.message, /unlock analysis/i);
});

test('noKeyBannerModel soft when only HF missing', () => {
  const m = noKeyBannerModel(withKeys('anthropic', { anthropic: true }));
  assert.equal(m.visible, true);
  assert.equal(m.tone, 'soft');
  assert.match(m.message, /hugging face/i);
});

test('noKeyBannerModel hidden when all keys present', () => {
  const m = noKeyBannerModel(withKeys('anthropic', { anthropic: true, hf: true }));
  assert.equal(m.visible, false);
});

// ---- shouldShowWelcome ----

test('shouldShowWelcome false before settings loaded', () => {
  assert.equal(shouldShowWelcome(null, { seen: false }), false);
});

test('shouldShowWelcome true when LLM key missing (even if seen)', () => {
  assert.equal(shouldShowWelcome(withKeys('anthropic', {}), { seen: true }), true);
});

test('shouldShowWelcome true on first launch when not seen', () => {
  assert.equal(shouldShowWelcome(withKeys('anthropic', { anthropic: true }), { seen: false }), true);
});

test('shouldShowWelcome false when keys set and already seen', () => {
  assert.equal(shouldShowWelcome(withKeys('anthropic', { anthropic: true }), { seen: true }), false);
});
