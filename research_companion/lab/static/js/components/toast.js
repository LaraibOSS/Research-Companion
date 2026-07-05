/**
 * components/toast.js — Bottom toast notifications.
 * Types: 'info' (default) | 'error'
 * Auto-dismisses after 4 seconds.
 */

let _container = null;

function _getContainer() {
  if (_container) return _container;
  _container = document.createElement('div');
  _container.id = 'toast-container';
  _container.style.cssText = [
    'position:fixed',
    'bottom:24px',
    'left:50%',
    'transform:translateX(-50%)',
    'display:flex',
    'flex-direction:column',
    'align-items:center',
    'gap:8px',
    'z-index:9999',
    'pointer-events:none',
  ].join(';');
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
  toast.style.cssText = [
    'padding:10px 18px',
    'border-radius:6px',
    'font-size:14px',
    'font-weight:500',
    'pointer-events:auto',
    'cursor:pointer',
    'opacity:0',
    'transition:opacity 0.2s ease',
    type === 'error'
      ? 'background:var(--color-fail);color:#fff'
      : 'background:var(--color-panel);color:var(--color-fg);border:1px solid var(--color-border)',
  ].join(';');

  container.appendChild(toast);

  // Animate in
  requestAnimationFrame(() => {
    toast.style.opacity = '1';
  });

  const dismiss = () => {
    toast.style.opacity = '0';
    setTimeout(() => { if (toast.parentNode) toast.parentNode.removeChild(toast); }, 220);
  };

  toast.addEventListener('click', dismiss);
  setTimeout(dismiss, duration);
}
