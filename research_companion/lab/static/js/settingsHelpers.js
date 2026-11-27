/**
 * settingsHelpers.js — Pure helpers for the Settings view.
 *
 * buildSettingsPatch: compute minimal PUT body from form state vs. original.
 * validateSettings: client-side validation mirroring server rules.
 *
 * No DOM access — node-testable.
 * W3-F1.
 */

/** Fields treated as secrets (live in keys block of PUT body). */
const SECRET_FIELDS = ['anthropic_api_key', 'openai_api_key', 'openai_compatible_api_key', 'hf_token'];

/**
 * Non-secret fields that can appear at the top level of a PUT body.
 * A field missing here is silently dropped from every save.
 */
const REGULAR_FIELDS = [
  'provider', 'model', 'theme', 'accent', 'density', 'k_sections', 'char_budget', 'embed_model',
  'contact_email', 'downloads_dir', 'base_url', 'ollama_url', 'ollama_num_ctx',
];

/** Ollama context-length bounds, mirroring settings.py. */
export const OLLAMA_NUM_CTX_MIN = 2048;
export const OLLAMA_NUM_CTX_MAX = 1048576;

/**
 * Which Model Provider fields the Settings card shows for a provider.
 * Hosted providers show their own key; the self-hosted ones show their
 * server fields and require a model name (they have no default model).
 *
 * @param {string} provider
 * @returns {{anthropicKey:boolean, openaiKey:boolean, baseUrl:boolean,
 *            compatKey:boolean, ollamaUrl:boolean, ollamaNumCtx:boolean,
 *            modelRequired:boolean}}
 */
export function providerFields(provider) {
  return {
    anthropicKey: provider === 'anthropic' || !provider,
    openaiKey: provider === 'openai',
    baseUrl: provider === 'openai_compatible',
    compatKey: provider === 'openai_compatible',
    ollamaUrl: provider === 'ollama',
    ollamaNumCtx: provider === 'ollama',
    modelRequired: provider === 'ollama' || provider === 'openai_compatible',
  };
}

/** "" or an http(s) URL with a host — the same rule settings.py enforces. */
export function isHttpUrlOrEmpty(value) {
  if (value === '' || value === null || value === undefined) return true;
  try {
    const u = new URL(String(value));
    return (u.protocol === 'http:' || u.protocol === 'https:') && !!u.host;
  } catch {
    return false;
  }
}

/**
 * Build a minimal PUT /api/settings body from form state compared to original.
 *
 * Rules:
 * - Only include regular fields that changed vs. original.
 * - Secret fields: include in `keys` block ONLY if non-empty string OR explicit null.
 * - Empty string for a secret field -> omit entirely (server rejects "").
 * - null for a secret field -> include as null (server deletes the key).
 *
 * @param {object} formState  — { provider, model, theme, accent, density, k_sections, char_budget, contact_email, anthropic_api_key, openai_api_key, hf_token }
 * @param {object} original   — the last GET /api/settings result (same shape)
 * @returns {object}  — minimal PUT body; may be {} if nothing changed
 */
export function buildSettingsPatch(formState, original) {
  const patch = {};

  // Regular (non-secret) fields
  for (const field of REGULAR_FIELDS) {
    if (!(field in formState)) continue;
    const newVal = formState[field];
    const oldVal = original[field];
    if (newVal !== oldVal) {
      patch[field] = newVal;
    }
  }

  // Secret fields -> keys block
  const keysBlock = {};
  for (const field of SECRET_FIELDS) {
    const val = formState[field];
    if (val === null) {
      // Explicit clear
      keysBlock[field] = null;
    } else if (typeof val === 'string' && val !== '') {
      // New/replacement value
      keysBlock[field] = val;
    }
    // Empty string -> omit
  }
  if (Object.keys(keysBlock).length > 0) {
    patch.keys = keysBlock;
  }

  return patch;
}

/**
 * Validate a settings patch against server-side rules.
 * Returns an array of human-readable error strings (empty = valid).
 *
 * @param {object} patch
 * @returns {string[]}
 */
export function validateSettings(patch) {
  const errors = [];

  if ('k_sections' in patch) {
    const v = patch.k_sections;
    if (typeof v !== 'number' || v < 1 || v > 20) {
      errors.push(`k_sections must be between 1 and 20 (got ${v})`);
    }
  }

  if ('char_budget' in patch) {
    const v = patch.char_budget;
    if (typeof v !== 'number' || v < 1000 || v > 50000) {
      errors.push(`char_budget must be between 1000 and 50000 (got ${v})`);
    }
  }

  if ('ollama_num_ctx' in patch) {
    const v = patch.ollama_num_ctx;
    if (!Number.isInteger(v) || v < OLLAMA_NUM_CTX_MIN || v > OLLAMA_NUM_CTX_MAX) {
      errors.push(`Context length must be a whole number between ${OLLAMA_NUM_CTX_MIN} and ${OLLAMA_NUM_CTX_MAX} (got ${v})`);
    }
  }

  for (const [field, label] of [['base_url', 'Server URL'], ['ollama_url', 'Ollama URL']]) {
    if (field in patch && !isHttpUrlOrEmpty(patch[field])) {
      errors.push(`${label} must start with http:// or https://`);
    }
  }

  return errors;
}

/**
 * Build a settings patch for the biomedical-connectors toggle.
 * @param {boolean} enabled
 * @returns {{connectors: string[]}}
 */
export function buildConnectorsPatch(enabled) {
  return { connectors: enabled ? ['europepmc', 'pubmed'] : [] };
}
