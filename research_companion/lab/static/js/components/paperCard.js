/**
 * components/paperCard.js — renderPaperCard(paper) -> HTMLElement
 */

import { strengthColor, stanceIcon, authorsLine, escapeHtml } from '../format.js';

/**
 * Render a paper card element.
 * @param {object} paper  — paper object from store
 * @returns {HTMLElement}
 */
export function renderPaperCard(paper) {
  const card = document.createElement('div');
  card.className = 'paper-card';
  card.dataset.paperId = paper.paper_id;

  // Left border color based on strength / status
  let borderColor;
  if (paper.status === 'failed') {
    borderColor = '#f85149';
    card.classList.add('status-failed');
  } else if (paper.status === 'processing') {
    borderColor = '#58a6ff';
    card.classList.add('status-processing');
  } else if (paper.strength && paper.strength.band) {
    borderColor = strengthColor(paper.strength.band);
  } else {
    borderColor = strengthColor('unscored');
  }
  card.style.borderLeftColor = borderColor;

  // Build badges
  const badges = [];
  if (paper.is_draft) {
    badges.push('<span class="badge badge-draft">★ DRAFT</span>');
  }

  // Stance chips from stance_counts
  const sc = paper.stance_counts || {};
  const strengthens = sc.strengthens || 0;
  const challenges = sc.challenges || 0;
  const alternative = sc.alternative || 0;
  const stanceHtml = [
    strengthens > 0 ? `<span class="stance-chip stance-strengthens">▲${strengthens}</span>` : '',
    challenges > 0  ? `<span class="stance-chip stance-challenges">⚡${challenges}</span>` : '',
    alternative > 0 ? `<span class="stance-chip stance-alternative">◆${alternative}</span>` : '',
  ].filter(Boolean).join('');

  const bandLabel = paper.strength ? paper.strength.band : (paper.status === 'processing' ? 'processing' : 'unscored');

  card.innerHTML = `
    <div class="paper-card-body">
      <div class="paper-title">${escapeHtml(paper.title || 'Untitled')}</div>
      <div class="paper-meta muted">${escapeHtml(authorsLine(paper.authors || [], paper.year))}</div>
      <div class="paper-badges">
        ${badges.join('')}
        ${stanceHtml}
        <span class="strength-badge" style="color:${borderColor}">${escapeHtml(bandLabel)}</span>
      </div>
      ${paper.status === 'failed' && paper.failure_reason
        ? `<div class="failure-reason muted">${escapeHtml(paper.failure_reason)}</div>
           <div class="card-actions">
             <button class="btn btn-sm btn-retry" data-paper-id="${escapeHtml(paper.paper_id)}">Retry</button>
             <button class="btn btn-sm btn-remove" data-paper-id="${escapeHtml(paper.paper_id)}">Remove</button>
           </div>`
        : ''}
    </div>
  `;

  return card;
}
