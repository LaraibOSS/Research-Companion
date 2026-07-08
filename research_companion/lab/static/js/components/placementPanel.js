/**
 * components/placementPanel.js — Citation Placement panel.
 *
 * A draft-quality check, kept deliberately separate from paper strength scoring:
 * it flags whether cited papers sit in the section where the alignment engine
 * judges them most relevant ("cited in Methods, but most relevant to Related
 * Work"). Mounted ONCE from main.js. Fixed-right, non-modal.
 * Toggled by CustomEvent('rc:toggle-placement') + Esc/outside-click closes.
 */

import * as store from '../store.js';
import * as api from '../api.js';
import { showToast } from './toast.js';
import {
  placementCounts,
  statusChip,
  groupByStatus,
} from '../placementHelpers.js';
import { escapeHtml } from '../format.js';

// ---------------------------------------------------------------------------
// Panel state
// ---------------------------------------------------------------------------

let _panel = null;
let _open = false;
let _fetched = false;
let _apiRef = api;
let _storeRef = store;
let _unsubscribe = null;
let _updating = false;

// ---------------------------------------------------------------------------
// Exported mount
// ---------------------------------------------------------------------------

/**
 * Mount the placement panel once into document.body.
 * @param {object} storeRef — store module (injected for testability)
 * @param {object} apiRef   — api module (injected for testability)
 */
export function mountPlacementPanel(storeRef = store, apiRef = api) {
  if (_panel) return;

  _apiRef = apiRef;
  _storeRef = storeRef;

  _panel = document.createElement('div');
  _panel.id = 'placement-panel';
  _panel.className = 'citations-panel';   // reuse the citations panel styling
  _panel.setAttribute('aria-label', 'Citation placement panel');
  _panel.setAttribute('role', 'complementary');
  _render();
  document.body.appendChild(_panel);

  window.addEventListener('rc:toggle-placement', () => _toggle());

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && _open) _close();
  });

  document.addEventListener('mousedown', (e) => {
    if (_open && _panel && !_panel.contains(e.target)) _close();
  });

  _unsubscribe = storeRef.subscribe(['placement'], () => _render());
}

// ---------------------------------------------------------------------------
// Toggle / open / close
// ---------------------------------------------------------------------------

function _toggle() {
  if (_open) _close();
  else _openPanel();
}

function _openPanel() {
  _open = true;
  _panel.classList.add('open');
  if (!_fetched) {
    _fetched = true;
    _fetchAndUpdate();
  }
}

function _close() {
  _open = false;
  _panel.classList.remove('open');
}

// ---------------------------------------------------------------------------
// Fetch
// ---------------------------------------------------------------------------

async function _fetchAndUpdate() {
  _updating = true;
  try {
    const data = await _apiRef.getDraftPlacement();
    if (data) _storeRef.setCitationPlacement(data);
  } catch (err) {
    showToast('Failed to load citation placement', 'error');
    console.error('[placementPanel] fetch error', err);
  } finally {
    _updating = false;
    _render();
  }
}

// ---------------------------------------------------------------------------
// Render
// ---------------------------------------------------------------------------

function _render() {
  if (!_panel) return;
  const { citationPlacement } = _storeRef.getState();
  _panel.innerHTML = _buildHtml(citationPlacement);
  _bindEvents();
}

function _buildHtml(placement) {
  const counts = placementCounts(placement);
  const placements = placement && Array.isArray(placement.placements)
    ? placement.placements : [];

  const headerTitle = counts.total > 0
    ? `Citation placement — ${counts.misplaced} to review of ${counts.total}`
    : 'Citation placement';

  // Not applicable: numbered-bibliography scope note (honest, not a fake empty).
  const notApplicable = placement && placement.applicable === false;
  const reason = (placement && placement.reason) || '';

  let bodyHtml;
  if (notApplicable) {
    const msg = reason
      || 'Placement checking is not available for this draft.';
    bodyHtml = `<div class="citations-empty">${escapeHtml(msg)}</div>`;
  } else if (placements.length === 0) {
    bodyHtml = `<div class="citations-empty">${escapeHtml(
      'No numbered in-text citations found to check.')}</div>`;
  } else {
    bodyHtml = groupByStatus(placements).map(_renderRow).join('');
  }

  const scopeNote = (!notApplicable && counts.total > 0)
    ? `<div class="citations-note-muted">Compares where each paper is cited against where it's most relevant. This does not affect a paper's strength.</div>`
    : '';

  return `
    <div class="citations-header">
      <div class="citations-title-row">
        <span class="citations-title">${escapeHtml(headerTitle)}</span>
        <button class="placement-close btn btn-secondary btn-sm" aria-label="Close placement panel">&times;</button>
      </div>
      ${scopeNote}
    </div>
    <div class="citations-body">
      ${bodyHtml}
    </div>`;
}

function _renderRow(pl) {
  const chip = statusChip(pl.status);
  const title = pl.paper_title || pl.paper_id || '';
  const detail = pl.detail || '';
  // Cited-in draft sections get a Read affordance -> open the draft at that section.
  const citedSections = Array.isArray(pl.cited_sections) ? pl.cited_sections : [];
  const sectionLinks = citedSections
    .filter(cs => cs && cs.section_id)
    .map(cs => `<button class="draft-read-btn placement-read-section" data-section-id="${escapeHtml(cs.section_id)}" title="Read draft section: ${escapeHtml(cs.title || cs.section_id)}" aria-label="Read draft section">${escapeHtml(cs.title || cs.section_id)}</button>`)
    .join('');
  const sectionRow = sectionLinks
    ? `<div class="placement-read-row">${sectionLinks}</div>`
    : '';
  return `
    <div class="citation-row" title="${escapeHtml(detail)}">
      <div class="citation-row-main">
        <span class="citation-row-title">${escapeHtml(title)}</span>
        <span class="citation-row-detail">${escapeHtml(detail)}</span>
        ${sectionRow}
      </div>
      <div class="citation-row-meta">
        <span class="citation-chip ${escapeHtml(chip.cls)}">${escapeHtml(chip.label)}</span>
      </div>
    </div>`;
}

// ---------------------------------------------------------------------------
// Event binding
// ---------------------------------------------------------------------------

function _bindEvents() {
  if (!_panel) return;
  _panel.querySelector('.placement-close')?.addEventListener('click', _close);

  // Read a cited draft section -> open the draft in the reader at that section.
  _panel.querySelectorAll('.placement-read-section').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const { draftId } = _storeRef.getState();
      if (!draftId) return;
      window.dispatchEvent(new CustomEvent('rc:open-reader', {
        detail: { paperId: draftId, sectionId: btn.dataset.sectionId },
      }));
    });
  });
}
