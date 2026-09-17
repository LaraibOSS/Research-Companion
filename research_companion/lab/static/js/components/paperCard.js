/**
 * components/paperCard.js — renderPaperCard(paper) -> HTMLElement
 */

import { strengthColor, stanceIcon, authorsLine, escapeHtml } from '../format.js';
import { tip } from '../glossary.js';
import { needsMetadata, formatFailureReason, alignmentNoteModel } from '../libraryHelpers.js';
import { findPdfAffordance, oaLinksLine, acquisitionAllowsHelp } from '../oaLinkHelpers.js';
import { queueRowModel } from '../acquireHelpers.js';
import * as api from '../api.js';
import { showToast } from './toast.js';
import { buildNoteRecord } from '../noteRecord.js';

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
  // A paper alignment REFUSED to score (it has not been read), or scored
  // from the abstract alone, must not look like one scored on a full text.
  const alignNote = alignmentNoteModel(paper.alignment_note);
  if (alignNote.show) {
    badges.push(`<span class="badge ${alignNote.cls}" title="${escapeHtml(alignNote.title)}">${escapeHtml(alignNote.label)}</span>`);
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

  // "Find PDF" affordance (open-access locator) — rendered beside Upload PDF
  // for a failed, missing-PDF-on-disk paper; the muted links line only shows
  // once a prior search came back with a miss that still surfaced oa_links.
  const findPdfState = findPdfAffordance(paper);
  const oaLine = findPdfState === 'button-with-links'
    ? oaLinksLine(paper.oa_links)
    : { show: false, items: [] };
  const oaLinksHtml = oaLine.show
    ? `<div class="oa-links muted">Not freely available — try: ${oaLine.items
        .map(l => `<a href="${escapeHtml(l.url)}" target="_blank" rel="noopener">${escapeHtml(l.label)}</a>`)
        .join(', ')}</div>`
    : '';

  // "Needs you" queue row — a person, not a machine, has to get this one
  // (a bot filter refused an otherwise-open-access download, or the paper
  // is paywalled and only the user's own institutional access can get it).
  // Membership + copy come straight from queueRowModel (backend-computed
  // human_can_help; see acquireHelpers.js) — this never re-derives it.
  // When it applies, it REPLACES the generic failure-reason line below
  // (queueRow.headline is the same underlying copy, plus the fuller detail).
  const queueRow = queueRowModel(paper);
  const queueInfoHtml = queueRow.show
    ? `<div class="acquire-queue-info">
        <div class="acquire-headline">${escapeHtml(queueRow.headline)}</div>
        ${queueRow.detail ? `<div class="acquire-detail muted">${escapeHtml(queueRow.detail)}</div>` : ''}
      </div>`
    : '';

  card.innerHTML = `
    <div class="paper-card-body">
      <div class="paper-title">${escapeHtml(paper.title || 'Untitled')}</div>
      <div class="paper-meta muted">${escapeHtml(authorsLine(paper.authors || [], paper.year))}</div>
      <div class="paper-badges">
        ${badges.join('')}
        ${stanceHtml}
        ${strengthChipHtml}
      </div>
      ${queueRow.show
        ? queueInfoHtml
        : (isFailed && paper.failure_reason
            ? `<div class="failure-reason muted" title="${escapeHtml(paper.failure_reason)}">${escapeHtml(formatFailureReason(paper.failure_reason, paper.acquisition))}</div>`
            : '')}
      <div class="card-actions">
        ${paper.status === 'failed'
          ? `<button class="btn btn-sm btn-retry" data-paper-id="${escapeHtml(paper.paper_id)}">Retry</button>`
          : `<button class="btn btn-sm btn-read" data-paper-id="${escapeHtml(paper.paper_id)}">Read</button>`}
        ${paper.status === 'failed' && acquisitionAllowsHelp(paper.acquisition, paper.has_pdf)
          ? `<button class="btn btn-sm btn-upload-pdf" data-paper-id="${escapeHtml(paper.paper_id)}">Upload PDF</button>`
          : ''}
        ${findPdfState !== 'hidden'
          ? `<button class="btn btn-sm btn-find-pdf" data-paper-id="${escapeHtml(paper.paper_id)}">Find PDF</button>`
          : ''}
        ${queueRow.canOpen
          ? `<button class="btn btn-sm btn-open-publisher" data-paper-id="${escapeHtml(paper.paper_id)}" data-url="${escapeHtml(queueRow.openUrl)}">Open at publisher ↗</button>`
          : ''}
        <button class="btn btn-sm btn-save-note" data-paper-id="${escapeHtml(paper.paper_id)}">Save note</button>
        <button class="btn btn-sm btn-remove" data-paper-id="${escapeHtml(paper.paper_id)}">Remove</button>
      </div>
      ${oaLinksHtml}
    </div>
  `;

  // Save note -> POST /api/notes (kind 'paper'), then toast. Wired here
  // (rather than in views/library.js, which wires the OTHER card-actions
  // buttons) since this button needs no library-view state — just the
  // paper this card was rendered for.
  const saveNoteBtn = card.querySelector('.btn-save-note');
  if (saveNoteBtn) {
    saveNoteBtn.addEventListener('click', async (e) => {
      e.stopPropagation();
      // Paper notes carry no draft_section_id, so the server's (paper_id,
      // draft_section_id) dedupe never catches a rapid double-click here —
      // guard it client-side instead.
      if (saveNoteBtn.disabled) return;
      saveNoteBtn.disabled = true;
      try {
        await api.saveNote(buildNoteRecord('paper', {
          paperId: paper.paper_id,
          paperTitle: paper.title || paper.paper_id,
        }));
        showToast('Saved to Notes', 'info');
      } catch (err) {
        showToast(`Failed to save note: ${err.message}`, 'error');
      } finally {
        saveNoteBtn.disabled = false;
      }
    });
  }

  return card;
}
