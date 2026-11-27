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
  providerReady, isSelfHosted, PROVIDER_LABELS,
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

test('shouldShowWelcome stays dismissed even with no LLM key (the banner covers it)', () => {
  // It used to reappear on every load while no key was set, which made the
  // free checks feel locked behind a key.
  assert.equal(shouldShowWelcome(withKeys('anthropic', {}), { seen: true }), false);
  assert.equal(shouldShowWelcome(withKeys('anthropic', {}), { seen: false }), true);
});

test('shouldShowWelcome true on first launch when not seen', () => {
  assert.equal(shouldShowWelcome(withKeys('anthropic', { anthropic: true }), { seen: false }), true);
});

test('shouldShowWelcome false when keys set and already seen', () => {
  assert.equal(shouldShowWelcome(withKeys('anthropic', { anthropic: true }), { seen: true }), false);
});

// ---------------------------------------------------------------------------
// Self-hosted providers: "ready" is not "a key is set"
// ---------------------------------------------------------------------------

test('PROVIDER_LABELS names every backend provider in plain words', () => {
  assert.deepEqual(Object.keys(PROVIDER_LABELS).sort(),
    ['anthropic', 'ollama', 'openai', 'openai_compatible']);
  assert.equal(PROVIDER_LABELS.ollama, 'Local model (Ollama)');
  assert.equal(PROVIDER_LABELS.openai_compatible, 'Other OpenAI-compatible server');
});

test('activeKeyName: ollama uses no key; openai_compatible its optional key', () => {
  assert.equal(activeKeyName({ provider: 'ollama' }), null);
  assert.equal(activeKeyName({ provider: 'openai_compatible' }), 'openai_compatible_api_key');
  assert.ok(isSelfHosted('ollama') && isSelfHosted('openai_compatible'));
  assert.ok(!isSelfHosted('anthropic'));
});

test('providerReady trusts the backend flag over key presence', () => {
  // Ollama with a model set: no key anywhere, still ready.
  assert.equal(providerReady({ provider: 'ollama', keys: {}, provider_ready: true }), true);
  assert.equal(missingLlmKey({ provider: 'ollama', keys: {}, provider_ready: true }), false);
  // Anthropic key present but the backend says not ready: not ready.
  const s = withKeys('anthropic', { anthropic: true });
  assert.equal(providerReady({ ...s, provider_ready: false }), false);
});

test('providerReady without the flag falls back to the key, and ollama is not ready', () => {
  assert.equal(providerReady(withKeys('openai', { openai: true })), true);
  assert.equal(providerReady({ provider: 'ollama', keys: {} }), false);
});

test('no-key banner hides for a ready local model', () => {
  const m = noKeyBannerModel({ provider: 'ollama', provider_ready: true,
    keys: { hf_token: { set: true } } });
  assert.equal(m.visible, false);
});
