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
import { directionResultModel, sortDirections } from '../directionsHelpers.js';
import { noveltyResultModel } from '../noveltyHelpers.js';
import { scaffoldPanelModel } from '../scaffoldHelpers.js';
import { serializeSession, hydrateSession, sessionHasContent } from '../brainstormSessionHelpers.js';
import * as store from '../store.js';

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
let _directionsLoading = false;
let _directionsError = null;
let _rawDirections = [];        // last raw POST /api/directions directions[]
let _directionsHasGenerated = false;
let _directionsSortCol = 'score';
let _directionsSortDir = 'desc';
let _noveltyByDirectionId = new Map(); // directionId -> {loading, error, result} — survives full _render()
let _scaffoldByDirectionId = new Map(); // directionId -> {loading, error, result} — survives full _render()
let _topic = '';            // last searched/typed topic — persisted so the box refills on revisit
let _hydrating = false;     // true while restoring a saved session (suppresses re-save)
let _persistTimer = null;   // debounce handle for _persist()

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
  _directionsLoading = false;
  _directionsError = null;
  _rawDirections = [];
  _directionsHasGenerated = false;
  _directionsSortCol = 'score';
  _directionsSortDir = 'desc';
  _noveltyByDirectionId = new Map();
  _scaffoldByDirectionId = new Map();
  _topic = '';
  _render();
  _hydrate();
}

export function unmount() {
  if (_persistTimer) { clearTimeout(_persistTimer); _persistTimer = null; }
  _el = null;
}

// ---------------------------------------------------------------------------
// Session persistence (per research; survives revisits/reloads)
// ---------------------------------------------------------------------------

// Restore a saved Brainstorm session on mount. Non-fatal: any failure just
// leaves the fresh empty tab. Never re-saves what it just loaded.
async function _hydrate() {
  let payload = null;
  try {
    const data = await api.getBrainstormSession();
    payload = data && data.session;
  } catch {
    payload = null;
  }
  if (!_el || !sessionHasContent(payload)) return;

  _hydrating = true;
  const s = hydrateSession(payload);
  _topic = s.topic;
  _rawResults = s.rawResults;
  _queriesUsed = s.queriesUsed;
  _expandedFlag = s.expandedFlag;
  _hasSearched = s.hasSearched || s.rawResults.length > 0;
  _rawDirections = s.rawDirections;
  _directionsHasGenerated = s.directionsHasGenerated || s.rawDirections.length > 0;
  _libraryIds = new Set(s.libraryIds);
  _noveltyByDirectionId = new Map(
    Object.entries(s.novelty).map(([id, result]) => [id, { loading: false, error: null, result }]),
  );
  _hydrating = false;
  _render();
}

// Serialize the tab's state and persist it (debounced). PUT is workspace-
// guarded; with no active research it simply fails and is ignored — the
// session saves once a research exists (adding a paper creates one).
function _persist() {
  if (_hydrating) return;
  if (_persistTimer) clearTimeout(_persistTimer);
  _persistTimer = setTimeout(() => {
    _persistTimer = null;
    const novelty = {};
    for (const [id, entry] of _noveltyByDirectionId) {
      if (entry && entry.result) novelty[id] = entry.result;
    }
    const payload = serializeSession({
      topic: _topic,
      queriesUsed: _queriesUsed,
      expandedFlag: _expandedFlag,
      rawResults: _rawResults,
      rawDirections: _rawDirections,
      hasSearched: _hasSearched,
      directionsHasGenerated: _directionsHasGenerated,
      novelty,
      libraryIds: [..._libraryIds],
    });
    api.putBrainstormSession(payload).catch(() => {});
  }, 500);
}


// Brainstorming produces papers, directions and a brief that all have to live
// *somewhere*. Ask for the research name on arrival rather than ambushing the
// user at their first Add — and if they dismiss it, leave a visible way back
// instead of silently letting them work into nowhere.
function _hasActiveResearch() {
  const { workspaces } = store.getState();
  return !!(workspaces && workspaces.activeId);
}

async function _promptForResearchOnce() {
  if (_askedForResearch || _hasActiveResearch()) return;
  _askedForResearch = true;
  await ensureActiveResearch(() => {});
  if (_el) _render();
}

function _researchGateHtml() {
  if (_hasActiveResearch()) return '';
  return `
    <div class="brainstorm-research-gate">
      <div>
        <strong>Name your research project to get started.</strong>
        <span class="muted"> Everything you find and add here is saved into it.</span>
      </div>
      <button id="brainstorm-name-research" class="btn btn-accent btn-sm">Name your research</button>
    </div>`;
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
  _topic = trimmed;
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
    _persist();
  }
}

async function _addOne(model) {
  await ensureActiveResearch(async () => {
    try {
      await api.addPaper(model.addTarget);
      for (const id of _modelIds(model)) _libraryIds.add(id);
      showToast(`Added "${_unescapeForToast(model.title)}"`, 'info');
      _render();
      _persist();
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
    _persist();
  });
}

function _directionModels() {
  return sortDirections(_rawDirections.map(directionResultModel), _directionsSortCol, _directionsSortDir);
}

/** Enabled once there is something to ground on: a typed topic, or at least
 * one paper already in view from a 2a search (the actual library is always
 * additionally consulted server-side regardless of this button's state). */
function _directionsButtonEnabled() {
  if (!_el) return false;
  const topic = ((_el.querySelector('#brainstorm-search-input') || {}).value || '').trim();
  return topic.length > 0 || _rawResults.length > 0;
}

async function _generateDirections() {
  if (!_el) return;
  const topic = ((_el.querySelector('#brainstorm-search-input') || {}).value || '').trim();
  const yearMin = (_el.querySelector('#brainstorm-year-min') || {}).value || '';
  const yearMax = (_el.querySelector('#brainstorm-year-max') || {}).value || '';

  _directionsLoading = true;
  _directionsError = null;
  _directionsHasGenerated = true;
  if (topic) _topic = topic;
  _render();

  try {
    const data = await api.directions({ topic, yearMin, yearMax, seeds: _rawResults });
    _rawDirections = Array.isArray(data.directions) ? data.directions : [];
    _directionsError = data.error || null;
  } catch (err) {
    _rawDirections = [];
    _directionsError = err.message || 'Failed to generate directions.';
  } finally {
    _directionsLoading = false;
    _render();
    _persist();
  }
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
      ${_researchGateHtml()}
      <div class="brainstorm-header">
        <h2>Brainstorm</h2>
        <p class="muted">Start from just a topic &mdash; find real papers, add what you want.</p>
      </div>
      <div class="brainstorm-controls">
        <input id="brainstorm-search-input" type="text" class="brainstorm-search-input"
               value="${escapeHtml(_topic)}"
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
      ${_directionsSectionHtml()}
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

function _directionsSectionHtml() {
  const enabled = _directionsButtonEnabled();
  return `
    <div class="brainstorm-directions-section">
      <div class="brainstorm-directions-header">
        <h3>Research Directions</h3>
        <button id="brainstorm-directions-btn" class="btn btn-accent"${enabled ? '' : ' disabled'}>Generate directions</button>
      </div>
      <div class="brainstorm-directions-body">
        ${_directionsBodyHtml()}
      </div>
    </div>`;
}

function _directionsBodyHtml() {
  if (_directionsLoading) {
    return '<div class="brainstorm-directions-loading muted">Generating directions&hellip;</div>';
  }
  if (_directionsError) {
    return `<div class="brainstorm-directions-error">
      <span>${escapeHtml(_directionsError)}</span>
      <button id="brainstorm-directions-retry-btn" class="btn btn-sm">Retry</button>
    </div>`;
  }
  if (!_directionsHasGenerated) {
    return '<div class="brainstorm-directions-empty muted">Search a topic or add papers, then generate directions.</div>';
  }
  const models = _directionModels();
  if (models.length === 0) {
    return '<div class="brainstorm-directions-empty muted">No grounded directions yet &mdash; try a broader topic or add more papers.</div>';
  }
  return models.map(_directionCardHtml).join('');
}

function _directionCardHtml(m) {
  const chips = m.citations.map(_citationChipHtml).join('');
  const noveltyState = _noveltyByDirectionId.get(m.directionId) || null;
  const scaffoldState = _scaffoldByDirectionId.get(m.directionId) || null;
  return `
    <div class="brainstorm-direction-card" data-direction-id="${escapeHtml(m.directionId)}">
      <div class="brainstorm-direction-top">
        <span class="chip brainstorm-direction-type-chip brainstorm-direction-type-${escapeHtml(m.typeBadge.slug)}">${m.typeBadge.label}</span>
        <span class="brainstorm-direction-score muted">score ${escapeHtml(String(m.score))} &middot; ${escapeHtml(String(m.groundingCount))} cited</span>
      </div>
      <div class="brainstorm-direction-title">${m.title}</div>
      <div class="brainstorm-direction-rationale muted">${m.rationale}</div>
      <div class="brainstorm-direction-citations">${chips}</div>
      <div class="brainstorm-direction-novelty">${_noveltyPanelHtml(m.directionId, noveltyState)}</div>
      <div class="brainstorm-direction-scaffold">${_scaffoldPanelHtml(m.directionId, scaffoldState)}</div>
    </div>`;
}

function _noveltyPanelHtml(directionId, state) {
  if (!state) {
    return `<button class="btn btn-sm brainstorm-novelty-btn" data-direction-id="${escapeHtml(directionId)}">Check novelty</button>`;
  }
  if (state.loading) {
    return '<span class="muted brainstorm-novelty-loading">Checking novelty&hellip;</span>';
  }
  if (state.error) {
    return `<div class="brainstorm-novelty-error">
      <span>${escapeHtml(state.error)}</span>
      <button class="btn btn-sm brainstorm-novelty-retry-btn" data-direction-id="${escapeHtml(directionId)}">Retry</button>
    </div>`;
  }
  const model = noveltyResultModel(state.result);
  const priorChips = model.priorWorks.map(pw => `
    <a class="chip brainstorm-novelty-prior-chip" href="${escapeHtml(pw.url)}" target="_blank" rel="noopener">${pw.label}</a>`).join('');
  return `
    <div class="brainstorm-novelty-result">
      <span class="chip brainstorm-novelty-badge brainstorm-novelty-badge-${escapeHtml(model.verdictBadge.slug)}">${model.verdictBadge.label}</span>
      <span class="brainstorm-novelty-confidence muted">${escapeHtml(String(model.confidencePct))}% confidence</span>
      <div class="brainstorm-novelty-rationale muted">${model.rationale}</div>
      ${priorChips ? `<div class="brainstorm-novelty-priors">${priorChips}</div>` : ''}
    </div>`;
}

async function _checkNovelty(directionId) {
  if (!_el || !directionId) return;
  const raw = _rawDirections.find(d => d.direction_id === directionId);
  if (!raw) return;

  const card = _el.querySelector(`.brainstorm-direction-card[data-direction-id="${CSS.escape(directionId)}"]`);
  const panel = card ? card.querySelector('.brainstorm-direction-novelty') : null;

  _noveltyByDirectionId.set(directionId, { loading: true, error: null, result: null });
  if (panel) panel.innerHTML = _noveltyPanelHtml(directionId, _noveltyByDirectionId.get(directionId));

  const yearMin = (_el.querySelector('#brainstorm-year-min') || {}).value || '';
  const yearMax = (_el.querySelector('#brainstorm-year-max') || {}).value || '';

  try {
    const data = await api.checkNovelty({
      title: raw.title || '', rationale: raw.rationale || '', yearMin, yearMax,
    });
    if (data.error) {
      _noveltyByDirectionId.set(directionId, { loading: false, error: data.error, result: null });
    } else {
      _noveltyByDirectionId.set(directionId, { loading: false, error: null, result: data });
    }
  } catch (err) {
    _noveltyByDirectionId.set(directionId, {
      loading: false, error: err.message || 'Novelty check failed.', result: null,
    });
  }

  if (panel) {
    panel.innerHTML = _noveltyPanelHtml(directionId, _noveltyByDirectionId.get(directionId));
    _bindNoveltyPanelEvents(panel, directionId);
  }
  _persist();
}

function _bindNoveltyPanelEvents(panel, directionId) {
  if (!panel) return;
  const retryBtn = panel.querySelector('.brainstorm-novelty-retry-btn');
  if (retryBtn) retryBtn.addEventListener('click', () => _checkNovelty(directionId));
}

function _scaffoldPanelHtml(directionId, state) {
  const model = scaffoldPanelModel(state);
  if (model.status === 'loading') {
    return '<span class="muted brainstorm-scaffold-loading">Creating draft&hellip;</span>';
  }
  if (model.status === 'error') {
    return `<div class="brainstorm-scaffold-error">
      <span>${model.errorMessage}</span>
      <button class="btn btn-sm brainstorm-scaffold-retry-btn" data-direction-id="${escapeHtml(directionId)}">Retry</button>
    </div>`;
  }
  if (model.status === 'success') {
    return `
      <div class="brainstorm-scaffold-result">
        <span class="brainstorm-scaffold-success muted">${model.successMessage}</span>
        <a class="btn btn-sm brainstorm-scaffold-open-btn" href="${escapeHtml(model.openDraftRoute || '#/draft')}">Open draft</a>
      </div>`;
  }
  return `<button class="btn btn-sm brainstorm-scaffold-btn" data-direction-id="${escapeHtml(directionId)}">Draft this direction</button>`;
}

async function _scaffoldDraft(directionId) {
  if (!_el || !directionId) return;
  const raw = _rawDirections.find(d => d.direction_id === directionId);
  if (!raw) return;

  await ensureActiveResearch(async () => {
    const card = _el.querySelector(`.brainstorm-direction-card[data-direction-id="${CSS.escape(directionId)}"]`);
    const panel = card ? card.querySelector('.brainstorm-direction-scaffold') : null;

    _scaffoldByDirectionId.set(directionId, { loading: true, error: null, result: null });
    if (panel) panel.innerHTML = _scaffoldPanelHtml(directionId, _scaffoldByDirectionId.get(directionId));

    try {
      const data = await api.scaffoldDraft({
        title: raw.title || '',
        rationale: raw.rationale || '',
        directionType: raw.direction_type || '',
        citations: Array.isArray(raw.citations) ? raw.citations : [],
      });
      if (data.ok === false) {
        _scaffoldByDirectionId.set(directionId, {
          loading: false, error: data.error || 'Failed to draft this direction.', result: null,
        });
      } else {
        _scaffoldByDirectionId.set(directionId, {
          loading: false, error: null,
          result: { section_count: data.section_count, replaced_draft: !!data.replaced_draft },
        });
        store.setDraft(data.paper_id);
        showToast(data.replaced_draft ? 'Replaced your previous draft' : 'Draft created', 'info');
      }
    } catch (err) {
      _scaffoldByDirectionId.set(directionId, {
        loading: false, error: err.message || 'Failed to draft this direction.', result: null,
      });
    }

    if (panel) {
      panel.innerHTML = _scaffoldPanelHtml(directionId, _scaffoldByDirectionId.get(directionId));
      _bindScaffoldPanelEvents(panel, directionId);
    }
  });
}

function _bindScaffoldPanelEvents(panel, directionId) {
  if (!panel) return;
  const retryBtn = panel.querySelector('.brainstorm-scaffold-retry-btn');
  if (retryBtn) retryBtn.addEventListener('click', () => _scaffoldDraft(directionId));
}

function _citationChipHtml(c) {
  if (c.kind === 'paper' && c.paperId) {
    return `<button class="chip brainstorm-direction-citation-paper" data-paper-id="${escapeHtml(c.paperId)}" title="${escapeHtml(c.title)}">${c.label}</button>`;
  }
  const kindClass = c.kind === 'gap' ? 'brainstorm-direction-citation-gap' : 'brainstorm-direction-citation-concept';
  return `<span class="chip ${kindClass}" title="${escapeHtml(c.kind)}">${c.label}</span>`;
}

// ---------------------------------------------------------------------------
// Events
// ---------------------------------------------------------------------------

function _bindEvents() {
  if (!_el) return;

  const nameBtn = _el.querySelector('#brainstorm-name-research');
  if (nameBtn) {
    nameBtn.addEventListener('click', async () => {
      await ensureActiveResearch(() => {});
      if (_el) _render();
    });
  }

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

  const directionsBtn = _el.querySelector('#brainstorm-directions-btn');
  if (directionsBtn) directionsBtn.addEventListener('click', () => _generateDirections());

  const directionsRetryBtn = _el.querySelector('#brainstorm-directions-retry-btn');
  if (directionsRetryBtn) directionsRetryBtn.addEventListener('click', () => _generateDirections());

  _el.querySelectorAll('.brainstorm-direction-citation-paper').forEach(btn => {
    btn.addEventListener('click', () => {
      const paperId = btn.dataset.paperId;
      if (!paperId) return;
      window.__rcPendingPaper = paperId;
      window.dispatchEvent(new CustomEvent('rc:open-paper', { detail: { paper_id: paperId }, bubbles: true }));
      window.location.hash = '#/library';
    });
  });

  _el.querySelectorAll('.brainstorm-novelty-btn, .brainstorm-novelty-retry-btn').forEach(btn => {
    btn.addEventListener('click', () => _checkNovelty(btn.dataset.directionId));
  });

  _el.querySelectorAll('.brainstorm-scaffold-btn, .brainstorm-scaffold-retry-btn').forEach(btn => {
    btn.addEventListener('click', () => _scaffoldDraft(btn.dataset.directionId));
  });
}
