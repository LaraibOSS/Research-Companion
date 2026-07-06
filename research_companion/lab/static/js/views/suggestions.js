/**
 * views/suggestions.js — Full-page /suggestions route (W3-F3).
 *
 * Thin wrapper: renders the grouped suggestions list full-width,
 * reusing the same renderer pieces from suggestionsPanel.
 * Route: #/suggestions
 */

import * as store from '../store.js';
import * as api from '../api.js';
import { showToast } from '../components/toast.js';
import { groupSuggestions, countOpen } from '../components/suggestionHelpers.js';

// ---------------------------------------------------------------------------
// Escape helper
// ---------------------------------------------------------------------------

function escapeHtml(s) {
  if (s == null) return '';
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function timeAgo(isoString) {
  if (!isoString) return '';
  const diff = Date.now() - new Date(isoString).getTime();
  const sec = Math.floor(diff / 1000);
  if (sec < 60) return 'just now';
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  return `${Math.floor(hr / 24)}d ago`;
}

// ---------------------------------------------------------------------------
// View state
// ---------------------------------------------------------------------------

let _el = null;
let _unsubscribe = null;
let _groupMode = 'severity';
let _statusFilter = 'open';
let _regenerating = false;

// ---------------------------------------------------------------------------
// mount / unmount
// ---------------------------------------------------------------------------

export function mount(el) {
  _el = el;
  _render();
  _unsubscribe = store.subscribe('suggestions', _render);

  // Fetch if we have no suggestions yet
  const { suggestions } = store.getState();
  if (!Array.isArray(suggestions) || suggestions.length === 0) {
    _fetch();
  }
}

export function unmount() {
  if (_unsubscribe) { _unsubscribe(); _unsubscribe = null; }
  _el = null;
  _regenerating = false;
}

// ---------------------------------------------------------------------------
// Fetch
// ---------------------------------------------------------------------------

async function _fetch() {
  try {
    const data = await api.getSuggestions();
    if (data && Array.isArray(data.suggestions)) {
      store.setSuggestions(data.suggestions);
    }
  } catch (err) {
    showToast('Failed to load suggestions', 'error');
    console.error('[suggestions view] fetch error', err);
  }
}

// ---------------------------------------------------------------------------
// Render
// ---------------------------------------------------------------------------

function _render() {
  if (!_el) return;
  const { suggestions } = store.getState();
  const list = Array.isArray(suggestions) ? suggestions : [];
  const openCount = countOpen(list);
  _el.innerHTML = _buildPageHtml(list, openCount);
  _bindEvents(list);
}

function _buildPageHtml(list, openCount) {
  return `
    <div class="suggestions-page">
      <div class="suggestions-page-header">
        <h2 class="suggestions-page-title">Suggestions
          <span class="suggestions-open-count">${escapeHtml(String(openCount))} open</span>
        </h2>
        <button class="btn btn-secondary btn-sm suggestions-regen${_regenerating ? ' loading' : ''}"
          ${_regenerating ? 'disabled' : ''}>
          ${_regenerating ? 'Regenerating…' : 'Regenerate'}
        </button>
      </div>
      <div class="suggestions-controls">
        <div class="suggestions-group-seg" role="group" aria-label="Group by">
          ${_segBtn('severity', 'Severity', _groupMode)}
          ${_segBtn('kind', 'Kind', _groupMode)}
          ${_segBtn('section', 'Section', _groupMode)}
        </div>
        <div class="suggestions-status-chips filter-chips">
          ${_statusChip('open', 'Open', _statusFilter)}
          ${_statusChip('addressed', 'Addressed', _statusFilter)}
          ${_statusChip('dismissed', 'Dismissed', _statusFilter)}
          ${_statusChip('all', 'All', _statusFilter)}
        </div>
      </div>
      <div class="suggestions-page-body">
        ${_renderBody(list)}
      </div>
    </div>`;
}

function _segBtn(value, label, current) {
  const active = current === value ? ' active' : '';
  return `<button class="suggestions-seg-btn${active}" data-group="${escapeHtml(value)}">${escapeHtml(label)}</button>`;
}

function _statusChip(value, label, current) {
  const active = current === value ? ' chip-active' : '';
  return `<button class="chip${active}" data-status="${escapeHtml(value)}">${escapeHtml(label)}</button>`;
}

function _renderBody(list) {
  const filtered = _statusFilter === 'all'
    ? list
    : list.filter(s => s.status === _statusFilter);

  if (filtered.length === 0) {
    return `<div class="suggestions-empty">${escapeHtml(_emptyMessage())}</div>`;
  }

  const groups = groupSuggestions(filtered, _groupMode);
  return groups.map(group => `
    <div class="suggestions-group">
      <div class="suggestions-group-label">${escapeHtml(group.label)}</div>
      ${group.items.map(s => _renderCard(s)).join('')}
    </div>`).join('');
}

function _emptyMessage() {
  switch (_statusFilter) {
    case 'open':      return 'Nothing open — your draft is in good shape.';
    case 'addressed': return 'No addressed suggestions yet.';
    case 'dismissed': return 'No dismissed suggestions.';
    default:          return 'No suggestions found.';
  }
}

function _renderCard(s) {
  const sevColor = `var(--sev-${escapeHtml(s.severity || 'low')})`;
  const isAddressed = s.status === 'addressed';

  const addressedRibbon = isAddressed ? `
    <div class="suggestion-addressed-ribbon">
      <span class="suggestion-check">&#10003;</span>
      Addressed ${escapeHtml(timeAgo(s.addressed_at))}
      ${s.addressed_by && s.addressed_by.note
        ? `<span class="suggestion-addressed-note"> — ${escapeHtml(s.addressed_by.note)}</span>`
        : ''}
    </div>` : '';

  const sourceLink = _sourceLink(s.source);

  return `
    <div class="suggestion-card${isAddressed ? ' suggestion-addressed' : ''}" data-id="${escapeHtml(s.id)}" data-sev="${escapeHtml(s.severity)}">
      ${addressedRibbon}
      <div class="suggestion-card-top">
        <span class="suggestion-sev-dot" style="background:${sevColor}" title="${escapeHtml(s.severity)}"></span>
        <span class="suggestion-kind-chip">${escapeHtml(s.kind || '')}</span>
        <span class="suggestion-time-ago">${escapeHtml(timeAgo(s.created_at))}</span>
      </div>
      <div class="suggestion-title">${escapeHtml(s.title)}</div>
      <div class="suggestion-detail-wrap">
        <div class="suggestion-detail clamped" data-id="${escapeHtml(s.id)}">${escapeHtml(s.detail)}</div>
        <button class="suggestion-more-btn" data-toggle="${escapeHtml(s.id)}">more</button>
      </div>
      <div class="suggestion-actions">
        ${sourceLink}
        <button class="btn btn-secondary btn-sm suggestion-discuss" data-id="${escapeHtml(s.id)}">Discuss</button>
        ${s.status === 'open'
          ? `<button class="btn btn-secondary btn-sm suggestion-dismiss" data-id="${escapeHtml(s.id)}">Dismiss</button>`
          : ''}
      </div>
    </div>`;
}

function _sourceLink(source) {
  if (!source) return '';
  const label = escapeHtml(source.label || source.type || 'Source');
  if (source.type === 'paper' && source.paper_id) {
    return `<button class="btn btn-secondary btn-sm suggestion-source-link"
      data-source-type="paper" data-paper-id="${escapeHtml(source.paper_id)}">${label}</button>`;
  }
  if (source.type === 'section' && source.section_id) {
    return `<a class="btn btn-secondary btn-sm suggestion-source-link"
      href="#/draft?section=${encodeURIComponent(source.section_id)}">${label}</a>`;
  }
  if (source.type === 'lane') {
    return `<a class="btn btn-secondary btn-sm suggestion-source-link"
      href="#/library">${label}</a>`;
  }
  return '';
}

// ---------------------------------------------------------------------------
// Event binding
// ---------------------------------------------------------------------------

function _bindEvents(list) {
  if (!_el) return;

  // Group mode
  _el.querySelectorAll('[data-group]').forEach(btn => {
    btn.addEventListener('click', () => {
      _groupMode = btn.dataset.group;
      _render();
    });
  });

  // Status filter
  _el.querySelectorAll('[data-status]').forEach(btn => {
    btn.addEventListener('click', () => {
      _statusFilter = btn.dataset.status;
      _render();
    });
  });

  // Regenerate
  _el.querySelector('.suggestions-regen')?.addEventListener('click', async () => {
    if (_regenerating) return;
    _regenerating = true;
    _render();
    try {
      const data = await api.regenerateSuggestions(false);
      if (data && Array.isArray(data.suggestions)) {
        store.setSuggestions(data.suggestions);
      }
      showToast('Suggestions regenerated', 'info');
    } catch (err) {
      showToast('Failed to regenerate', 'error');
      console.error('[suggestions view] regenerate error', err);
    } finally {
      _regenerating = false;
      _render();
    }
  });

  // Detail "more" toggle
  _el.querySelectorAll('[data-toggle]').forEach(btn => {
    btn.addEventListener('click', () => {
      const id = btn.dataset.toggle;
      const detail = _el.querySelector(`.suggestion-detail[data-id="${id}"]`);
      if (!detail) return;
      const expanded = detail.classList.toggle('clamped');
      btn.textContent = expanded ? 'more' : 'less';
    });
  });

  // Source links — paper type
  _el.querySelectorAll('[data-source-type="paper"]').forEach(btn => {
    btn.addEventListener('click', () => {
      const paperId = btn.dataset.paperId;
      window.dispatchEvent(new CustomEvent('rc:open-paper', { detail: { paperId } }));
      window.location.hash = '#/library';
    });
  });

  // Discuss buttons
  _el.querySelectorAll('.suggestion-discuss').forEach(btn => {
    btn.addEventListener('click', () => {
      const id = btn.dataset.id;
      window.dispatchEvent(new CustomEvent('rc:discuss', {
        detail: { type: 'suggestions', id },
      }));
    });
  });

  // Dismiss buttons
  _el.querySelectorAll('.suggestion-dismiss').forEach(btn => {
    btn.addEventListener('click', async () => {
      const id = btn.dataset.id;
      const card = _el.querySelector(`.suggestion-card[data-id="${id}"]`);
      if (card) {
        card.classList.add('suggestion-dismissing');
        await new Promise(r => setTimeout(r, 180));
      }
      try {
        await api.dismissSuggestion(id);
        const data = await api.getSuggestions();
        if (data && Array.isArray(data.suggestions)) {
          store.setSuggestions(data.suggestions);
        }
      } catch (err) {
        showToast('Failed to dismiss', 'error');
        console.error('[suggestions view] dismiss error', err);
        if (card) card.classList.remove('suggestion-dismissing');
      }
    });
  });
}
