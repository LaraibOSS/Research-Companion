/**
 * theme.js — Theme variables + DOM application.
 *
 * Pure part (themeVars) is node-testable.
 * DOM part (applyTheme) requires document — not tested with node --test.
 * W3-F1.
 */

const DEFAULTS = { theme: 'dark', accent: 'blue', density: 'comfortable' };

/**
 * Extract { theme, accent, density } from a settings object, applying defaults.
 * Pure — no DOM access.
 * @param {object|null|undefined} settings
 * @returns {{ theme: string, accent: string, density: string }}
 */
export function themeVars(settings) {
  const s = settings || {};
  return {
    theme:   s.theme   || DEFAULTS.theme,
    accent:  s.accent  || DEFAULTS.accent,
    density: s.density || DEFAULTS.density,
  };
}

/**
 * Apply a theme descriptor to the document and persist to localStorage.
 * @param {{ theme: string, accent: string, density: string }} t
 */
export function applyTheme(t) {
  const el = document.documentElement;
  el.dataset.theme   = t.theme;
  el.dataset.accent  = t.accent;
  el.dataset.density = t.density;
  try {
    localStorage.setItem('rc.theme',   t.theme);
    localStorage.setItem('rc.accent',  t.accent);
    localStorage.setItem('rc.density', t.density);
  } catch { /* storage may be blocked in tests/private mode */ }
}
