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

/** Name of the secret key required by the currently-selected provider. */
export function activeKeyName(settings) {
  const provider = (settings && settings.provider) || 'anthropic';
  return provider === 'openai' ? 'openai_api_key' : 'anthropic_api_key';
}

function _keySet(settings, name) {
  const keys = (settings && settings.keys) || {};
  return !!(keys[name] && keys[name].set);
}

/** True when the active provider's LLM key is not set (analysis is blocked). */
export function missingLlmKey(settings) {
  if (!settings || !settings.keys) return false; // unknown yet — don't nag
  return !_keySet(settings, activeKeyName(settings));
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
 * Whether to show the first-launch welcome dialog.
 * Shows when the LLM key is missing, OR on the very first launch (seen flag
 * not yet persisted) so new users always see the "get set up" guidance once.
 * Never shows before settings have loaded (settings.keys absent).
 */
export function shouldShowWelcome(settings, { seen } = {}) {
  if (!settings || !settings.keys) return false;
  if (missingLlmKey(settings)) return true;
  return !seen;
}

export { WELCOME_SEEN_KEY };
