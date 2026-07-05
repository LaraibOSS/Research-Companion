/**
 * router.js — Hash-based SPA router.
 *
 * Routes: #/library (default), #/graph, #/draft, #/compare, #/ask
 * Unknown routes fall back to library.
 *
 * Usage:
 *   import { registerRoute, startRouter } from './router.js';
 *   registerRoute('/library', { mount(el) {...}, unmount() {...} });
 *   startRouter(document.getElementById('view'));
 */

const _registry = new Map();
let _currentRoute = null;
let _viewEl = null;

/**
 * Register a route handler.
 * @param {string} route  — e.g. '/library'
 * @param {{ mount: (el: HTMLElement) => void, unmount: () => void }} handler
 */
export function registerRoute(route, handler) {
  _registry.set(route, handler);
}

/**
 * Parse the current hash into a route string and optional query params.
 * e.g. '#/compare?a=123' -> { route: '/compare', params: { a: '123' } }
 */
function _parseHash() {
  const hash = window.location.hash || '#/library';
  const withoutHash = hash.slice(1); // remove leading '#'
  const [routePart, queryPart] = withoutHash.split('?');
  const route = routePart || '/library';
  const params = {};
  if (queryPart) {
    for (const pair of queryPart.split('&')) {
      const [k, v] = pair.split('=');
      if (k) params[decodeURIComponent(k)] = decodeURIComponent(v || '');
    }
  }
  return { route, params };
}

/**
 * Navigate to a route.
 * @param {string} route  — e.g. '/library' or '/compare?a=abc'
 */
export function navigate(route) {
  window.location.hash = '#' + route;
}

function _render() {
  const { route } = _parseHash();

  // Unmount current view if different
  if (_currentRoute && _currentRoute !== route) {
    const prev = _registry.get(_currentRoute);
    if (prev && typeof prev.unmount === 'function') {
      try { prev.unmount(); } catch (e) { console.error('[router] unmount error', e); }
    }
  }

  // Clear view element
  if (_viewEl) _viewEl.innerHTML = '';

  // Update nav highlights
  document.querySelectorAll('[data-route]').forEach(el => {
    el.classList.toggle('active', el.dataset.route === route);
  });

  // Mount new view
  const handler = _registry.get(route) || _registry.get('/library');
  _currentRoute = route;
  if (handler && typeof handler.mount === 'function' && _viewEl) {
    try { handler.mount(_viewEl); } catch (e) { console.error('[router] mount error', e); }
  }
}

/**
 * Start the router, listening for hashchange.
 * @param {HTMLElement} viewEl  — the <main id="view"> mount point
 */
export function startRouter(viewEl) {
  _viewEl = viewEl;
  window.addEventListener('hashchange', _render);
  _render();
}
