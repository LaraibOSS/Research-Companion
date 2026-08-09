/**
 * components/confirmDialog.js — Minimal promise-based confirm dialog.
 *
 * confirmDialog({title, message, confirmLabel, cancelLabel}) -> Promise<boolean>
 * Resolves true if the user picks the primary (confirm) action, false on
 * cancel / backdrop / Escape / X. Reuses the welcome-dialog styling.
 */

import { escapeHtml } from '../format.js';

export function confirmDialog({ title, message, confirmLabel = 'OK', cancelLabel = 'Cancel' } = {}) {
  return new Promise((resolve) => {
    const overlay = document.createElement('div');
    overlay.className = 'welcome-overlay';

    let settled = false;
    const done = (value) => {
      if (settled) return;
      settled = true;
      document.removeEventListener('keydown', onKeydown);
      overlay.remove();
      resolve(value);
    };
    const onKeydown = (e) => { if (e.key === 'Escape') done(false); };

    overlay.addEventListener('click', (e) => { if (e.target === overlay) done(false); });

    const dialog = document.createElement('div');
    dialog.className = 'welcome-dialog welcome-dialog-sm';
    dialog.setAttribute('role', 'dialog');
    dialog.setAttribute('aria-modal', 'true');
    dialog.innerHTML = `
      <button class="drawer-close welcome-close" aria-label="Close" title="Close">&times;</button>
      <h2 class="welcome-title">${escapeHtml(title || '')}</h2>
      <p class="welcome-sub">${escapeHtml(message || '')}</p>
      <div class="welcome-actions">
        <button class="btn" data-role="cancel">${escapeHtml(cancelLabel)}</button>
        <button class="btn btn-accent" data-role="confirm">${escapeHtml(confirmLabel)}</button>
      </div>
    `;

    overlay.appendChild(dialog);
    document.body.appendChild(overlay);

    dialog.querySelector('.welcome-close').addEventListener('click', () => done(false));
    dialog.querySelector('[data-role="cancel"]').addEventListener('click', () => done(false));
    dialog.querySelector('[data-role="confirm"]').addEventListener('click', () => done(true));
    document.addEventListener('keydown', onKeydown);
  });
}

/**
 * promptDialog({title, message, placeholder, confirmLabel, cancelLabel}) -> Promise<string|null>
 * A single-text-input modal, styled like confirmDialog. Resolves the
 * trimmed input value on confirm (Enter or the confirm button), or null on
 * an empty value / cancel / backdrop / Escape / X. Never throws.
 */
export function promptDialog({
  title, message, placeholder = '', confirmLabel = 'Create', cancelLabel = 'Cancel',
} = {}) {
  return new Promise((resolve) => {
    const overlay = document.createElement('div');
    overlay.className = 'welcome-overlay';

    let settled = false;
    const done = (value) => {
      if (settled) return;
      settled = true;
      document.removeEventListener('keydown', onKeydown);
      overlay.remove();
      resolve(value);
    };
    const onKeydown = (e) => { if (e.key === 'Escape') done(null); };

    overlay.addEventListener('click', (e) => { if (e.target === overlay) done(null); });

    const dialog = document.createElement('div');
    dialog.className = 'welcome-dialog welcome-dialog-sm';
    dialog.setAttribute('role', 'dialog');
    dialog.setAttribute('aria-modal', 'true');
    dialog.innerHTML = `
      <button class="drawer-close welcome-close" aria-label="Close" title="Close">&times;</button>
      <h2 class="welcome-title">${escapeHtml(title || '')}</h2>
      <p class="welcome-sub">${escapeHtml(message || '')}</p>
      <input class="ws-create-input" type="text" maxlength="120"
             placeholder="${escapeHtml(placeholder)}" aria-label="${escapeHtml(title || '')}">
      <div class="welcome-actions">
        <button class="btn" data-role="cancel">${escapeHtml(cancelLabel)}</button>
        <button class="btn btn-accent" data-role="confirm">${escapeHtml(confirmLabel)}</button>
      </div>
    `;

    overlay.appendChild(dialog);
    document.body.appendChild(overlay);

    const input = dialog.querySelector('input');
    const submit = () => done(input.value.trim() || null);

    dialog.querySelector('.welcome-close').addEventListener('click', () => done(null));
    dialog.querySelector('[data-role="cancel"]').addEventListener('click', () => done(null));
    dialog.querySelector('[data-role="confirm"]').addEventListener('click', submit);
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') submit(); });
    document.addEventListener('keydown', onKeydown);
    input.focus();
  });
}
