/**
 * components/welcomeDialog.js — First-launch "get set up" dialog.
 *
 * Shown once on first launch, and whenever the active provider's LLM key is
 * missing, so new users know they must add a model key (required) and can
 * optionally add a Hugging Face token for better semantic search.
 *
 * API:
 *   openWelcomeDialog(settings)  — show the dialog for the given settings snapshot
 *   closeWelcomeDialog()         — dismiss (also persists the "seen" flag)
 *
 * Dismiss triggers (all persist rc.welcomeShown): X button, backdrop click,
 * Escape, "Maybe later". "Go to Settings" navigates to #/settings and closes.
 */

import { escapeHtml } from '../format.js';
import { activeKeyName, missingHfToken, WELCOME_SEEN_KEY } from '../keyPromptHelpers.js';

let _overlay = null;
let _onKeydown = null;

function _statusPill(set) {
  return set
    ? `<span class="welcome-status welcome-status-ok">Added</span>`
    : `<span class="welcome-status welcome-status-missing">Not set</span>`;
}

export function openWelcomeDialog(settings) {
  const keys = (settings && settings.keys) || {};
  const llmName = activeKeyName(settings);
  const llmLabel = llmName === 'openai_api_key' ? 'OpenAI API key' : 'Anthropic API key';
  const llmSet = !!(keys[llmName] && keys[llmName].set);
  const hfSet = !missingHfToken(settings);

  if (_overlay) closeWelcomeDialog();

  _overlay = document.createElement('div');
  _overlay.className = 'welcome-overlay';
  _overlay.addEventListener('click', (e) => { if (e.target === _overlay) closeWelcomeDialog(); });

  const dialog = document.createElement('div');
  dialog.className = 'welcome-dialog';
  dialog.setAttribute('role', 'dialog');
  dialog.setAttribute('aria-modal', 'true');
  dialog.setAttribute('aria-labelledby', 'welcome-title');
  dialog.innerHTML = `
    <button class="drawer-close welcome-close" aria-label="Close" title="Close">&times;</button>
    <h2 id="welcome-title" class="welcome-title">Get set up</h2>
    <p class="welcome-sub">Research Companion needs a model to analyse your papers. Add your keys to unlock everything.</p>
    <ul class="welcome-keys">
      <li class="welcome-key">
        <div class="welcome-key-main">
          <span class="welcome-key-name">${escapeHtml(llmLabel)} <span class="welcome-req">required</span></span>
          <span class="welcome-key-desc">Powers extraction, chat, alignment and review.</span>
        </div>
        ${_statusPill(llmSet)}
      </li>
      <li class="welcome-key">
        <div class="welcome-key-main">
          <span class="welcome-key-name">Hugging Face token <span class="welcome-opt">optional</span></span>
          <span class="welcome-key-desc">Enables better semantic search; without it, keyword (BM25) search is used.</span>
        </div>
        ${_statusPill(hfSet)}
      </li>
    </ul>
    <div class="welcome-actions">
      <button class="btn" id="welcome-later">Maybe later</button>
      <a class="btn btn-accent" id="welcome-settings" href="#/settings">Go to Settings</a>
    </div>
  `;

  _overlay.appendChild(dialog);
  document.body.appendChild(_overlay);

  dialog.querySelector('.welcome-close').addEventListener('click', closeWelcomeDialog);
  dialog.querySelector('#welcome-later').addEventListener('click', closeWelcomeDialog);
  dialog.querySelector('#welcome-settings').addEventListener('click', () => {
    // href already navigates to #/settings; just dismiss + persist.
    closeWelcomeDialog();
  });

  _onKeydown = (e) => { if (e.key === 'Escape') closeWelcomeDialog(); };
  document.addEventListener('keydown', _onKeydown);
}

export function closeWelcomeDialog() {
  try { localStorage.setItem(WELCOME_SEEN_KEY, '1'); } catch { /* noop */ }
  if (_onKeydown) {
    document.removeEventListener('keydown', _onKeydown);
    _onKeydown = null;
  }
  if (_overlay) {
    _overlay.remove();
    _overlay = null;
  }
}
