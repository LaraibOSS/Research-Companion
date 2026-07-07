/**
 * js/components/helpPanel.js — Full help drawer (W3-F7).
 *
 * Opens the existing drawer-overlay mechanism with rich static content:
 *   - What-is-this paragraph
 *   - Five core flows
 *   - Glossary table (single source from glossary.js)
 *   - Links + version line
 *
 * Idempotent: clicking help again closes the panel.
 */

import { GLOSSARY } from '../glossary.js';

const VERSION = 'v0.5.1';
const GITHUB_URL = 'https://github.com/Laraib-Hasan-Future/Research-Companion';
const DOCS_PATH = 'docs/RESEARCH_COMPANION_GUIDE.pdf';

const CORE_FLOWS = [
  ['Add a paper',
   'Click "+ Add papers" and paste an arXiv ID, URL, or file path.'],
  ['Ingest a folder',
   'Use "Ingest folder…" in the Library to bulk-process a directory of PDFs.'],
  ['Review suggestions',
   'Open the bell (top-right) to see AI-generated improvement suggestions for your draft.'],
  ['Discuss with the companion',
   'Click the chat FAB (bottom-right) to ask questions grounded in your ingested papers.'],
  ['Explore the timeline',
   'Navigate to Timeline to see how the field evolved and where research gaps remain open.'],
];

/**
 * Escape a string for safe use in HTML (not attributes — for text content).
 * @param {string} s
 * @returns {string}
 */
function _esc(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

/**
 * Build the glossary table HTML from GLOSSARY (single source of truth).
 * @returns {string}
 */
function _glossaryTableHtml() {
  const rows = Object.entries(GLOSSARY)
    .map(([term, def]) =>
      `<tr><td class="help-glossary-term">${_esc(term)}</td><td>${_esc(def)}</td></tr>`,
    )
    .join('');
  return `
    <table class="help-glossary-table">
      <thead>
        <tr><th>Term</th><th>Meaning</th></tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>`;
}

/**
 * Open (or close if already open) the help drawer.
 */
export function openHelpPanel() {
  const existing = document.getElementById('help-drawer-overlay');
  if (existing) { existing.remove(); return; }

  const flowsHtml = CORE_FLOWS
    .map(([title, desc]) =>
      `<li><strong>${_esc(title)}:</strong> ${_esc(desc)}</li>`,
    )
    .join('');

  const overlay = document.createElement('div');
  overlay.id = 'help-drawer-overlay';
  overlay.className = 'drawer-overlay open';

  const drawer = document.createElement('div');
  drawer.className = 'drawer open';
  drawer.innerHTML = `
    <button class="drawer-close" id="help-close" aria-label="Close help">&times;</button>
    <div class="drawer-content">
      <div class="drawer-header">
        <h2 class="drawer-title">Help &amp; Documentation</h2>
        <div class="muted" style="font-size:var(--text-sm)">${_esc(VERSION)}</div>
      </div>

      <section class="help-section">
        <h3 class="help-section-title">What is Research Companion?</h3>
        <p class="help-body">
          Research Companion is a local AI lab that ingests your PDFs, extracts claims, methods
          and results, then helps you analyse the literature, align your draft, and discuss
          findings — all grounded in your own papers.
        </p>
      </section>

      <section class="help-section">
        <h3 class="help-section-title">Core flows</h3>
        <ol class="help-flows">${flowsHtml}</ol>
      </section>

      <section class="help-section">
        <h3 class="help-section-title">Glossary</h3>
        ${_glossaryTableHtml()}
      </section>

      <section class="help-section">
        <h3 class="help-section-title">Resources</h3>
        <div style="display:flex;flex-direction:column;gap:8px">
          <a href="${GITHUB_URL}" target="_blank" rel="noopener"
             class="btn btn-secondary btn-sm">GitHub repository &#8599;</a>
          <p class="muted" style="font-size:var(--text-sm);margin:0">
            PDF guide: <code>${_esc(DOCS_PATH)}</code>
            (open from project root)
          </p>
        </div>
      </section>
    </div>`;

  overlay.appendChild(drawer);
  document.body.appendChild(overlay);

  const close = () => overlay.remove();
  overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
  const closeBtn = overlay.querySelector('#help-close');
  if (closeBtn) closeBtn.addEventListener('click', close);
}
