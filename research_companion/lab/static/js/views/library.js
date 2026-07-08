/**
 * views/library.js — Library view: card grid + list toggle, filters, drawer details.
 */

import * as api from '../api.js';
import * as store from '../store.js';
import { renderPaperCard } from '../components/paperCard.js';
import { open as drawerOpen, close as drawerClose } from '../components/drawer.js';
import { showToast } from '../components/toast.js';
import { strengthColor, stanceIcon, escapeHtml, authorsLine, timeAgo } from '../format.js';
import { openModal } from '../components/ingestModal.js';
import { buildRows, sortRows, draftActionFor } from '../libraryHelpers.js';
import { buildPaperPatch } from '../metadataForm.js';

let _el = null;
let _unsubscribe = null;
let _filter = 'all';
let _sort = 'added';
let _openPaperHandler = null; // rc:open-paper listener (kept for unmount cleanup)

// List-view state
let _viewMode   = localStorage.getItem('rc.libraryView') || 'grid'; // 'grid' | 'list'
let _listCol    = 'added';
let _listDir    = 'desc';

export function mount(el) {
  _el = el;
  _render();
  _unsubscribe = store.subscribe(['papers', 'draft'], () => _renderGrid());

  // Listen for paper-source link clicks from the suggestions panel / view.
  // The panel also sets window.__rcPendingPaper before dispatching the event
  // as a fallback in case the event fires before this listener is registered.
  _openPaperHandler = (e) => {
    const paperId = e.detail && e.detail.paperId;
    if (paperId) _openDrawer(paperId);
  };
  window.addEventListener('rc:open-paper', _openPaperHandler);

  // Check the module-level handoff written by the panel before navigating —
  // handles the arrive-before-mount race (hash change triggers mount after event).
  if (window.__rcPendingPaper) {
    const pendingId = window.__rcPendingPaper;
    window.__rcPendingPaper = null;
    // Defer until after first render so the papers grid is in the DOM
    Promise.resolve().then(() => _openDrawer(pendingId));
  }
}

export function unmount() {
  if (_unsubscribe) { _unsubscribe(); _unsubscribe = null; }
  if (_openPaperHandler) {
    window.removeEventListener('rc:open-paper', _openPaperHandler);
    _openPaperHandler = null;
  }
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
        <div class="lib-view-toggle" role="group" aria-label="View mode">
          <button class="lib-view-btn${_viewMode === 'grid' ? ' lib-view-btn-active' : ''}"
                  id="lib-view-grid" title="Grid view" aria-pressed="${_viewMode === 'grid'}">⊞</button>
          <button class="lib-view-btn${_viewMode === 'list' ? ' lib-view-btn-active' : ''}"
                  id="lib-view-list" title="List view" aria-pressed="${_viewMode === 'list'}">☰</button>
        </div>
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

  // Wire view toggle buttons
  _el.querySelector('#lib-view-grid').addEventListener('click', () => {
    _viewMode = 'grid';
    localStorage.setItem('rc.libraryView', 'grid');
    _render();
  });
  _el.querySelector('#lib-view-list').addEventListener('click', () => {
    _viewMode = 'list';
    localStorage.setItem('rc.libraryView', 'list');
    _render();
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
// Shared remove flow (grid cards, list rows, drawer)
// ---------------------------------------------------------------------------

/**
 * Confirm + delete a paper, update the store, and toast the outcome.
 * @param {string} paperId
 * @param {{ onSuccess?: () => void }} [opts] — e.g. close the drawer
 */
async function removePaperFlow(paperId, { onSuccess } = {}) {
  if (!confirm(`Remove paper ${paperId}?`)) return;
  try {
    const res = await api.deletePaper(paperId);
    const s = store.getState();
    s.papers.delete(paperId);
    if (res && res.draft_cleared === true) store.setDraft(null);
    store.notify(['papers']);
    if (onSuccess) onSuccess();
    showToast('Paper removed', 'info');
  } catch (err) {
    showToast(`Remove failed: ${err.message}`, 'error');
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

  if (papers.length === 0) {
    grid.className = 'paper-grid';
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

  if (_viewMode === 'list') {
    _renderList(grid, papers, state.draftId);
  } else {
    _renderGridCards(grid, papers);
  }
}

// ---------------------------------------------------------------------------
// Grid cards (original view)
// ---------------------------------------------------------------------------

function _renderGridCards(grid, papers) {
  grid.className = 'paper-grid';

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

    // Read button -> open the paper in the reader.
    const readBtn = card.querySelector('.btn-read');
    if (readBtn) {
      readBtn.addEventListener('click', (e) => {
        e.stopPropagation();  // don't open the drawer
        window.dispatchEvent(new CustomEvent('rc:open-reader', {
          detail: { paperId: paper.paper_id, title: paper.title },
        }));
      });
    }

    // Remove button (on all cards)
    const removeBtn = card.querySelector('.btn-remove');
    if (removeBtn) {
      removeBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        removePaperFlow(removeBtn.dataset.paperId);
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
// List table view
// ---------------------------------------------------------------------------

const _LIST_COLS = [
  { key: 'title',    label: 'Title' },
  { key: 'year',     label: 'Year' },
  { key: 'status',   label: 'Status' },
  { key: 'strength', label: 'Strength' },
  { key: 'relation', label: 'Relation' },
  { key: 'added',    label: 'Added' },
];

const STANCE_ICONS = { strengthens: '▲', challenges: '⚡', alternative: '◆' };

function _statusPillHtml(status) {
  const cls = `lib-status-pill lib-status-pill-${escapeHtml(status)}`;
  return `<span class="${cls}">${escapeHtml(status)}</span>`;
}

function _renderList(grid, papers, draftId) {
  grid.className = 'lib-table-wrap';

  const rows = sortRows(buildRows(papers, draftId), _listCol, _listDir);

  const headerCells = _LIST_COLS.map(({ key, label }) => {
    const isActive = key === _listCol;
    const arrow = isActive ? ((_listDir === 'asc') ? ' ▲' : ' ▼') : '';
    return `<th class="lib-th${isActive ? ' lib-th-active' : ''}" data-col="${escapeHtml(key)}" role="columnheader" aria-sort="${isActive ? (_listDir === 'asc' ? 'ascending' : 'descending') : 'none'}">${escapeHtml(label)}${arrow}</th>`;
  }).join('') + '<th class="lib-th lib-th-actions" role="columnheader" aria-label="Actions"></th>';

  const rowsHtml = rows.map(row => {
    const draftBadge = row.isDraft ? '<span class="badge badge-draft">★ DRAFT</span> ' : '';
    const strengthTxt = row.strengthBand
      ? escapeHtml(row.strengthBand) + (row.strengthScore != null ? ` (${row.strengthScore.toFixed(2)})` : '')
      : '<span class="muted">—</span>';
    const relationIcon = row.relation ? (STANCE_ICONS[row.relation] || '') : '';
    const relationTxt  = row.relation
      ? `${escapeHtml(relationIcon)} ${escapeHtml(row.relation)}`
      : '<span class="muted">—</span>';
    const addedTxt = row.addedAt ? escapeHtml(timeAgo(row.addedAt)) : '<span class="muted">—</span>';
    const yearTxt  = row.year ? escapeHtml(String(row.year)) : '<span class="muted">—</span>';

    // Failure indicator
    const failureAttr  = row.failureReason ? ` title="${escapeHtml(row.failureReason)}"` : '';
    const retryBtnHtml = row.status === 'failed'
      ? `<button class="btn btn-sm btn-retry lib-retry-btn" data-paper-id="${escapeHtml(row.paperId)}">Retry</button>`
      : '';

    // Missing-metadata pill — opens the drawer straight into edit mode.
    const metadataPillHtml = row.needsMetadata
      ? ` <button class="lib-status-pill lib-status-pill-metadata lib-meta-btn" data-paper-id="${escapeHtml(row.paperId)}" title="Missing authors/year — click to add">Needs metadata</button>`
      : '';

    return `<tr class="lib-row lib-row-${escapeHtml(row.status)}" data-paper-id="${escapeHtml(row.paperId)}"${failureAttr}>
      <td class="lib-td lib-td-title">${draftBadge}${escapeHtml(row.title)}${metadataPillHtml}${retryBtnHtml}</td>
      <td class="lib-td lib-td-year">${yearTxt}</td>
      <td class="lib-td lib-td-status">${_statusPillHtml(row.status)}</td>
      <td class="lib-td lib-td-strength">${strengthTxt}</td>
      <td class="lib-td lib-td-relation">${relationTxt}</td>
      <td class="lib-td lib-td-added">${addedTxt}</td>
      <td class="lib-td lib-td-actions"><button class="btn btn-sm btn-row-read" data-paper-id="${escapeHtml(row.paperId)}" data-title="${escapeHtml(row.title || '')}" title="Read" aria-label="Read paper">Read</button><button class="btn-icon btn-row-remove" data-paper-id="${escapeHtml(row.paperId)}" title="Remove" aria-label="Remove paper">&#128465;</button></td>
    </tr>`;
  }).join('');

  grid.innerHTML = `
    <table class="lib-table" role="grid">
      <thead>
        <tr>${headerCells}</tr>
      </thead>
      <tbody>
        ${rowsHtml}
      </tbody>
    </table>
  `;

  // Wire sortable headers
  grid.querySelectorAll('.lib-th[data-col]').forEach(th => {
    th.addEventListener('click', () => {
      const col = th.dataset.col;
      if (col === _listCol) {
        _listDir = _listDir === 'asc' ? 'desc' : 'asc';
      } else {
        _listCol = col;
        _listDir = 'asc';
      }
      _renderGrid();
    });
  });

  // Wire row clicks -> drawer
  grid.querySelectorAll('.lib-row').forEach(row => {
    row.addEventListener('click', (e) => {
      if (e.target.closest('button')) return;
      _openDrawer(row.dataset.paperId);
    });
  });

  // Wire retry buttons in list
  grid.querySelectorAll('.lib-retry-btn').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const pid = btn.dataset.paperId;
      try {
        const res = await api.retryPaper(pid);
        showToast(`Retrying — job ${res.job_id}`, 'info');
      } catch (err) {
        showToast(`Retry failed: ${err.message}`, 'error');
      }
    });
  });

  // Wire per-row read buttons -> open the paper in the reader.
  grid.querySelectorAll('.btn-row-read').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();  // don't open the drawer
      window.dispatchEvent(new CustomEvent('rc:open-reader', {
        detail: { paperId: btn.dataset.paperId, title: btn.dataset.title || undefined },
      }));
    });
  });

  // Wire per-row remove buttons
  grid.querySelectorAll('.btn-row-remove').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      removePaperFlow(btn.dataset.paperId);
    });
  });

  // Wire "Needs metadata" pills -> open drawer straight into edit mode
  grid.querySelectorAll('.lib-meta-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      _openDrawer(btn.dataset.paperId, { edit: true });
    });
  });
}

// ---------------------------------------------------------------------------
// Drawer
// ---------------------------------------------------------------------------

async function _openDrawer(paperId, { edit = false } = {}) {
  const state = store.getState();
  const paper = state.papers.get(paperId);
  if (!paper) return;

  // Fresh drawer render clears any prior in-progress edit (prevents a stuck
  // guard if the drawer was closed mid-edit via the overlay/close button).
  _metaEditing = false;

  const draftAction = draftActionFor(paperId, state.draftId);

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
    <div class="drawer-header" id="drawer-meta-header">
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
      <button class="btn btn-secondary btn-full" id="drawer-edit-meta">Edit metadata</button>
      <button class="btn btn-secondary btn-full" id="drawer-set-draft">${escapeHtml(draftAction.label)}</button>
      <button class="btn btn-secondary btn-full" id="drawer-read">Read</button>
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
      await api.setDraft(draftAction.next);
      store.setDraft(draftAction.next);
      showToast(draftAction.toast, 'info');
      drawerClose();
    } catch (err) {
      showToast(`Failed: ${err.message}`, 'error');
    }
  });

  content.querySelector('#drawer-read').addEventListener('click', () => {
    window.dispatchEvent(new CustomEvent('rc:open-reader', {
      detail: { paperId, title: paper.title },
    }));
    drawerClose();
  });

  content.querySelector('#drawer-compare').addEventListener('click', () => {
    drawerClose();
    window.location.hash = `#/compare?a=${encodeURIComponent(paperId)}`;
  });

  content.querySelector('#drawer-show-graph').addEventListener('click', () => {
    drawerClose();
    window.location.hash = '#/graph';
  });

  content.querySelector('#drawer-remove').addEventListener('click', () => {
    removePaperFlow(paperId, { onSuccess: drawerClose });
  });

  const editBtn = content.querySelector('#drawer-edit-meta');
  if (editBtn) {
    editBtn.addEventListener('click', () => _startMetadataEdit(paperId));
  }

  // Optionally open straight into edit mode (from the "Needs metadata" pill).
  if (edit) _startMetadataEdit(paperId);
}

// ---------------------------------------------------------------------------
// Drawer inline metadata edit form
// ---------------------------------------------------------------------------

let _metaEditing = false; // one edit at a time; guards re-entry

/**
 * Swap the drawer header into an inline Title / Authors / Year form.
 * Save calls PATCH /api/papers/{id}; Cancel/Escape restore the header.
 */
function _startMetadataEdit(paperId) {
  if (_metaEditing) return;
  const state = store.getState();
  const paper = state.papers.get(paperId);
  if (!paper) return;

  const header = document.getElementById('drawer-meta-header');
  if (!header) return;
  _metaEditing = true;

  const originalHtml = header.innerHTML;
  const authorsStr = (paper.authors || []).join(', ');
  const yearVal = paper.year != null ? String(paper.year) : '';

  header.innerHTML = `
    <form class="drawer-meta-form" novalidate>
      <label class="drawer-meta-field">
        <span class="drawer-meta-label">Title</span>
        <input type="text" id="meta-title" class="drawer-meta-input"
               value="${escapeHtml(paper.title || '')}" autocomplete="off">
      </label>
      <label class="drawer-meta-field">
        <span class="drawer-meta-label">Authors <span class="muted">(comma-separated)</span></span>
        <input type="text" id="meta-authors" class="drawer-meta-input"
               value="${escapeHtml(authorsStr)}" autocomplete="off">
      </label>
      <label class="drawer-meta-field">
        <span class="drawer-meta-label">Year</span>
        <input type="number" id="meta-year" class="drawer-meta-input"
               min="1900" max="2100" step="1" value="${escapeHtml(yearVal)}" autocomplete="off">
      </label>
      <div class="drawer-meta-error" id="meta-error" role="alert"></div>
      <div class="drawer-meta-actions">
        <button type="submit" class="btn btn-accent btn-sm" id="meta-save">Save</button>
        <button type="button" class="btn btn-secondary btn-sm" id="meta-cancel">Cancel</button>
      </div>
    </form>
  `;

  const form      = header.querySelector('.drawer-meta-form');
  const titleEl   = header.querySelector('#meta-title');
  const authorsEl = header.querySelector('#meta-authors');
  const yearEl    = header.querySelector('#meta-year');
  const errorEl   = header.querySelector('#meta-error');
  if (titleEl) { titleEl.focus(); titleEl.select(); }

  let done = false; // guard: submit + async can race
  const restore = () => {
    _metaEditing = false;
    if (header) header.innerHTML = originalHtml;
  };
  const cancel = () => {
    if (done) return;
    done = true;
    restore();
  };

  const save = async () => {
    if (done) return;
    const result = buildPaperPatch({
      title:      titleEl ? titleEl.value : '',
      authorsStr: authorsEl ? authorsEl.value : '',
      yearStr:    yearEl ? yearEl.value : '',
    });
    if (result.error) {
      if (errorEl) errorEl.textContent = result.error;
      showToast(result.error, 'error');
      return; // keep the form open
    }
    done = true;
    try {
      const updated = await api.patchPaper(paperId, result.body);
      // Splice the returned full dict back into the store and re-render.
      const s = store.getState();
      s.papers.set(updated.paper_id, { ...s.papers.get(updated.paper_id), ...updated });
      store.notify(['papers']);
      showToast('Metadata updated', 'info');
      _metaEditing = false;
      // Re-open the drawer to reflect fresh values (header + banners refresh).
      _openDrawer(updated.paper_id);
    } catch (err) {
      done = false; // allow retry
      if (errorEl) errorEl.textContent = err.message;
      showToast(err.message, 'error');
    }
  };

  if (form) {
    form.addEventListener('submit', (e) => { e.preventDefault(); save(); });
  }
  header.querySelector('#meta-cancel').addEventListener('click', cancel);

  // Escape cancels the edit without closing the whole drawer. Bound to the
  // FORM (not the persistent header) so the listener is discarded along
  // with it when cancel()/save()/restore() replace header.innerHTML — a
  // listener on the header itself would outlive the edit and keep calling
  // stopPropagation() on every later Escape, permanently blocking the
  // drawer's document-level Escape-to-close (and stacking on repeat edits).
  if (form) {
    form.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        cancel();
      }
    });
  }
}
