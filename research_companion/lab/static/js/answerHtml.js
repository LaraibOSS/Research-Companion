/**
 * js/answerHtml.js — Shared answer-rendering helpers.
 *
 * Exported for use by both views/ask.js and components/conversePanel.js.
 * Pure functions; no DOM dependencies; node-testable.
 *
 * SECURITY: escapeHtml is applied to the entire answer string FIRST,
 * before any markup is constructed, so LLM output can never inject HTML.
 */

import { escapeHtml } from './format.js';

/**
 * Render an LLM answer as minimal markdown-lite HTML.
 *
 * SECURITY: the whole answer is passed through escapeHtml FIRST, so no
 * markup from the model (e.g. a <script> tag) can ever survive; all tags
 * below are constructed from the escaped text.
 *
 * Supports: paragraphs on blank lines, **bold**, `code` spans, "- " lists,
 * and [S#]/[#] citation tags -> <sup class="cite" data-n="#">[#]</sup>.
 *
 * @param {string|null} answer
 * @param {Array<{n:number}>} [citations]  — reserved; chips are resolved
 *   against the citations list at event time in the view
 * @returns {string} safe HTML
 */
export function renderAnswerHtml(answer, citations = []) {
  return _render(answer, _inlineWithCitations);
}

/**
 * The same markdown-lite rendering, but `[S1]` stays literal text.
 *
 * For surfaces that list their sources separately rather than inline. The
 * Report tab is one: it renders a chip per source beneath each answer and has
 * no handler for an inline marker, so turning `[S1]` into the superscript Ask
 * uses would promise a link that does nothing.
 *
 * @param {string|null} text
 * @returns {string} safe HTML
 */
export function renderProseHtml(text) {
  return _render(text, _inlinePlain);
}

const _inlinePlain = (s) => s
  .replace(/`([^`]+)`/g, '<code>$1</code>')
  .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');

const _inlineWithCitations = (s) => _inlinePlain(s)
  .replace(/\[S?(\d+)\]/g, '<sup class="cite" data-n="$1">[$1]</sup>');

function _render(text, inline) {
  const escaped = escapeHtml(text == null ? '' : String(text));

  const blocks = escaped
    .split(/\n[ \t]*\n/)
    .map(b => b.trim())
    .filter(Boolean);

  return blocks.map(block => {
    const lines = block.split('\n').map(l => l.trim()).filter(Boolean);
    if (lines.length > 0 && lines.every(l => l.startsWith('- '))) {
      const items = lines.map(l => `<li>${inline(l.slice(2).trim())}</li>`).join('');
      return `<ul>${items}</ul>`;
    }
    return `<p>${inline(lines.join('<br>'))}</p>`;
  }).join('');
}

/**
 * Render the unverified-quotes warning panel HTML.
 * Returns '' when the list is empty.
 *
 * @param {string[]} unverified
 * @returns {string} safe HTML
 */
export function renderUnverifiedHtml(unverified) {
  if (!Array.isArray(unverified) || unverified.length === 0) return '';
  return `
    <div class="ask-unverified">
      <div class="ask-unverified-title">
        &#9888; ${unverified.length} quoted span${unverified.length !== 1 ? 's' : ''}
        could not be verified against sources
      </div>
      <ul class="ask-unverified-list">
        ${unverified.map(q => {
          const s = String(q == null ? '' : q);
          const shown = s.length > 120 ? s.slice(0, 120) + '…' : s;
          return `<li>${escapeHtml(shown)}</li>`;
        }).join('')}
      </ul>
    </div>`;
}
