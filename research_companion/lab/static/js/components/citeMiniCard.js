/**
 * js/components/citeMiniCard.js — Citation chip hover mini-card + drawer open.
 *
 * Usage:
 *   import { attachCiteHandlers } from '../components/citeMiniCard.js';
 *   const cleanup = attachCiteHandlers(containerEl, (n) => citationsArray.find(c => c.n === n));
 *   // call cleanup() when the container is torn down
 *
 * Drawer opening uses the rc:open-paper / __rcPendingPaper handoff so it works
 * even when the library view hasn't mounted yet (landed in d25b1a1).
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
      ? `<div class="cite-minicard-section muted">&sect; ${escapeHtml(citation.section_title)}</div>`
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

function _openPaperDrawer(paperId) {
  // Use the rc:open-paper handoff (landed in d25b1a1).
  // Setting __rcPendingPaper first handles the arrive-before-mount race.
  window.__rcPendingPaper = paperId;
  window.dispatchEvent(new CustomEvent('rc:open-paper', {
    detail: { paperId },
    bubbles: false,
  }));
  // Navigate to library so library.js mounts and picks up the pending paper
  if (window.location.hash !== '#/library') {
    window.location.hash = '#/library';
  }
}

/**
 * Attach cite-chip hover/click handlers to a container element.
 *
 * @param {HTMLElement} containerEl  — element containing .cite chips
 * @param {(n: number) => object|null} resolveCitation
 *   — called with the chip's data-n value; should return the citation object
 *     { n, paper_id, title, section_title, cited } or null
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
    _openPaperDrawer(citation.paper_id);
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
