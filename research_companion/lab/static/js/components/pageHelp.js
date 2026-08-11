/**
 * components/pageHelp.js — the persistent "?" affordance on every page.
 *
 * Unlike the one-line explainerBanner (dismissed once, gone forever), this is
 * always available: a small "?" button pinned to the view that opens a short
 * write-up of what the page does, what its content is based on, and the
 * verify-before-you-cite disclaimer.
 *
 * The router attaches it to every mounted view, so a page never has to remember
 * to add it. Copy lives in helpContent.js (pure, node-tested). Distinct from the global
 * helpPanel.js drawer (glossary + core flows), which stays as-is.
 */
import { helpFor } from '../helpContent.js';

const BTN_ID = 'rc-help-fab';
const PANEL_ID = 'rc-help-panel';
let _escBound = false;

function _close() {
  const panel = document.getElementById(PANEL_ID);
  if (panel) panel.remove();
  const btn = document.getElementById(BTN_ID);
  if (btn) btn.setAttribute('aria-expanded', 'false');
}

function _open(viewId) {
  if (document.getElementById(PANEL_ID)) { _close(); return; }
  const help = helpFor(viewId);

  const panel = document.createElement('div');
  panel.id = PANEL_ID;
  panel.className = 'rc-help-panel';
  panel.setAttribute('role', 'dialog');
  panel.setAttribute('aria-label', `About ${help.title}`);

  // Built with DOM APIs + textContent — help copy is static, but this keeps the
  // component injection-proof by construction rather than by convention.
  const head = document.createElement('div');
  head.className = 'rc-help-head';
  const h = document.createElement('h3');
  h.className = 'rc-help-title';
  h.textContent = help.title;
  const x = document.createElement('button');
  x.className = 'rc-help-close';
  x.setAttribute('aria-label', 'Close help');
  x.textContent = '×';
  x.addEventListener('click', () => _close());
  head.appendChild(h);
  head.appendChild(x);

  const what = document.createElement('p');
  what.className = 'rc-help-what';
  what.textContent = help.what;

  const basedLabel = document.createElement('div');
  basedLabel.className = 'rc-help-label';
  basedLabel.textContent = 'What it uses';
  const based = document.createElement('p');
  based.className = 'rc-help-based';
  based.textContent = help.basedOn;

  const discLabel = document.createElement('div');
  discLabel.className = 'rc-help-label';
  discLabel.textContent = help.aiUsed ? 'Verify before you cite' : 'How reliable is this';
  const disc = document.createElement('p');
  disc.className = 'rc-help-disclaimer' + (help.aiUsed ? ' is-ai' : '');
  disc.textContent = help.disclaimer;

  panel.append(head, what, basedLabel, based, discLabel, disc);
  document.body.appendChild(panel);

  const btn = document.getElementById(BTN_ID);
  if (btn) btn.setAttribute('aria-expanded', 'true');
  x.focus();
}

/**
 * Attach (or re-attach) the help affordance to a freshly-mounted view.
 * Safe to call on every route render: it removes any previous instance first.
 * @param {HTMLElement} viewEl — the router's view container
 * @param {string} viewId — current route ('/graph') or bare id ('graph')
 */
export function attachHelp(viewEl, viewId) {
  // Hosted on document.body (the button is position:fixed): several views reset
  // their container's innerHTML after mount, which would wipe a child of viewEl.
  const old = document.getElementById(BTN_ID);
  if (old) old.remove();
  _close();

  const help = helpFor(viewId);
  const btn = document.createElement('button');
  btn.id = BTN_ID;
  btn.className = 'rc-help-fab';
  btn.type = 'button';
  btn.textContent = '?';
  btn.title = `What is ${help.title}?`;
  btn.setAttribute('aria-label', `What is ${help.title}?`);
  btn.setAttribute('aria-expanded', 'false');
  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    _open(viewId);
  });
  document.body.appendChild(btn);

  // One global Escape handler for the panel, installed once.
  if (!_escBound) {
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') _close();
    });
    _escBound = true;
  }
}
