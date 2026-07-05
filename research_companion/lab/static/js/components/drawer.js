/**
 * components/drawer.js — Right slide-in panel (420px wide).
 * Generic: open(html), close().
 */

let _drawer = null;
let _overlay = null;
let _escapeListenerAttached = false;

function _handleEscape(e) {
  if (e.key === 'Escape') close();
}

function _ensureDOM() {
  if (_drawer) return;

  _overlay = document.createElement('div');
  _overlay.className = 'drawer-overlay';
  _overlay.addEventListener('click', close);

  _drawer = document.createElement('div');
  _drawer.className = 'drawer';
  _drawer.setAttribute('role', 'dialog');
  _drawer.setAttribute('aria-modal', 'true');

  const closeBtn = document.createElement('button');
  closeBtn.className = 'drawer-close';
  closeBtn.innerHTML = '&times;';
  closeBtn.setAttribute('aria-label', 'Close');
  closeBtn.addEventListener('click', close);

  const content = document.createElement('div');
  content.className = 'drawer-content';
  content.id = 'drawer-content';

  _drawer.appendChild(closeBtn);
  _drawer.appendChild(content);

  document.body.appendChild(_overlay);
  document.body.appendChild(_drawer);

  // Close on Escape — named handler so it can be removed if needed
  if (!_escapeListenerAttached) {
    document.addEventListener('keydown', _handleEscape);
    _escapeListenerAttached = true;
  }
}

/**
 * Open the drawer with HTML content.
 * @param {string} html
 */
export function open(html) {
  _ensureDOM();
  document.getElementById('drawer-content').innerHTML = html;
  _drawer.classList.add('open');
  _overlay.classList.add('open');
  document.body.style.overflow = 'hidden';
}

/**
 * Close the drawer.
 */
export function close() {
  if (!_drawer) return;
  _drawer.classList.remove('open');
  _overlay.classList.remove('open');
  document.body.style.overflow = '';
}

/**
 * Check if drawer is currently open.
 * @returns {boolean}
 */
export function isOpen() {
  return _drawer ? _drawer.classList.contains('open') : false;
}
