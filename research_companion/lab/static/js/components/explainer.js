/**
 * js/components/explainer.js — Dismissable one-line explainer banner.
 *
 * Usage:
 *   import { explainerBanner } from '../components/explainer.js';
 *   const banner = explainerBanner('graph', 'Every paper becomes claims...');
 *   if (banner) el.prepend(banner);
 *
 * Dismissal persisted in localStorage under key rc.explainer.<viewId>.
 * Returns null if already dismissed.
 */

/**
 * Create a dismissable explainer banner element.
 * @param {string} viewId  — unique id (used as localStorage key suffix)
 * @param {string} text    — plain-text description (static; safe to set as textContent)
 * @returns {HTMLElement|null}  null if already dismissed
 */
export function explainerBanner(viewId, text) {
  const key = `rc.explainer.${viewId}`;
  try {
    if (localStorage.getItem(key) === '1') return null;
  } catch {
    // localStorage unavailable (e.g. private mode restriction) — show banner
  }

  const el = document.createElement('div');
  el.className = 'rc-explainer';
  el.setAttribute('role', 'note');

  const icon = document.createElement('span');
  icon.className = 'rc-explainer-icon';
  icon.textContent = 'ℹ';   // ℹ
  icon.setAttribute('aria-hidden', 'true');

  const msg = document.createElement('span');
  msg.className = 'rc-explainer-text';
  msg.textContent = text;   // static string — textContent is safe

  const close = document.createElement('button');
  close.className = 'rc-explainer-close';
  close.setAttribute('aria-label', 'Dismiss');
  close.textContent = '×';  // ×
  close.addEventListener('click', () => {
    try { localStorage.setItem(key, '1'); } catch { /* ignore */ }
    el.remove();
  });

  el.appendChild(icon);
  el.appendChild(msg);
  el.appendChild(close);
  return el;
}
