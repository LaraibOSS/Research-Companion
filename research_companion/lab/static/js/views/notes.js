/**
 * views/notes.js — Full-page /notes route: a "notebook" over every saved
 * revision note (POST /api/notes, wired from Draft/Alignment/Reader/Paper/
 * Ask "Save note" affordances — see js/noteRecord.js + Task 3's four
 * call-sites).
 *
 * Each note is normalized via noteRowModel() (js/opportunityHelpers.js) —
 * applied internally by notesGroupModel() — so the kind badge, relation
 * badge, relevance percent, source excerpt and status all share the exact
 * same normalization Task 3/4 shipped. notesGroupModel(notes, groupBy)
 * groups the (already kind/status-filtered) notes by section or paper,
 * always sorting the 'Unfiled' group last.
 *
 * Features:
 *   - Group-by toggle: Section (default) / Paper.
 *   - Filter chips: kind (Alignment/Opportunity/Reader/Ask/Paper/Free-form/All)
 *     and status (Open default/Done/Dismissed/All), mirroring the
 *     Suggestions panel's chip pattern (components/suggestionsPanel.js).
 *   - New note: a small inline form (textarea + optional draft-section and
 *     paper pickers) -> buildNoteRecord('freeform', {...}) -> api.saveNote.
 *   - Export as Markdown -> GET /api/notes/export?group_by=<_groupBy> ->
 *     client-side .md download.
 *   - Evidence quote click -> rc:open-reader (opens the source paper) —
 *     only rendered when the note has both a paper and a quote.
 *   - Editable comment (blur -> PATCH /api/notes/{id} {comment}).
 *   - Status controls: Mark done / Dismiss / Reopen -> PATCH {status}.
 *   - Delete -> DELETE /api/notes/{id}.
 *
 * Route: #/notes
 */

import * as api from '../api.js';
import * as store from '../store.js';
import { showToast } from '../components/toast.js';
import { escapeHtml, timeAgo } from '../format.js';
import { notesGroupModel } from '../opportunityHelpers.js';
import { buildNoteRecord } from '../noteRecord.js';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const KIND_LABELS = {
  opportunity: 'Opportunity',
  alignment: 'Alignment',
  reader: 'Reader',
  paper: 'Paper',
  ask: 'Ask',
  freeform: 'Free-form',
};

// Kind filter chips, in display order — one chip per first-class note kind
// (js/noteRecord.js's KINDS), plus 'all' last.
const KIND_CHIPS = [
  { value: 'alignment', label: 'Alignment' },
  { value: 'opportunity', label: 'Opportunity' },
  { value: 'reader', label: 'Reader' },
  { value: 'ask', label: 'Ask' },
  { value: 'paper', label: 'Paper' },
  { value: 'freeform', label: 'Free-form' },
  { value: 'all', label: 'All' },
];

const STATUS_CHIPS = [
  { value: 'open', label: 'Open' },
  { value: 'done', label: 'Done' },
  { value: 'dismissed', label: 'Dismissed' },
  { value: 'all', label: 'All' },
];

// ---------------------------------------------------------------------------
// View state
// ---------------------------------------------------------------------------

let _el = null;
let _notes = [];        // raw note records from the server
let _rows = [];          // flat, index-aligned noteRowModel rows for the CURRENT
                          // (filtered + grouped) render — data-note-idx handlers
                          // look these up by position.
let _exporting = false;
let _loaded = false;

let _groupBy = 'section';    // 'section' | 'paper'
let _kindFilter = 'all';     // 'alignment'|'opportunity'|'reader'|'ask'|'freeform'|'all'
let _statusFilter = 'open';  // 'open'|'done'|'dismissed'|'all'

// New-note inline form
let _newNoteOpen = false;
let _newNoteSaving = false;
let _draftSections = [];     // [{section_id, title, ...}] — lazy-fetched, may stay []
let _sectionsFetched = false;

// ---------------------------------------------------------------------------
// mount / unmount
// ---------------------------------------------------------------------------

export function mount(el) {
  _el = el;
  _loaded = false;
  _render();
  _fetch();
}

export function unmount() {
  _el = null;
  _notes = [];
  _rows = [];
  _exporting = false;
  _loaded = false;
  _groupBy = 'section';
  _kindFilter = 'all';
  _statusFilter = 'open';
  _newNoteOpen = false;
  _newNoteSaving = false;
  _draftSections = [];
  _sectionsFetched = false;
}

// ---------------------------------------------------------------------------
// Fetch
// ---------------------------------------------------------------------------

async function _fetch() {
  try {
    const data = await api.getNotes();
    _notes = (data && Array.isArray(data.notes)) ? data.notes : [];
  } catch (err) {
    showToast('Failed to load notes', 'error');
    console.error('[notes view] fetch error', err);
    _notes = [];
  }
  _loaded = true;
  _render();
}

/** Lazy-fetch the current draft's sections for the New-note section picker.
 * Non-fatal: on any failure (no draft, network error) the picker is simply
 * omitted from the New-note form. */
async function _openNewNoteForm() {
  _newNoteOpen = true;
  _render();
  if (_sectionsFetched) return;
  _sectionsFetched = true;
  try {
    const data = await api.getDraftAlignment();
    _draftSections = (data && Array.isArray(data.sections)) ? data.sections : [];
  } catch {
    _draftSections = [];
  }
  if (_newNoteOpen) _render();
}

function _papersArray() {
  const { papers } = store.getState();
  if (!papers || typeof papers.values !== 'function') return [];
  return [...papers.values()];
}

// ---------------------------------------------------------------------------
// Filtering
// ---------------------------------------------------------------------------

/**
 * Filter raw note records by the current kind/status chips, BEFORE grouping.
 * @param {Array} notes
 * @returns {Array}
 */
function _filterNotes(notes) {
  return notes.filter((n) => {
    const safe = (n && typeof n === 'object') ? n : {};
    const kind = safe.kind != null ? String(safe.kind) : '';
    const status = safe.status != null ? String(safe.status) : 'open';
    const kindOk = _kindFilter === 'all' || kind === _kindFilter;
    const statusOk = _statusFilter === 'all' || status === _statusFilter;
    return kindOk && statusOk;
  });
}

// ---------------------------------------------------------------------------
// Render
// ---------------------------------------------------------------------------

function _render() {
  if (!_el) return;

  const filtered = _filterNotes(_notes);
  const groups = notesGroupModel(filtered, _groupBy);
  _rows = groups.flatMap((g) => g.rows);

  let idx = 0;
  const groupsHtml = groups.map((group) => {
    const cardsHtml = group.rows.map((row) => _renderCard(row, idx++)).join('');
    return `
      <div class="notes-group">
        <div class="notes-group-label">${escapeHtml(group.label)}</div>
        ${cardsHtml}
      </div>
    `;
  }).join('');

  let bodyHtml;
  if (!_loaded) {
    bodyHtml = '<div class="notes-empty muted">Loading notes…</div>';
  } else if (_notes.length === 0) {
    bodyHtml = '<div class="notes-empty muted">No notes yet — save suggestions from the Draft view.</div>';
  } else if (filtered.length === 0) {
    bodyHtml = '<div class="notes-empty muted">No notes match the current filters.</div>';
  } else {
    bodyHtml = groupsHtml;
  }

  _el.innerHTML = `
    <div class="notes-view">
      <div class="notes-header">
        <h2 class="notes-title">Notes</h2>
        <div class="notes-header-actions">
          <button class="btn btn-secondary notes-new-note-btn" type="button">${_newNoteOpen ? 'Close' : 'New note'}</button>
          <button class="btn btn-secondary notes-export-btn" type="button"${_exporting ? ' disabled' : ''}>
            ${_exporting ? 'Exporting…' : 'Export as Markdown'}
          </button>
        </div>
      </div>
      ${_newNoteOpen ? _renderNewNoteForm() : ''}
      <div class="notes-controls">
        <div class="notes-groupby-seg" role="group" aria-label="Group by">
          ${_groupByBtn('section', 'Section')}
          ${_groupByBtn('paper', 'Paper')}
        </div>
        <div class="notes-kind-chips filter-chips">
          ${KIND_CHIPS.map((c) => _chip('kind', c.value, c.label, _kindFilter)).join('')}
        </div>
        <div class="notes-status-chips filter-chips">
          ${STATUS_CHIPS.map((c) => _chip('status', c.value, c.label, _statusFilter)).join('')}
        </div>
      </div>
      <div class="notes-body">
        ${bodyHtml}
      </div>
    </div>
  `;
  _bindEvents();
}

function _groupByBtn(value, label) {
  const active = _groupBy === value ? ' active' : '';
  return `<button class="notes-groupby-btn${active}" type="button" data-groupby="${escapeHtml(value)}">${escapeHtml(label)}</button>`;
}

function _chip(kind, value, label, current) {
  const active = current === value ? ' chip-active' : '';
  const attr = kind === 'kind' ? 'data-kind' : 'data-status';
  return `<button class="chip${active}" type="button" ${attr}="${escapeHtml(value)}">${escapeHtml(label)}</button>`;
}

function _renderNewNoteForm() {
  const sections = _draftSections;
  const papersArr = _papersArray();

  const sectionPickerHtml = sections.length > 0 ? `
    <label class="notes-new-note-label muted" for="notes-new-note-section">Section (optional)</label>
    <select class="notes-new-note-section-select" id="notes-new-note-section">
      <option value="">— none —</option>
      ${sections.map((s) => `<option value="${escapeHtml(s.section_id)}">${escapeHtml(s.title || s.section_id)}</option>`).join('')}
    </select>
  ` : '';

  const paperPickerHtml = papersArr.length > 0 ? `
    <label class="notes-new-note-label muted" for="notes-new-note-paper">Paper (optional)</label>
    <select class="notes-new-note-paper-select" id="notes-new-note-paper">
      <option value="">— none —</option>
      ${papersArr.map((p) => `<option value="${escapeHtml(p.paper_id)}">${escapeHtml(p.title || p.paper_id)}</option>`).join('')}
    </select>
  ` : '';

  return `
    <div class="notes-new-note-form">
      <label class="notes-new-note-label muted" for="notes-new-note-textarea">Note</label>
      <textarea class="notes-new-note-textarea" id="notes-new-note-textarea" rows="3" placeholder="Add a note…" aria-label="Note text"></textarea>
      ${sectionPickerHtml}
      ${paperPickerHtml}
      <div class="notes-new-note-actions">
        <button type="button" class="btn btn-sm btn-accent notes-new-note-save"${_newNoteSaving ? ' disabled' : ''}>
          ${_newNoteSaving ? 'Saving…' : 'Save note'}
        </button>
        <button type="button" class="btn btn-sm btn-secondary notes-new-note-cancel">Cancel</button>
      </div>
    </div>
  `;
}

function _renderCard(m, idx) {
  const color = m.badgeColor;
  const icon = m.badgeIcon;
  const status = m.status;
  const kindLabel = KIND_LABELS[m.kind] || (m.kind ? m.kind : 'Note');

  // Evidence-quote -> Reader link: only when the note has BOTH a paper and a
  // quote (an ask/freeform note may carry a quote-less source_excerpt, or a
  // paper-less quote makes no sense to "open in source").
  const quoteHtml = (m.quote && m.paperId)
    ? `
      <button class="note-quote-btn" type="button" data-note-idx="${idx}" title="Open in source paper">
        <span class="note-quote-text">${escapeHtml(m.quote)}</span>
        <span class="ev-open-hint muted">&#8599; open in source</span>
      </button>
    `
    : '';

  const excerptHtml = m.sourceExcerpt
    ? `<p class="note-source-excerpt">${escapeHtml(m.sourceExcerpt)}</p>`
    : '';

  const paperTitleHtml = (m.paperTitle || m.paperId)
    ? `<div class="note-paper-title">${escapeHtml(m.paperTitle || m.paperId)}</div>`
    : '';

  const actionsHtml = `
    ${status === 'open' ? `<button class="btn btn-secondary btn-sm note-mark-done" data-note-idx="${idx}">Mark done</button>` : ''}
    ${status !== 'dismissed' ? `<button class="btn btn-secondary btn-sm note-dismiss" data-note-idx="${idx}">Dismiss</button>` : ''}
    ${status !== 'open' ? `<button class="btn btn-secondary btn-sm note-reopen" data-note-idx="${idx}">Reopen</button>` : ''}
    <button class="btn btn-secondary btn-sm btn-danger note-delete" data-note-idx="${idx}">Delete</button>
  `;

  return `
    <div class="note-card" data-note-idx="${idx}">
      <div class="note-card-header">
        <span class="note-kind-badge">${escapeHtml(kindLabel)}</span>
        <span class="note-badge" style="color:${escapeHtml(color)};border-color:${escapeHtml(color)}">${escapeHtml(icon)} ${escapeHtml(m.relation || 'note')}</span>
        <span class="note-relevance muted">${escapeHtml(String(m.relevancePct))}%</span>
        <span class="note-status-tag note-status-${escapeHtml(status)}">${escapeHtml(status)}</span>
      </div>
      ${paperTitleHtml}
      ${m.rationale ? `<p class="note-rationale">${escapeHtml(m.rationale)}</p>` : ''}
      ${excerptHtml}
      ${quoteHtml}
      <label class="note-comment-label muted" for="note-comment-${idx}">Comment</label>
      <textarea class="note-comment" id="note-comment-${idx}" data-note-idx="${idx}"
        placeholder="Add a comment…">${escapeHtml(m.comment)}</textarea>
      <div class="note-actions">${actionsHtml}</div>
      <div class="note-time muted">${escapeHtml(timeAgo(m.createdAt))}</div>
    </div>
  `;
}

// ---------------------------------------------------------------------------
// Event binding
// ---------------------------------------------------------------------------

function _bindEvents() {
  if (!_el) return;

  // Group-by toggle
  _el.querySelectorAll('.notes-groupby-seg [data-groupby]').forEach((btn) => {
    btn.addEventListener('click', () => {
      _groupBy = btn.dataset.groupby;
      _render();
    });
  });

  // Kind filter chips
  _el.querySelectorAll('.notes-kind-chips [data-kind]').forEach((btn) => {
    btn.addEventListener('click', () => {
      _kindFilter = btn.dataset.kind;
      _render();
    });
  });

  // Status filter chips
  _el.querySelectorAll('.notes-status-chips [data-status]').forEach((btn) => {
    btn.addEventListener('click', () => {
      _statusFilter = btn.dataset.status;
      _render();
    });
  });

  // New note toggle + form
  _el.querySelector('.notes-new-note-btn')?.addEventListener('click', () => {
    if (_newNoteOpen) {
      _newNoteOpen = false;
      _render();
    } else {
      _openNewNoteForm();
    }
  });
  _bindNewNoteForm();

  // Export as Markdown
  _el.querySelector('.notes-export-btn')?.addEventListener('click', async () => {
    if (_exporting) return;
    _exporting = true;
    _render();
    try {
      const data = await api.exportNotes(_groupBy);
      const markdown = (data && typeof data.markdown === 'string') ? data.markdown : '';
      _downloadMarkdown(markdown);
    } catch (err) {
      showToast('Failed to export notes', 'error');
      console.error('[notes view] export error', err);
    } finally {
      _exporting = false;
      _render();
    }
  });

  // Evidence quote -> open in reader
  _el.querySelectorAll('.note-quote-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      const idx = Number(btn.dataset.noteIdx);
      const row = _rows[idx];
      if (!row) return;
      window.dispatchEvent(new CustomEvent('rc:open-reader', {
        detail: { paperId: row.paperId, quote: row.quote },
      }));
    });
  });

  // Editable comment -> PATCH on blur
  _el.querySelectorAll('.note-comment').forEach((textarea) => {
    textarea.addEventListener('blur', async () => {
      const idx = Number(textarea.dataset.noteIdx);
      const row = _rows[idx];
      if (!row) return;
      const value = textarea.value;
      if (value === row.comment) return; // no change
      try {
        await api.updateNote(row.id, { comment: value });
        row.comment = value;
        const raw = _notes.find((n) => String(n.id) === row.id);
        if (raw) raw.comment = value;
      } catch (err) {
        showToast('Failed to save comment', 'error');
        console.error('[notes view] comment update error', err);
      }
    });
  });

  // Status controls
  _el.querySelectorAll('.note-mark-done').forEach((btn) => {
    btn.addEventListener('click', () => _updateStatus(btn, 'done'));
  });
  _el.querySelectorAll('.note-dismiss').forEach((btn) => {
    btn.addEventListener('click', () => _updateStatus(btn, 'dismissed'));
  });
  _el.querySelectorAll('.note-reopen').forEach((btn) => {
    btn.addEventListener('click', () => _updateStatus(btn, 'open'));
  });

  // Delete
  _el.querySelectorAll('.note-delete').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const idx = Number(btn.dataset.noteIdx);
      const row = _rows[idx];
      if (!row) return;
      try {
        await api.deleteNote(row.id);
        _notes = _notes.filter((n) => String(n.id) !== row.id);
        _render();
      } catch (err) {
        showToast('Failed to delete note', 'error');
        console.error('[notes view] delete error', err);
      }
    });
  });
}

function _bindNewNoteForm() {
  if (!_newNoteOpen) return;
  const form = _el.querySelector('.notes-new-note-form');
  if (!form) return;

  const textarea = form.querySelector('.notes-new-note-textarea');
  textarea?.focus();

  form.querySelector('.notes-new-note-cancel')?.addEventListener('click', () => {
    _newNoteOpen = false;
    _render();
  });

  form.querySelector('.notes-new-note-save')?.addEventListener('click', async () => {
    if (_newNoteSaving) return;
    const comment = ((textarea && textarea.value) || '').trim();
    if (!comment) {
      showToast('Note text is required', 'error');
      return;
    }

    const sectionSelect = form.querySelector('.notes-new-note-section-select');
    const paperSelect = form.querySelector('.notes-new-note-paper-select');
    const sectionId = (sectionSelect && sectionSelect.value) || '';
    const sectionTitle = sectionId
      ? ((_draftSections.find((s) => s.section_id === sectionId) || {}).title || sectionId)
      : '';
    const paperId = (paperSelect && paperSelect.value) || '';
    const paperTitle = paperId
      ? ((_papersArray().find((p) => p.paper_id === paperId) || {}).title || paperId)
      : '';

    const saveBtn = form.querySelector('.notes-new-note-save');
    if (saveBtn) { saveBtn.disabled = true; saveBtn.textContent = 'Saving…'; }
    _newNoteSaving = true;
    try {
      await api.saveNote(buildNoteRecord('freeform', {
        comment, sectionId, sectionTitle, paperId, paperTitle,
      }));
      showToast('Saved to Notes', 'info');
      _newNoteOpen = false;
      _newNoteSaving = false;
      await _fetch(); // refetch + re-render (also hides the form)
      return;
    } catch (err) {
      showToast('Failed to save note', 'error');
      console.error('[notes view] new-note save error', err);
      if (saveBtn) { saveBtn.disabled = false; saveBtn.textContent = 'Save note'; }
    }
    _newNoteSaving = false;
  });
}

async function _updateStatus(btn, status) {
  const idx = Number(btn.dataset.noteIdx);
  const row = _rows[idx];
  if (!row) return;
  try {
    await api.updateNote(row.id, { status });
    const raw = _notes.find((n) => String(n.id) === row.id);
    if (raw) raw.status = status;
    _render();
  } catch (err) {
    showToast('Failed to update note', 'error');
    console.error('[notes view] status update error', err);
  }
}

// ---------------------------------------------------------------------------
// Export helper
// ---------------------------------------------------------------------------

function _downloadMarkdown(markdown) {
  const blob = new Blob([markdown], { type: 'text/markdown' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'revision-notes.md';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
