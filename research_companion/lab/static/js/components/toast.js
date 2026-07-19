/**
 * components/toast.js — Bottom toast notifications.
 * Types: 'info' (default) | 'error'
 * Auto-dismisses after 4 seconds.
 *
 * Styling lives in lab.css (#toast-container, .toast, .toast-info,
 * .toast-error, .toast-visible) so the toast follows the design tokens
 * (spacing/radius/typography/color) and respects theme + density.
 */

let _container = null;

function _getContainer() {
  if (_container) return _container;
  _container = document.createElement('div');
  _container.id = 'toast-container';
  document.body.appendChild(_container);
  return _container;
}

/**
 * Show a toast notification.
 * @param {string} message
 * @param {'info'|'error'} [type='info']
 * @param {number} [duration=4000]
 */
export function showToast(message, type = 'info', duration = 4000) {
  const container = _getContainer();
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.textContent = message;

  container.appendChild(toast);

  // Animate in
  requestAnimationFrame(() => {
    toast.classList.add('toast-visible');
  });

  const dismiss = () => {
    toast.classList.remove('toast-visible');
    setTimeout(() => { if (toast.parentNode) toast.parentNode.removeChild(toast); }, 220);
  };

  toast.addEventListener('click', dismiss);
  setTimeout(dismiss, duration);
}
