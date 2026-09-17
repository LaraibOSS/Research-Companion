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
const SECRET_FIELDS = ['anthropic_api_key', 'openai_api_key', 'hf_token'];

/** Non-secret fields that can appear at the top level of a PUT body. */
const REGULAR_FIELDS = ['provider', 'model', 'theme', 'accent', 'density', 'k_sections', 'char_budget', 'embed_model', 'contact_email', 'downloads_dir'];

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
