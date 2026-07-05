/**
 * views/library.js — Library view: card grid, filters, drawer details.
 */

import * as api from '../api.js';
import * as store from '../store.js';
import { renderPaperCard } from '../components/paperCard.js';
import { open as drawerOpen, close as drawerClose } from '../components/drawer.js';
import { showToast } from '../components/toast.js';
import { strengthColor, stanceIcon, escapeHtml, authorsLine } from '../format.js';
import { openModal } from '../components/ingestModal.js';

let _el = null;
let _unsubscribe = null;
let _filter = 'all';
let _sort = 'added';

export function mount(el) {
  _el = el;
  _render();
  _unsubscribe = store.subscribe('papers', () => _renderGrid());
}

export function unmount() {
  if (_unsubscribe) { _unsubscribe(); _unsubscribe = null; }
  drawerClose();
  _el = null;
}

// ---------------------------------------------------------------------------
// Full render (called once on mount)
// ---------------------------------------------------------------------------

function _render() {
  if (!_el) return;
  _el.innerHTML = `
    <div class="library-header">
      <div class="library-add-row">
        <input id="lib-add-input" class="add-input" type="text"
               placeholder="arXiv ID, URL, or PDF path..." autocomplete="off">
        <button id="lib-add-btn" class="btn btn-accent">Add</button>
        <button id="lib-ingest-btn" class="btn btn-secondary">Ingest folder...</button>
      </div>
      <div class="filter-chips" id="lib-filters">
        <button class="chip chip-active" data-filter="all">All</button>
        <button class="chip" data-filter="strong">Strong</button>
        <button class="chip" data-filter="moderate">Moderate</button>
        <button class="chip" data-filter="weak">Weak</button>
        <button class="chip" data-filter="unscored">Unscored</button>
        <button class="chip" data-filter="failed">Failed</button>
      </div>
      <div class="sort-row">
        <label for="lib-sort" class="muted">Sort by:</label>
        <select id="lib-sort">
          <option value="added">Added</option>
          <option value="strength">Strength</option>
          <option value="title">Title</option>
        </select>
      </div>
    </div>
    <div id="lib-grid" class="paper-grid"></div>
  `;

  // Wire filter chips
  _el.querySelector('#lib-filters').addEventListener('click', (e) => {
    const chip = e.target.closest('[data-filter]');
    if (!chip) return;
    _filter = chip.dataset.filter;
    _el.querySelectorAll('.chip').forEach(c => c.classList.remove('chip-active'));
    chip.classList.add('chip-active');
    _renderGrid();
  });

  // Wire sort
  _el.querySelector('#lib-sort').addEventListener('change', (e) => {
    _sort = e.target.value;
    _renderGrid();
  });

  // Wire add button
  _el.querySelector('#lib-add-btn').addEventListener('click', _handleAdd);
  _el.querySelector('#lib-add-input').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') _handleAdd();
  });

  // Wire ingest button -> modal
  _el.querySelector('#lib-ingest-btn').addEventListener('click', () => {
    openModal('folder');
  });

  _renderGrid();
}

// ---------------------------------------------------------------------------
// Add handler
// ---------------------------------------------------------------------------

async function _handleAdd() {
  if (!_el) return;
  const input = _el.querySelector('#lib-add-input');
  const target = (input.value || '').trim();
  if (!target) return;

  try {
    const res = await api.addPaper(target);
    input.value = '';
    showToast(`Adding paper — job ${res.job_id}`, 'info');
  } catch (err) {
    showToast(`Failed to add paper: ${err.message}`, 'error');
  }
}

// ---------------------------------------------------------------------------
// Grid render
// ---------------------------------------------------------------------------

function _renderGrid() {
  if (!_el) return;
  const grid = _el.querySelector('#lib-grid');
  if (!grid) return;

  const state = store.getState();
  let papers = [...state.papers.values()];

  // Filter
  if (_filter !== 'all') {
    papers = papers.filter(p => {
      if (_filter === 'failed') return p.status === 'failed';
      const band = p.strength ? p.strength.band : null;
      if (_filter === 'unscored') return !band || p.status === 'processing';
      return band === _filter;
    });
  }

  // Sort
  papers.sort((a, b) => {
    if (_sort === 'strength') {
      const ORDER = { strong: 0, moderate: 1, weak: 2, unscored: 3, failed: 4 };
      const aBand = a.strength ? a.strength.band : 'unscored';
      const bBand = b.strength ? b.strength.band : 'unscored';
      return (ORDER[aBand] ?? 99) - (ORDER[bBand] ?? 99);
    }
    if (_sort === 'title') {
      return (a.title || '').localeCompare(b.title || '');
    }
    // default: added order (Map insertion order preserved)
    return 0;
  });

  grid.innerHTML = '';

  if (papers.length === 0) {
    grid.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">📚</div>
        <div class="empty-title">Drop your research into the lab</div>
        <div class="empty-sub muted">Add a paper with an arXiv ID, URL, or PDF path to get started.</div>
        <div class="empty-actions">
          <button class="btn btn-accent" id="empty-add-btn">+ Add paper</button>
          <button class="btn btn-secondary" id="empty-ingest-btn">Ingest folder...</button>
        </div>
      </div>
    `;
    grid.querySelector('#empty-add-btn').addEventListener('click', () => {
      _el && _el.querySelector('#lib-add-input').focus();
    });
    grid.querySelector('#empty-ingest-btn').addEventListener('click', () => {
      openModal('folder');
    });
    return;
  }

  for (const paper of papers) {
    const card = renderPaperCard(paper);

    // Retry button
    const retryBtn = card.querySelector('.btn-retry');
    if (retryBtn) {
      retryBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        const pid = retryBtn.dataset.paperId;
        try {
          const res = await api.retryPaper(pid);
          showToast(`Retrying — job ${res.job_id}`, 'info');
        } catch (err) {
          showToast(`Retry failed: ${err.message}`, 'error');
        }
      });
    }

    // Remove button (on failed cards)
    const removeBtn = card.querySelector('.btn-remove');
    if (removeBtn) {
      removeBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        const pid = removeBtn.dataset.paperId;
        if (!confirm(`Remove paper ${pid}?`)) return;
        try {
          await api.deletePaper(pid);
          const s = store.getState();
          s.papers.delete(pid);
          store.notify(['papers']);
          showToast('Paper removed', 'info');
        } catch (err) {
          showToast(`Remove failed: ${err.message}`, 'error');
        }
      });
    }

    // Click card -> drawer
    card.addEventListener('click', (e) => {
      if (e.target.closest('button')) return;
      _openDrawer(paper.paper_id);
    });

    grid.appendChild(card);
  }
}

// ---------------------------------------------------------------------------
// Drawer
// ---------------------------------------------------------------------------

async function _openDrawer(paperId) {
  const state = store.getState();
  const paper = state.papers.get(paperId);
  if (!paper) return;

  const bandColor = paper.strength ? strengthColor(paper.strength.band) : strengthColor('unscored');
  const bandLabel = paper.strength ? paper.strength.band : 'unscored';
  const scoreText = paper.strength && paper.strength.score != null
    ? ` · score ${paper.strength.score.toFixed(2)}`
    : '';

  let alignHtml = '';
  let evidenceHtml = '';

  // Try to load alignment
  try {
    const alignment = await api.getPaperAlignment(paperId);
    const sections = alignment.sections || [];
    if (sections.length > 0) {
      alignHtml = `
        <div class="drawer-section">
          <div class="drawer-section-title">Section Alignment</div>
          ${sections.map(sec => `
            <div class="align-chip">
              <span class="stance-icon">${escapeHtml(stanceIcon(sec.relation))}</span>
              <span>${escapeHtml(sec.section_title || sec.section_id || '')}</span>
              <span class="muted">${sec.relevance != null ? (sec.relevance * 100).toFixed(0) + '%' : ''}</span>
            </div>
          `).join('')}
        </div>
      `;

      // Top 3 evidence quotes
      const allEvidence = [];
      for (const sec of sections) {
        for (const ev of (sec.evidence || [])) {
          allEvidence.push({ ...ev, section_title: sec.section_title });
        }
      }
      const top3 = allEvidence.slice(0, 3);
      if (top3.length > 0) {
        evidenceHtml = `
          <div class="drawer-section">
            <div class="drawer-section-title">Evidence</div>
            ${top3.map(ev => `
              <blockquote class="evidence-quote">
                <p>${escapeHtml(ev.quote || ev.text || '')}</p>
                <footer>
                  ${ev.verified
                    ? '<span class="badge badge-ok">✓ verified</span>'
                    : '<span class="badge badge-warn">unverified</span>'}
                  ${ev.section_title ? `<span class="muted">${escapeHtml(ev.section_title)}</span>` : ''}
                </footer>
              </blockquote>
            `).join('')}
          </div>
        `;
      }
    }
  } catch {
    // Alignment not available — no-op
  }

  const html = `
    <div class="drawer-header">
      <h2 class="drawer-title">${escapeHtml(paper.title || 'Untitled')}</h2>
      <div class="muted">${escapeHtml(authorsLine(paper.authors || [], paper.year))}</div>
    </div>

    <div class="strength-banner" style="border-left:4px solid ${bandColor}">
      <span class="strength-label" style="color:${bandColor}">${escapeHtml(bandLabel)}</span>
      <span class="muted">${escapeHtml(scoreText)}</span>
    </div>

    ${alignHtml}
    ${evidenceHtml}

    <div class="drawer-section drawer-actions">
      <div class="drawer-section-title">Actions</div>
      <button class="btn btn-secondary btn-full" id="drawer-set-draft">Set as draft</button>
      <button class="btn btn-secondary btn-full" id="drawer-compare">Compare with...</button>
      <button class="btn btn-secondary btn-full" id="drawer-show-graph">Show in graph</button>
      <button class="btn btn-danger btn-full" id="drawer-remove">Remove</button>
    </div>
  `;

  drawerOpen(html);

  // Wire drawer actions (they attach to #drawer-content)
  const content = document.getElementById('drawer-content');
  if (!content) return;

  content.querySelector('#drawer-set-draft').addEventListener('click', async () => {
    try {
      await api.setDraft(paperId);
      store.setDraft(paperId);
      showToast('Draft updated', 'info');
      drawerClose();
    } catch (err) {
      showToast(`Failed: ${err.message}`, 'error');
    }
  });

  content.querySelector('#drawer-compare').addEventListener('click', () => {
    drawerClose();
    window.location.hash = `#/compare?a=${encodeURIComponent(paperId)}`;
  });

  content.querySelector('#drawer-show-graph').addEventListener('click', () => {
    drawerClose();
    window.location.hash = '#/graph';
  });

  content.querySelector('#drawer-remove').addEventListener('click', async () => {
    if (!confirm(`Remove paper ${paperId}?`)) return;
    try {
      await api.deletePaper(paperId);
      const s = store.getState();
      s.papers.delete(paperId);
      store.notify(['papers']);
      drawerClose();
      showToast('Paper removed', 'info');
    } catch (err) {
      showToast(`Remove failed: ${err.message}`, 'error');
    }
  });
}
