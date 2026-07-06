/**
 * icons.js — Inline SVG icon set (pure data module, no DOM dependencies).
 * All icons: 18x18 viewport, stroke currentColor, fill none, stroke-width 1.7.
 * W3-F1.
 */

/** @type {Record<string, string>} */
export const ICONS = {
  home: `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M2 7.5L9 2l7 5.5V16a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V7.5z"/><path d="M6.5 17V11h5v6"/></svg>`,

  library: `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="4" height="12" rx="1"/><rect x="7" y="3" width="4" height="12" rx="1"/><rect x="12" y="3" width="4" height="12" rx="1"/></svg>`,

  graph: `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="9" r="2"/><circle cx="3" cy="5" r="1.5"/><circle cx="15" cy="5" r="1.5"/><circle cx="3" cy="13" r="1.5"/><circle cx="15" cy="13" r="1.5"/><line x1="7.3" y1="7.7" x2="4.2" y2="6.2"/><line x1="10.7" y1="7.7" x2="13.8" y2="6.2"/><line x1="7.3" y1="10.3" x2="4.2" y2="11.8"/><line x1="10.7" y1="10.3" x2="13.8" y2="11.8"/></svg>`,

  draft: `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M11 2H5a1 1 0 0 0-1 1v12a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1V6l-3-4z"/><path d="M11 2v4h3"/><path d="M7 10l1.5 1.5L12 8"/></svg>`,

  timeline: `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="9" r="7"/><polyline points="9,5 9,9 12,11"/></svg>`,

  ask: `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M15 2H3a1 1 0 0 0-1 1v9a1 1 0 0 0 1 1h3l3 3 3-3h3a1 1 0 0 0 1-1V3a1 1 0 0 0-1-1z"/></svg>`,

  compare: `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="2" width="6" height="14" rx="1"/><rect x="10" y="2" width="6" height="14" rx="1"/></svg>`,

  settings: `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="9" r="2.5"/><path d="M9 1v2M9 15v2M1 9h2M15 9h2M3.22 3.22l1.42 1.42M13.36 13.36l1.42 1.42M3.22 14.78l1.42-1.42M13.36 4.64l1.42-1.42"/></svg>`,

  help: `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="9" r="7"/><path d="M6.8 6.8a2.5 2.5 0 1 1 2.5 2.5c0 0-0.3.7-0.3 1.7"/><circle cx="9" cy="13" r="0.5" fill="currentColor"/></svg>`,

  bell: `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M9 2a5 5 0 0 1 5 5v3l1.5 2.5H2.5L4 10V7a5 5 0 0 1 5-5z"/><path d="M7 14a2 2 0 0 0 4 0"/></svg>`,

  plus: `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><line x1="9" y1="3" x2="9" y2="15"/><line x1="3" y1="9" x2="15" y2="9"/></svg>`,

  x: `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><line x1="4" y1="4" x2="14" y2="14"/><line x1="14" y1="4" x2="4" y2="14"/></svg>`,
};

/**
 * Return the SVG string for an icon name, or '' if unknown.
 * @param {string} name
 * @returns {string}
 */
export function icon(name) {
  return ICONS[name] || '';
}
