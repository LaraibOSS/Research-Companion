/**
 * keyPromptHelpers.js — Pure helpers for the API-key onboarding prompt.
 *
 * Decides (a) whether the active LLM provider key is missing (blocks analysis),
 * (b) whether the optional Hugging Face token is missing (degrades semantic
 * search), (c) the no-key banner's message/tone, and (d) whether the first-run
 * welcome dialog should be shown.
 *
 * No DOM access — node-testable.
 */

const WELCOME_SEEN_KEY = 'rc.welcomeShown';

/** Plain labels for every provider the backend accepts (settings._VALID_PROVIDERS). */
export const PROVIDER_LABELS = {
  anthropic: 'Anthropic',
  openai: 'OpenAI',
  ollama: 'Local model (Ollama)',
  openai_compatible: 'Other OpenAI-compatible server',
};

/** Providers that run on the user's own machine or server (no default model). */
const SELF_HOSTED = new Set(['ollama', 'openai_compatible']);

export function isSelfHosted(provider) {
  return SELF_HOSTED.has(provider);
}

/**
 * Name of the secret key the currently-selected provider uses, or null when
 * it uses none (Ollama). For openai_compatible the key is optional.
 */
export function activeKeyName(settings) {
  const provider = (settings && settings.provider) || 'anthropic';
  if (provider === 'openai') return 'openai_api_key';
  if (provider === 'openai_compatible') return 'openai_compatible_api_key';
  if (provider === 'ollama') return null;
  return 'anthropic_api_key';
}

function _keySet(settings, name) {
  const keys = (settings && settings.keys) || {};
  return !!(keys[name] && keys[name].set);
}

/**
 * True when the selected provider has what it needs to make a call.
 * The backend computes this (settings.provider_ready, from llm.provider_ready)
 * because "ready" is not "a key is set" for every provider: Ollama needs no
 * key but needs a model name. The key check is only the fallback for a
 * payload without the flag.
 */
export function providerReady(settings) {
  if (!settings) return false;
  if (typeof settings.provider_ready === 'boolean') return settings.provider_ready;
  const name = activeKeyName(settings);
  return name ? _keySet(settings, name) : false;
}

/** True when the active provider is not ready to make a call (analysis is blocked). */
export function missingLlmKey(settings) {
  if (!settings || !settings.keys) return false; // unknown yet — don't nag
  return !providerReady(settings);
}

/** True when the optional Hugging Face token is not set. */
export function missingHfToken(settings) {
  if (!settings || !settings.keys) return false;
  return !_keySet(settings, 'hf_token');
}

/**
 * Model for the persistent top banner.
 * - LLM missing  -> blocking amber message (highest priority).
 * - else HF only -> softer, optional message.
 * - else         -> hidden.
 */
export function noKeyBannerModel(settings) {
  if (missingLlmKey(settings)) {
    return {
      visible: true,
      tone: 'block',
      message: 'Connect a model to unlock analysis',
      linkText: 'Settings',
    };
  }
  if (missingHfToken(settings)) {
    return {
      visible: true,
      tone: 'soft',
      message: 'Add a Hugging Face token for better semantic search (optional)',
      linkText: 'Settings',
    };
  }
  return { visible: false, tone: 'none', message: '', linkText: 'Settings' };
}

/**
 * Whether to show the first-launch welcome dialog: once, then never again
 * once dismissed. Never before settings have loaded (settings.keys absent).
 *
 * It used to reappear on every page load while no model key was set. That
 * made the free checks feel locked behind a key, and the persistent
 * "Connect a model" banner (noKeyBannerModel) already covers a missing key.
 */
export function shouldShowWelcome(settings, { seen } = {}) {
  if (!settings || !settings.keys) return false;
  return !seen;
}

export { WELCOME_SEEN_KEY };
