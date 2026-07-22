/**
 * views/notes.js — Full-page /notes route.
 *
 * Lists every saved revision note (POST /api/notes, wired from the Draft
 * view's "Save note" button — see views/draft.js), grouped by the draft
 * section they were captured against. Each note row is built from
 * noteRowModel() (js/opportunityHelpers.js) so the relation badge, relevance
 * percent, and status all share the exact same normalization Task 3 already
 * shipped for the Draft-view opportunities block.
 *
 * Features:
 *   - Export as Markdown -> GET /api/notes/export -> client-side .md download.
 *   - Evidence quote click -> rc:open-reader (opens the source paper).
 *   - Editable comment (blur -> PATCH /api/notes/{id} {comment}).
 *   - Status controls: Mark done / Dismiss / Reopen -> PATCH {status}.
 *   - Delete -> DELETE /api/notes/{id}.
 *
 * Route: #/notes
 */

import * as api from '../api.js';
import { showToast } from '../components/toast.js';
import { escapeHtml, timeAgo } from '../format.js';
import { noteRowModel } from '../opportunityHelpers.js';

// ---------------------------------------------------------------------------
// View state
// ---------------------------------------------------------------------------

let _el = null;
let _notes = [];       // raw note records from the server
let _rows = [];         // noteRowModel(...) output, index-aligned registry for handlers
let _exporting = false;
let _loaded = false;

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

// ---------------------------------------------------------------------------
// Grouping
// ---------------------------------------------------------------------------

/**
 * Group noteRowModel rows by sectionTitle, preserving first-seen order.
 * @param {Array} rows — noteRowModel() output
 * @returns {Array<{sectionTitle: string, indices: number[]}>}
 */
function _groupBySection(rows) {
  const order = [];
  const bySection = new Map();
  rows.forEach((row, idx) => {
    const key = row.sectionTitle || row.sectionId || 'Ungrouped';
    if (!bySection.has(key)) {
      bySection.set(key, []);
      order.push(key);
    }
    bySection.get(key).push(idx);
  });
  return order.map(key => ({ sectionTitle: key, indices: bySection.get(key) }));
}

// ---------------------------------------------------------------------------
// Render
// ---------------------------------------------------------------------------

function _render() {
  if (!_el) return;
  _rows = _notes.map(noteRowModel);
  const groups = _groupBySection(_rows);

  _el.innerHTML = `
    <div class="notes-view">
      <div class="notes-header">
        <h2 class="notes-title">Notes</h2>
        <button class="btn btn-secondary notes-export-btn" type="button"${_exporting ? ' disabled' : ''}>
          ${_exporting ? 'Exporting…' : 'Export as Markdown'}
        </button>
      </div>
      <div class="notes-body">
        ${!_loaded
          ? '<div class="notes-empty muted">Loading notes…</div>'
          : (_rows.length === 0
              ? '<div class="notes-empty muted">No notes yet — save suggestions from the Draft view.</div>'
              : groups.map(_renderGroup).join(''))}
      </div>
    </div>
  `;
  _bindEvents();
}

function _renderGroup(group) {
  return `
    <div class="notes-group">
      <div class="notes-group-label">${escapeHtml(group.sectionTitle)}</div>
      ${group.indices.map(idx => _renderCard(idx)).join('')}
    </div>
  `;
}

function _renderCard(idx) {
  const m = _rows[idx];
  const color = m.badgeColor;
  const icon = m.badgeIcon;
  const status = m.status;

  const quoteHtml = m.quote
    ? `
      <button class="note-quote-btn" type="button" data-note-idx="${idx}" title="Open in source paper">
        <span class="note-quote-text">${escapeHtml(m.quote)}</span>
        <span class="ev-open-hint muted">&#8599; open in source</span>
      </button>
    `
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
        <span class="note-badge" style="color:${escapeHtml(color)};border-color:${escapeHtml(color)}">${escapeHtml(icon)} ${escapeHtml(m.relation || 'note')}</span>
        <span class="note-relevance muted">${escapeHtml(String(m.relevancePct))}%</span>
        <span class="note-status-tag note-status-${escapeHtml(status)}">${escapeHtml(status)}</span>
      </div>
      <div class="note-paper-title">${escapeHtml(m.paperTitle || m.paperId)}</div>
      ${m.rationale ? `<p class="note-rationale">${escapeHtml(m.rationale)}</p>` : ''}
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

  // Export as Markdown
  _el.querySelector('.notes-export-btn')?.addEventListener('click', async () => {
    if (_exporting) return;
    _exporting = true;
    _render();
    try {
      const data = await api.exportNotes();
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
  _el.querySelectorAll('.note-quote-btn').forEach(btn => {
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
  _el.querySelectorAll('.note-comment').forEach(textarea => {
    textarea.addEventListener('blur', async () => {
      const idx = Number(textarea.dataset.noteIdx);
      const row = _rows[idx];
      if (!row) return;
      const value = textarea.value;
      if (value === row.comment) return; // no change
      try {
        await api.updateNote(row.id, { comment: value });
        row.comment = value;
        const raw = _notes.find(n => String(n.id) === row.id);
        if (raw) raw.comment = value;
      } catch (err) {
        showToast('Failed to save comment', 'error');
        console.error('[notes view] comment update error', err);
      }
    });
  });

  // Status controls
  _el.querySelectorAll('.note-mark-done').forEach(btn => {
    btn.addEventListener('click', () => _updateStatus(btn, 'done'));
  });
  _el.querySelectorAll('.note-dismiss').forEach(btn => {
    btn.addEventListener('click', () => _updateStatus(btn, 'dismissed'));
  });
  _el.querySelectorAll('.note-reopen').forEach(btn => {
    btn.addEventListener('click', () => _updateStatus(btn, 'open'));
  });

  // Delete
  _el.querySelectorAll('.note-delete').forEach(btn => {
    btn.addEventListener('click', async () => {
      const idx = Number(btn.dataset.noteIdx);
      const row = _rows[idx];
      if (!row) return;
      try {
        await api.deleteNote(row.id);
        _notes = _notes.filter(n => String(n.id) !== row.id);
        _render();
      } catch (err) {
        showToast('Failed to delete note', 'error');
        console.error('[notes view] delete error', err);
      }
    });
  });
}

async function _updateStatus(btn, status) {
  const idx = Number(btn.dataset.noteIdx);
  const row = _rows[idx];
  if (!row) return;
  try {
    await api.updateNote(row.id, { status });
    const raw = _notes.find(n => String(n.id) === row.id);
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
