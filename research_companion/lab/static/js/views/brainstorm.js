/**
 * views/brainstorm.js — Brainstorm tab, discovery surface (route /brainstorm,
 * Phase 2 slice 2a of Research Ideation).
 *
 * Topic search box + year-range filters + an opt-in "Expand my topic with
 * AI" toggle + Search button -> GET /api/discover. Results run through the
 * pure discoverHelpers.js pipeline (dedupe -> model -> sort) before
 * rendering: title/authors/year/citations/source badge/abstract snippet,
 * an "In library" indicator, and per-result Add (+ a header Add all) that
 * reuse the existing guarded add-paper flow via ensureActiveResearch.
 * Loading / empty / error states mirror views/gaps.js. All server strings
 * render pre-escaped via discoverHelpers.js / escapeHtml.
 *
 * ESCAPING CONTRACT (see discoverHelpers.js's discoverResultModel docstring):
 * title / authorsText / sourceLabel / abstractShort come back ALREADY
 * escaped from discoverResultModel -> interpolate directly, never re-escape.
 * addTarget / url / source / the raw ids are NOT escaped -> escapeHtml them
 * before writing into the DOM (esp. data- attributes).
 */

import * as api from '../api.js';
import { escapeHtml } from '../format.js';
import { showToast } from '../components/toast.js';
import { ensureActiveResearch } from '../researchGuard.js';
import {
  discoverResultModel,
  dedupeDiscoverResults,
  sortDiscoverResults,
} from '../discoverHelpers.js';

// ---------------------------------------------------------------------------
// Module state
// ---------------------------------------------------------------------------

let _el = null;
let _loading = false;
let _error = null;
let _rawResults = [];       // last raw GET /api/discover results[] (pre-dedupe)
let _queriesUsed = [];
let _expandedFlag = false;
let _libraryIds = new Set(); // "prefix:id" ids known-added this session
let _sortCol = 'relevance';
let _sortDir = 'desc';
let _hasSearched = false;

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

export function mount(el) {
  _el = el;
  _loading = false;
  _error = null;
  _rawResults = [];
  _queriesUsed = [];
  _expandedFlag = false;
  _libraryIds = new Set();
  _sortCol = 'relevance';
  _sortDir = 'desc';
  _hasSearched = false;
  _render();
}

export function unmount() {
  _el = null;
}

// ---------------------------------------------------------------------------
// Data
// ---------------------------------------------------------------------------

function _models() {
  const deduped = dedupeDiscoverResults(_rawResults);
  const models = deduped.map(r => discoverResultModel(r, _libraryIds));
  return sortDiscoverResults(models, _sortCol, _sortDir);
}

/** Namespaced ids this model carries, for the session-local "just added" set. */
function _modelIds(m) {
  return [
    m.arxivId && `arxiv:${m.arxivId}`,
    m.doi && `doi:${m.doi}`,
    m.s2Id && `s2:${m.s2Id}`,
    m.pmid && `pmid:${m.pmid}`,
    m.pmcid && `pmcid:${m.pmcid}`,
  ].filter(Boolean);
}

/** model.title is already HTML-escaped; unescape for a plain-text toast. */
const _ENTITY_MAP = { '&amp;': '&', '&lt;': '<', '&gt;': '>', '&quot;': '"', '&#39;': "'" };
function _unescapeForToast(escaped) {
  return escaped.replace(/&amp;|&lt;|&gt;|&quot;|&#39;/g, m => _ENTITY_MAP[m]);
}

async function _search() {
  if (!_el) return;
  const query = (_el.querySelector('#brainstorm-search-input') || {}).value || '';
  const trimmed = query.trim();
  if (!trimmed) {
    _error = 'Type a topic or working title to search.';
    _hasSearched = false;
    _render();
    return;
  }

  const yearMin = (_el.querySelector('#brainstorm-year-min') || {}).value || '';
  const yearMax = (_el.querySelector('#brainstorm-year-max') || {}).value || '';
  const expand = !!(_el.querySelector('#brainstorm-expand-toggle') || {}).checked;

  _loading = true;
  _error = null;
  _hasSearched = true;
  _render();

  try {
    const data = await api.discover({ q: trimmed, yearMin, yearMax, expand });
    _rawResults = Array.isArray(data.results) ? data.results : [];
    _queriesUsed = Array.isArray(data.queries_used) ? data.queries_used : [];
    _expandedFlag = !!data.expanded;
    _error = data.error || null;
  } catch (err) {
    _rawResults = [];
    _queriesUsed = [];
    _error = err.message || 'Search failed.';
  } finally {
    _loading = false;
    _render();
  }
}

async function _addOne(model) {
  await ensureActiveResearch(async () => {
    try {
      await api.addPaper(model.addTarget);
      for (const id of _modelIds(model)) _libraryIds.add(id);
      showToast(`Added "${_unescapeForToast(model.title)}"`, 'info');
      _render();
    } catch (err) {
      showToast(err.message || 'Failed to add paper', 'error');
    }
  });
}

async function _addAll() {
  const notInLibrary = _models().filter(m => !m.inLibrary);
  if (notInLibrary.length === 0) return;
  await ensureActiveResearch(async () => {
    let added = 0;
    for (const m of notInLibrary) {
      try {
        await api.addPaper(m.addTarget);
        for (const id of _modelIds(m)) _libraryIds.add(id);
        added += 1;
      } catch (err) {
        showToast(err.message || 'Failed to add a paper', 'error');
      }
    }
    showToast(`Added ${added} paper${added === 1 ? '' : 's'}`, 'info');
    _render();
  });
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

function _render() {
  if (!_el) return;

  const models = _hasSearched ? _models() : [];
  const notInLibraryCount = models.filter(m => !m.inLibrary).length;

  _el.innerHTML = `
    <div class="brainstorm-view">
      <div class="brainstorm-header">
        <h2>Brainstorm</h2>
        <p class="muted">Start from just a topic &mdash; find real papers, add what you want.</p>
      </div>
      <div class="brainstorm-controls">
        <input id="brainstorm-search-input" type="text" class="brainstorm-search-input"
               placeholder="e.g. graph neural networks for code" aria-label="Topic to search">
        <input id="brainstorm-year-min" type="number" class="brainstorm-year-input"
               placeholder="Year from" aria-label="Year from">
        <input id="brainstorm-year-max" type="number" class="brainstorm-year-input"
               placeholder="Year to" aria-label="Year to">
        <label class="brainstorm-expand-label">
          <input id="brainstorm-expand-toggle" type="checkbox">
          Expand my topic with AI
        </label>
        <button id="brainstorm-search-btn" class="btn btn-accent">Search</button>
      </div>
      ${_expandedFlag && _queriesUsed.length > 0 ? _queriesUsedHtml() : ''}
      <div class="brainstorm-body">
        ${_bodyHtml(models)}
      </div>
      ${models.length > 0 ? `
        <div class="brainstorm-footer">
          <button id="brainstorm-add-all-btn" class="btn btn-secondary"${notInLibraryCount === 0 ? ' disabled' : ''}>
            Add all${notInLibraryCount > 0 ? ` (${notInLibraryCount})` : ''}
          </button>
        </div>` : ''}
    </div>`;

  _bindEvents();
}

function _queriesUsedHtml() {
  const chips = _queriesUsed.map(q => `<span class="chip brainstorm-query-chip">${escapeHtml(q)}</span>`).join('');
  return `<div class="brainstorm-queries-used muted">searched: ${chips}</div>`;
}

function _bodyHtml(models) {
  if (_loading) {
    return '<div class="brainstorm-loading muted">Searching&hellip;</div>';
  }
  if (_error) {
    return `<div class="brainstorm-error">
      <span>${escapeHtml(_error)}</span>
      <button id="brainstorm-retry-btn" class="btn btn-sm">Retry</button>
    </div>`;
  }
  if (!_hasSearched) {
    return '<div class="brainstorm-empty muted">Search a topic to find papers.</div>';
  }
  if (models.length === 0) {
    return '<div class="brainstorm-empty muted">No papers found for this search.</div>';
  }
  return models.map(_rowHtml).join('');
}

function _rowHtml(m) {
  const addBtn = m.inLibrary
    ? '<span class="brainstorm-in-library-badge muted">In library</span>'
    : `<button class="btn btn-sm brainstorm-add-btn" data-add-target="${escapeHtml(m.addTarget)}">Add</button>`;

  return `
    <div class="brainstorm-row" data-add-target="${escapeHtml(m.addTarget)}">
      <div class="brainstorm-row-main">
        <div class="brainstorm-row-title">${m.title}</div>
        <div class="brainstorm-row-meta muted">
          ${m.authorsText}${m.year != null ? ` &middot; ${escapeHtml(String(m.year))}` : ''}
          &middot; ${escapeHtml(String(m.citationCount))} citations
          &middot; <span class="chip brainstorm-source-chip">${m.sourceLabel}</span>
        </div>
        ${m.abstractShort ? `<div class="brainstorm-row-abstract muted">${m.abstractShort}</div>` : ''}
      </div>
      <div class="brainstorm-row-actions">${addBtn}</div>
    </div>`;
}

// ---------------------------------------------------------------------------
// Events
// ---------------------------------------------------------------------------

function _bindEvents() {
  if (!_el) return;

  const searchBtn = _el.querySelector('#brainstorm-search-btn');
  if (searchBtn) searchBtn.addEventListener('click', () => _search());

  const input = _el.querySelector('#brainstorm-search-input');
  if (input) {
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') _search();
    });
  }

  const retryBtn = _el.querySelector('#brainstorm-retry-btn');
  if (retryBtn) retryBtn.addEventListener('click', () => _search());

  const addAllBtn = _el.querySelector('#brainstorm-add-all-btn');
  if (addAllBtn) addAllBtn.addEventListener('click', () => _addAll());

  _el.querySelectorAll('.brainstorm-add-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const model = _models().find(m => m.addTarget === btn.dataset.addTarget);
      if (model) _addOne(model);
    });
  });
}
