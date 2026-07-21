/**
 * js/components/citeMiniCard.js — Citation chip hover mini-card + drawer open.
 *
 * Usage:
 *   import { attachCiteHandlers } from '../components/citeMiniCard.js';
 *   const cleanup = attachCiteHandlers(containerEl, (n) => citationsArray.find(c => c.n === n));
 *   // call cleanup() when the container is torn down
 *
 * Clicking a chip dispatches rc:open-reader so the paper reader opens at the
 * exact source span (using the citation's absolute char offsets) — the
 * "verify it yourself" moment for Q&A. Falls back to opening at the section
 * (or the paper) when offsets are absent/degenerate (e.g. old data).
 */

import { escapeHtml } from '../format.js';

// Shared singleton mini-card (one across all callers)
let _miniCard = null;

function _ensureMiniCard() {
  if (_miniCard) return _miniCard;
  _miniCard = document.createElement('div');
  _miniCard.className = 'cite-minicard';
  _miniCard.style.display = 'none';
  document.body.appendChild(_miniCard);
  return _miniCard;
}

function _hideMiniCard() {
  if (_miniCard) _miniCard.style.display = 'none';
}

function _showMiniCard(chip, citation) {
  const card = _ensureMiniCard();
  card.innerHTML = `
    <div class="cite-minicard-title">${escapeHtml(citation.title || citation.paper_id || '')}</div>
    ${citation.section_title
      ? `<div class="cite-minicard-section muted">${escapeHtml(citation.section_title)}</div>`
      : ''}
    ${citation.cited
      ? '<span class="badge badge-ok">cited</span>'
      : '<span class="badge badge-warn">retrieved</span>'}
  `;
  const rect = chip.getBoundingClientRect();
  card.style.display = 'block';
  const cardW = 280;
  const left = Math.max(8, Math.min(rect.left, window.innerWidth - cardW - 8));
  card.style.left = `${left}px`;
  card.style.top = `${rect.bottom + 6}px`;
}

function _openCitationInReader(citation) {
  // Open the reader at the exact source span. reader.js is mounted once at
  // boot and is the sole listener for rc:open-reader; it highlights an
  // explicit [charStart, charEnd] range directly (no ?q= locate). When the
  // offsets are absent/zero it still opens at the section (sectionId), or the
  // paper if there's no section either.
  window.dispatchEvent(new CustomEvent('rc:open-reader', {
    detail: {
      paperId: citation.paper_id,
      sectionId: citation.section_id,
      charStart: citation.char_start,
      charEnd: citation.char_end,
      title: citation.title,
    },
  }));
}

/**
 * Attach cite-chip hover/click handlers to a container element.
 *
 * @param {HTMLElement} containerEl  — element containing .cite chips
 * @param {(n: number) => object|null} resolveCitation
 *   — called with the chip's data-n value; should return the citation object
 *     { n, paper_id, title, section_id, section_title, cited, char_start,
 *       char_end } or null
 * @returns {() => void}  cleanup — removes all event listeners
 */
export function attachCiteHandlers(containerEl, resolveCitation) {
  function onMouseover(e) {
    const chip = e.target.closest && e.target.closest('.cite');
    if (!chip) return;
    const n = Number(chip.dataset.n);
    const citation = resolveCitation(n);
    if (citation) _showMiniCard(chip, citation);
  }

  function onMouseout(e) {
    if (e.target.closest && e.target.closest('.cite')) _hideMiniCard();
  }

  function onClick(e) {
    const chip = e.target.closest && e.target.closest('.cite');
    if (!chip) return;
    const n = Number(chip.dataset.n);
    const citation = resolveCitation(n);
    if (!citation) return;
    _hideMiniCard();
    _openCitationInReader(citation);
  }

  containerEl.addEventListener('mouseover', onMouseover);
  containerEl.addEventListener('mouseout', onMouseout);
  containerEl.addEventListener('click', onClick);

  return function cleanup() {
    containerEl.removeEventListener('mouseover', onMouseover);
    containerEl.removeEventListener('mouseout', onMouseout);
    containerEl.removeEventListener('click', onClick);
  };
}
