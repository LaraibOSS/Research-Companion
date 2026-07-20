/**
 * components/paperCard.js — renderPaperCard(paper) -> HTMLElement
 */

import { strengthColor, stanceIcon, authorsLine, escapeHtml } from '../format.js';
import { tip } from '../glossary.js';
import { needsMetadata, formatFailureReason } from '../libraryHelpers.js';

/**
 * Render a paper card element.
 * @param {object} paper  — paper object from store
 * @returns {HTMLElement}
 */
export function renderPaperCard(paper) {
  const card = document.createElement('div');
  card.className = 'paper-card';
  card.dataset.paperId = paper.paper_id;
  card.setAttribute('role', 'button');
  card.tabIndex = 0;

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
  if (needsMetadata(paper)) {
    badges.push('<span class="badge badge-warn" title="Missing authors/year — open to add">Needs metadata</span>');
  }
  if (paper.ocr_used) {
    const src = paper.parse_source || 'OCR';
    badges.push(`<span class="badge badge-ocr" title="Read via OCR — scanned PDF (${escapeHtml(src)})">OCR</span>`);
  }

  // Stance chips from stance_counts
  const sc = paper.stance_counts || {};
  const strengthens = sc.strengthens || 0;
  const challenges = sc.challenges || 0;
  const alternative = sc.alternative || 0;
  const stanceHtml = [
    strengthens > 0 ? `<span class="stance-chip stance-strengthens"${tip('strengthens')}>▲${strengthens}</span>` : '',
    challenges > 0  ? `<span class="stance-chip stance-challenges"${tip('challenges')}>⚡${challenges}</span>` : '',
    alternative > 0 ? `<span class="stance-chip stance-alternative"${tip('alternative')}>◆${alternative}</span>` : '',
  ].filter(Boolean).join('');

  const isFailed = paper.status === 'failed';
  const bandLabel = isFailed
    ? 'failed'
    : (paper.strength ? paper.strength.band : (paper.status === 'processing' ? 'processing' : 'unscored'));

  // Failed status chip gets the full (untruncated) reason as a hover tooltip;
  // the muted line under the title gets the short, truncated version so a
  // long error message can't blow out the card layout.
  const chipTitleAttr = isFailed && paper.failure_reason
    ? ` title="${escapeHtml(paper.failure_reason)}"`
    : '';
  const strengthChipHtml = isFailed
    ? `<span class="strength-badge" style="color:${borderColor}"${chipTitleAttr}>${escapeHtml(bandLabel)}</span>`
    : `<span class="strength-badge" style="color:${borderColor}"${tip('strength')}>${escapeHtml(bandLabel)}</span>`;

  card.innerHTML = `
    <div class="paper-card-body">
      <div class="paper-title">${escapeHtml(paper.title || 'Untitled')}</div>
      <div class="paper-meta muted">${escapeHtml(authorsLine(paper.authors || [], paper.year))}</div>
      <div class="paper-badges">
        ${badges.join('')}
        ${stanceHtml}
        ${strengthChipHtml}
      </div>
      ${isFailed && paper.failure_reason
        ? `<div class="failure-reason muted" title="${escapeHtml(paper.failure_reason)}">${escapeHtml(formatFailureReason(paper.failure_reason))}</div>`
        : ''}
      <div class="card-actions">
        ${paper.status === 'failed'
          ? `<button class="btn btn-sm btn-retry" data-paper-id="${escapeHtml(paper.paper_id)}">Retry</button>`
          : `<button class="btn btn-sm btn-read" data-paper-id="${escapeHtml(paper.paper_id)}">Read</button>`}
        <button class="btn btn-sm btn-remove" data-paper-id="${escapeHtml(paper.paper_id)}">Remove</button>
      </div>
    </div>
  `;

  return card;
}
