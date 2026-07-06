/**
 * components/suggestionsPanel.js — Global docked suggestions panel (W3-F3).
 *
 * Mounted ONCE from main.js. Fixed-right panel, width 400px, z-index 380.
 * Non-modal — page behind stays interactive.
 * Toggled by CustomEvent('rc:toggle-suggestions') + Esc closes.
 */

import * as store from '../store.js';
import * as api from '../api.js';
import { showToast } from './toast.js';
import { groupSuggestions, countOpen } from './suggestionHelpers.js';
import { escapeHtml, timeAgo } from '../format.js';
import { tip } from '../glossary.js';

// ---------------------------------------------------------------------------
// Panel state
// ---------------------------------------------------------------------------

let _panel = null;          // HTMLElement
let _open = false;
let _fetched = false;       // lazy-fetch on first open
let _groupMode = 'severity'; // 'severity'|'kind'|'section'
let _statusFilter = 'open'; // 'open'|'addressed'|'dismissed'|'all'
let _regenerating = false;
let _unsubscribe = null;
let _updating = false;      // guard: true while _fetchAndUpdate is in-flight

// ---------------------------------------------------------------------------
// Exported mount
// ---------------------------------------------------------------------------

/**
 * Mount the suggestions panel once into document.body.
 * @param {object} storeRef  — store module (injected for testability)
 * @param {object} apiRef    — api module (injected for testability)
 */
export function mountSuggestionsPanel(storeRef = store, apiRef = api) {
  if (_panel) return; // already mounted

  _apiRef = apiRef; // store for use by _render -> _bindEvents

  _panel = document.createElement('div');
  _panel.id = 'suggestions-panel';
  _panel.className = 'suggestions-panel';
  _panel.setAttribute('aria-label', 'Suggestions panel');
  _panel.setAttribute('role', 'complementary');
  _render(storeRef);
  document.body.appendChild(_panel);

  // Listen for toggle event from bell
  window.addEventListener('rc:toggle-suggestions', () => _toggle(storeRef, apiRef));

  // Esc closes when open
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && _open) _close();
  });

  // Subscribe to store suggestions topic — handles both SSE-driven updates and
  // direct setSuggestions calls (e.g. after dismiss).
  _unsubscribe = storeRef.subscribe('suggestions', () => {
    const { lastAddressedIds } = storeRef.getState();

    // If the notify came from outside our own fetch (SSE counts-only push) and
    // the panel is open, refetch the full list so the view stays fresh.
    if (_open && !_updating) {
      _fetchAndUpdate(storeRef, apiRef);
      return; // _fetchAndUpdate will call _render after update
    }

    _render(storeRef);
    if (Array.isArray(lastAddressedIds) && lastAddressedIds.length > 0) {
      _flashAddressed(lastAddressedIds);
      showToast(
        `${lastAddressedIds.length} suggestion${lastAddressedIds.length === 1 ? '' : 's'} addressed`,
        'info',
      );
    }
  });
}

// ---------------------------------------------------------------------------
// Toggle / open / close
// ---------------------------------------------------------------------------

function _toggle(storeRef, apiRef) {
  if (_open) {
    _close();
  } else {
    _openPanel(storeRef, apiRef);
  }
}

function _openPanel(storeRef, apiRef) {
  _open = true;
  _panel.classList.add('open');
  if (!_fetched) {
    _fetched = true;
    _fetchAndUpdate(storeRef, apiRef);
  }
}

function _close() {
  _open = false;
  _panel.classList.remove('open');
}

// ---------------------------------------------------------------------------
// Fetch
// ---------------------------------------------------------------------------

async function _fetchAndUpdate(storeRef, apiRef) {
  _updating = true;
  try {
    const data = await apiRef.getSuggestions();
    if (data && Array.isArray(data.suggestions)) {
      storeRef.setSuggestions(data.suggestions);
    }
  } catch (err) {
    showToast('Failed to load suggestions', 'error');
    console.error('[suggestionsPanel] fetch error', err);
  } finally {
    _updating = false;
    // Render now that we have fresh data; also flash any newly addressed cards
    _render(storeRef);
    const { lastAddressedIds } = storeRef.getState();
    if (Array.isArray(lastAddressedIds) && lastAddressedIds.length > 0) {
      _flashAddressed(lastAddressedIds);
      showToast(
        `${lastAddressedIds.length} suggestion${lastAddressedIds.length === 1 ? '' : 's'} addressed`,
        'info',
      );
    }
  }
}

// ---------------------------------------------------------------------------
// Render
// ---------------------------------------------------------------------------

// apiRef is stored at mount time so _render can pass it to _bindEvents
let _apiRef = api;

function _render(storeRef) {
  if (!_panel) return;
  const { suggestions } = storeRef.getState();
  const list = Array.isArray(suggestions) ? suggestions : [];
  const openCount = countOpen(list);
  _panel.innerHTML = _buildHtml(list, openCount);
  _bindEvents(list, storeRef, _apiRef);
}

function _buildHtml(list, openCount) {
  return `
    <div class="suggestions-header">
      <div class="suggestions-title-row">
        <span class="suggestions-title">Suggestions</span>
        <span class="suggestions-open-count">${escapeHtml(String(openCount))} open</span>
        <button class="suggestions-close btn btn-secondary btn-sm" aria-label="Close suggestions panel">&times;</button>
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
      <div class="suggestions-actions-row">
        <button class="btn btn-secondary btn-sm suggestions-regen${_regenerating ? ' loading' : ''}"
          ${_regenerating ? 'disabled' : ''}>
          ${_regenerating ? 'Regenerating…' : 'Regenerate'}
        </button>
      </div>
    </div>
    <div class="suggestions-body">
      ${_renderBody(list)}
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
  // Filter
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
    case 'open':       return 'Nothing open — your draft is in good shape.';
    case 'addressed':  return 'No addressed suggestions yet.';
    case 'dismissed':  return 'No dismissed suggestions.';
    default:           return 'No suggestions found.';
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
        <span class="suggestion-sev-dot" style="background:${sevColor}" title="${escapeHtml(s.severity)}"${tip('severity')}></span>
        <span class="suggestion-kind-chip"${tip('band')}>${escapeHtml(s.kind || '')}</span>
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
    // Opens library drawer for this paper
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

function _bindEvents(list, storeRef, apiRef) {
  if (!_panel) return;

  // Close button
  _panel.querySelector('.suggestions-close')?.addEventListener('click', _close);

  // Group mode segmented control
  _panel.querySelectorAll('[data-group]').forEach(btn => {
    btn.addEventListener('click', () => {
      _groupMode = btn.dataset.group;
      _render(storeRef);
    });
  });

  // Status filter chips
  _panel.querySelectorAll('[data-status]').forEach(btn => {
    btn.addEventListener('click', () => {
      _statusFilter = btn.dataset.status;
      _render(storeRef);
    });
  });

  // Regenerate
  _panel.querySelector('.suggestions-regen')?.addEventListener('click', async () => {
    if (_regenerating) return;
    _regenerating = true;
    _render(storeRef);
    try {
      const data = await apiRef.regenerateSuggestions(false);
      if (data && Array.isArray(data.suggestions)) {
        storeRef.setSuggestions(data.suggestions);
      }
      showToast('Suggestions regenerated', 'info');
    } catch (err) {
      showToast('Failed to regenerate', 'error');
      console.error('[suggestionsPanel] regenerate error', err);
    } finally {
      _regenerating = false;
      _render(storeRef);
    }
  });

  // Detail "more" toggle — safe lookup by iterating cards instead of CSS interpolation
  _panel.querySelectorAll('[data-toggle]').forEach(btn => {
    btn.addEventListener('click', () => {
      const id = btn.dataset.toggle;
      // Safe lookup: iterate to avoid CSS-selector injection via id value
      let detail = null;
      _panel.querySelectorAll('.suggestion-detail').forEach(el => {
        if (el.dataset.id === id) detail = el;
      });
      if (!detail) return;
      const expanded = detail.classList.toggle('clamped');
      btn.textContent = expanded ? 'more' : 'less';
    });
  });

  // Source links — paper type opens library drawer
  _panel.querySelectorAll('[data-source-type="paper"]').forEach(btn => {
    btn.addEventListener('click', () => {
      const paperId = btn.dataset.paperId;
      // Stash as module-level handoff so library.js can open the drawer even if
      // it hasn't mounted yet (event arrives before mount completes).
      window.__rcPendingPaper = paperId;
      // Open library drawer — dispatch event that library view listens to
      window.dispatchEvent(new CustomEvent('rc:open-paper', { detail: { paperId } }));
      window.location.hash = '#/library';
    });
  });

  // Discuss buttons
  _panel.querySelectorAll('.suggestion-discuss').forEach(btn => {
    btn.addEventListener('click', () => {
      const id = btn.dataset.id;
      window.dispatchEvent(new CustomEvent('rc:discuss', {
        detail: { type: 'suggestions', id },
      }));
    });
  });

  // Dismiss buttons
  _panel.querySelectorAll('.suggestion-dismiss').forEach(btn => {
    btn.addEventListener('click', async () => {
      const id = btn.dataset.id;
      // Optimistic remove animation — safe lookup by iterating cards
      let card = null;
      _panel.querySelectorAll('.suggestion-card').forEach(el => {
        if (el.dataset.id === id) card = el;
      });
      if (card) {
        card.classList.add('suggestion-dismissing');
        await new Promise(r => setTimeout(r, 180));
      }
      try {
        await apiRef.dismissSuggestion(id);
        // Refetch to get updated list
        const data = await apiRef.getSuggestions();
        if (data && Array.isArray(data.suggestions)) {
          storeRef.setSuggestions(data.suggestions);
        }
      } catch (err) {
        showToast('Failed to dismiss', 'error');
        console.error('[suggestionsPanel] dismiss error', err);
        if (card) card.classList.remove('suggestion-dismissing');
      }
    });
  });
}

// ---------------------------------------------------------------------------
// Flash addressed cards
// ---------------------------------------------------------------------------

function _flashAddressed(ids) {
  if (!_panel || !_open) return;
  for (const id of ids) {
    const card = _panel.querySelector(`.suggestion-card[data-id="${id}"]`);
    if (card) {
      card.classList.add('suggestion-flash-green');
      setTimeout(() => card.classList.remove('suggestion-flash-green'), 400);
    }
  }
}
