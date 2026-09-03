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
import {
  briefModel, setBulletText, deleteBullet, addBullet, deleteSection, moveBullet,
} from '../briefHelpers.js';
import { buildNoteRecord } from '../noteRecord.js';
import { addReceiptModel } from '../addReceipt.js';
import {
  ingestStatus, provenanceLine, DIRECTIONS_INTRO, DIRECTIONS_DISCLAIMER,
} from '../directionsProvenance.js';
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
let _directionsGrounding = null;  // real counts of what the last generate used
let _directionsSortCol = 'score';
let _directionsSortDir = 'desc';
let _noveltyByDirectionId = new Map(); // directionId -> {loading, error, result} — survives full _render()
let _scaffoldByDirectionId = new Map(); // directionId -> {loading, error, result} — survives full _render()
let _topic = '';            // last searched/typed topic — persisted so the box refills on revisit
let _hydrating = false;     // true while restoring a saved session (suppresses re-save)
let _persistTimer = null;   // debounce handle for _persist()
let _unsub = null;          // store subscription (ingest notice live-update)
let _brief = null;          // raw brief {brief_id, topic, sections:[...]} | null — persisted
let _briefLoading = false;
let _briefError = null;
let _briefEditing = null;   // {si, bi} of the bullet being inline-edited, or null
let _briefNoteFor = null;   // {si, bi} of the bullet with an open note form, or null
let _askedForResearch = false;  // the up-front 'name your research' prompt fires once per mount
let _addReceipt = null;     // {queued, skipped, failed} from the last Add — dismissible
let _wsLoaded = false;      // workspaces snapshot fetched (never judge before this)
let _limit = 20;            // how many results to fetch (20/30/40/50)
let _rank = 'balanced';     // balanced | citations | venue
let _unsubWs = null;        // workspaces subscription

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
  _directionsGrounding = null;
  _directionsSortCol = 'score';
  _directionsSortDir = 'desc';
  _noveltyByDirectionId = new Map();
  _scaffoldByDirectionId = new Map();
  _topic = '';
  _brief = null;
  _briefLoading = false;
  _briefError = null;
  _briefEditing = null;
  _briefNoteFor = null;
  _askedForResearch = false;
  _addReceipt = null;
  _wsLoaded = false;
  _limit = 20;
  _rank = 'balanced';
  _render();
  _hydrate();
  _unsub = store.subscribe(['papers', 'activity'], () => _refreshIngestNotice());
  _unsubWs = store.subscribe('workspaces', () => { _wsLoaded = true; if (_el) _render(); });
}

export function unmount() {
  if (_persistTimer) { clearTimeout(_persistTimer); _persistTimer = null; }
  if (_unsub) { _unsub(); _unsub = null; }
  if (_unsubWs) { _unsubWs(); _unsubWs = null; }
  _el = null;
}

// Papers finish ingesting in the background; keep the "still being added"
// notice truthful by patching just that node (a full _render() here would
// disturb typing and in-flight panels).
function _refreshIngestNotice() {
  if (!_el) return;
  const node = _el.querySelector('#brainstorm-ingest-notice');
  if (!node) return;
  const ingest = ingestStatus(store.getState());
  node.textContent = ingest.message;
  node.hidden = !ingest.message;
  node.classList.toggle('is-busy', ingest.busy);
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
  _brief = s.brief;
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
      brief: _brief,
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
  if (_askedForResearch) return;
  // The workspaces snapshot loads asynchronously at boot. Deciding from an
  // unloaded store would tell a user who already HAS a research to create one,
  // so refresh it first and only then judge.
  try {
    const data = await api.getWorkspaces();
    store.setWorkspaces(data);
  } catch {
    return;   // cannot tell -> never nag
  }
  _wsLoaded = true;
  if (!_el) return;
  _render();
  if (_hasActiveResearch()) return;
  _askedForResearch = true;
  await ensureActiveResearch(() => {});
  if (_el) _render();
}

function _researchGateHtml() {
  if (!_wsLoaded || _hasActiveResearch()) return '';
  return `
    <div class="brainstorm-research-gate">
      <div>
        <strong>Name your research project to get started.</strong>
        <span class="muted"> Everything you find and add here is saved into it.</span>
      </div>
      <button id="brainstorm-name-research" class="btn btn-accent btn-sm">Name your research</button>
    </div>`;
}

function _activeResearchName() {
  const { workspaces } = store.getState();
  const list = (workspaces && Array.isArray(workspaces.list)) ? workspaces.list : [];
  const activeId = workspaces && workspaces.activeId;
  const active = list.find(w => w.id === activeId);
  return active ? (active.name || active.id) : '';
}

// Adding is async and silent; show an explicit receipt of what happened and
// what to do about downloads that fail, rather than leaving the user to infer
// it from a toast.
function _addReceiptHtml() {
  if (!_addReceipt) return '';
  const m = addReceiptModel({ ..._addReceipt, researchName: _activeResearchName() });
  if (!m.hasContent) return '';
  return `
    <div class="brainstorm-add-receipt">
      <button class="brainstorm-add-receipt-close" id="brainstorm-receipt-close"
              aria-label="Dismiss">&times;</button>
      <div class="brainstorm-add-receipt-title">${escapeHtml(m.title)}</div>
      <p class="brainstorm-add-receipt-detail">${escapeHtml(m.detail)}
        <a href="#/library">View in Library</a>
      </p>
      <p class="brainstorm-add-receipt-note">${escapeHtml(m.disclaimer)}</p>
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
  _limit = Number((_el.querySelector('#brainstorm-limit') || {}).value) || 20;
  _rank = (_el.querySelector('#brainstorm-rank') || {}).value || 'balanced';

  _loading = true;
  _error = null;
  _hasSearched = true;
  _topic = trimmed;
  _render();

  try {
    const data = await api.discover({
      q: trimmed, yearMin, yearMax, expand, limit: _limit, rank: _rank,
    });
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
      _addReceipt = { queued: 1, skipped: 0, failed: 0 };
      showToast(`Added "${_unescapeForToast(model.title)}"`, 'info');
      _render();
      _persist();
    } catch (err) {
      showToast(err.message || 'Failed to add paper', 'error');
    }
  });
}

async function _addAll() {
  const all = _models();
  const notInLibrary = all.filter(m => !m.inLibrary);
  const skipped = all.length - notInLibrary.length;
  if (notInLibrary.length === 0) {
    // Everything on screen is already here — say so instead of doing nothing.
    _addReceipt = { queued: 0, skipped, failed: 0 };
    _render();
    return;
  }
  await ensureActiveResearch(async () => {
    let added = 0;
    let failed = 0;
    for (const m of notInLibrary) {
      try {
        await api.addPaper(m.addTarget);
        for (const id of _modelIds(m)) _libraryIds.add(id);
        added += 1;
      } catch (err) {
        failed += 1;
        showToast(err.message || 'Failed to add a paper', 'error');
      }
    }
    _addReceipt = { queued: added, skipped, failed };
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
    _directionsGrounding = data.grounding || null;
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
      ${_addReceiptHtml()}
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
        <select id="brainstorm-limit" class="brainstorm-select" aria-label="Number of results">
          ${[20, 30, 40, 50].map(n =>
            `<option value="${n}"${n === _limit ? ' selected' : ''}>${n} results</option>`).join('')}
        </select>
        <select id="brainstorm-rank" class="brainstorm-select" aria-label="Rank results by">
          ${[['balanced', 'Balanced'], ['citations', 'Most cited'], ['venue', 'Top venues']]
            .map(([v, label]) =>
              `<option value="${v}"${v === _rank ? ' selected' : ''}>${label}</option>`).join('')}
        </select>
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
      ${_briefSectionHtml()}
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
          ${m.isTopVenue
            ? `<span class="brainstorm-venue-badge" title="Recognized top venue">${m.topVenue}</span>`
            : (m.venue ? `<span class="brainstorm-venue">${m.venue}</span>` : '')}
          &middot; <span class="chip brainstorm-source-chip">${m.sourceLabel}</span>
        </div>
        ${m.abstractShort ? `<div class="brainstorm-row-abstract muted">${m.abstractShort}</div>` : ''}
      </div>
      <div class="brainstorm-row-actions">${addBtn}</div>
    </div>`;
}

function _directionsSectionHtml() {
  const enabled = _directionsButtonEnabled();
  const ingest = ingestStatus(store.getState());
  // Advisory, never a hard lock: say plainly that generating now uses only the
  // papers already analyzed, and offer to wait.
  const noticeHtml = `<div class="brainstorm-ingest-notice${ingest.busy ? ' is-busy' : ''}"
       id="brainstorm-ingest-notice"${ingest.message ? '' : ' hidden'}>${escapeHtml(ingest.message)}</div>`;
  const provenance = provenanceLine(_directionsGrounding);
  const provHtml = (provenance && _rawDirections.length > 0)
    ? `<p class="brainstorm-directions-provenance muted">${escapeHtml(provenance)}</p>`
    : '';
  const disclaimerHtml = _rawDirections.length > 0
    ? `<p class="brainstorm-directions-disclaimer muted">${escapeHtml(DIRECTIONS_DISCLAIMER)}</p>`
    : '';
  return `
    <div class="brainstorm-directions-section">
      <div class="brainstorm-directions-header">
        <h3>Research Directions</h3>
        <button id="brainstorm-directions-btn" class="btn btn-accent"${enabled ? '' : ' disabled'}>Generate directions</button>
      </div>
      <p class="brainstorm-directions-intro muted">${escapeHtml(DIRECTIONS_INTRO)}</p>
      ${noticeHtml}
      ${provHtml}
      <div class="brainstorm-directions-body">
        ${_directionsBodyHtml()}
      </div>
      ${disclaimerHtml}
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

  const receiptClose = _el.querySelector('#brainstorm-receipt-close');
  if (receiptClose) {
    receiptClose.addEventListener('click', () => { _addReceipt = null; _render(); });
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
      window.dispatchEvent(new CustomEvent('rc:open-paper', { detail: { paperId }, bubbles: true }));
      window.location.hash = '#/library';
    });
  });

  _el.querySelectorAll('.brainstorm-novelty-btn, .brainstorm-novelty-retry-btn').forEach(btn => {
    btn.addEventListener('click', () => _checkNovelty(btn.dataset.directionId));
  });

  _el.querySelectorAll('.brainstorm-scaffold-btn, .brainstorm-scaffold-retry-btn').forEach(btn => {
    btn.addEventListener('click', () => _scaffoldDraft(btn.dataset.directionId));
  });

  _bindBriefEvents();
}

// Parse {si, bi} from a data-attribute element (bi optional).
function _briefIdx(el) {
  return { si: Number(el.dataset.si), bi: el.dataset.bi != null ? Number(el.dataset.bi) : -1 };
}

function _bindBriefEvents() {
  const briefBtn = _el.querySelector('#brainstorm-brief-btn');
  if (briefBtn) briefBtn.addEventListener('click', () => _generateBrief());
  const briefRetry = _el.querySelector('#brainstorm-brief-retry-btn');
  if (briefRetry) briefRetry.addEventListener('click', () => _generateBrief());

  // Edit a bullet: swap to an inline editor.
  _el.querySelectorAll('[data-brief-edit]').forEach(b => b.addEventListener('click', () => {
    _briefNoteFor = null; _briefEditing = _briefIdx(b); _render();
    const inp = _el.querySelector('.brief-edit-input');
    if (inp) { inp.focus(); inp.setSelectionRange(inp.value.length, inp.value.length); }
  }));
  _el.querySelectorAll('[data-brief-save]').forEach(b => b.addEventListener('click', () => {
    const inp = _el.querySelector('.brief-edit-input');
    const { si, bi } = _briefIdx(b);
    _brief = setBulletText(_brief, si, bi, inp ? inp.value : '');
    _briefEditing = null; _render(); _persist();
  }));
  _el.querySelectorAll('[data-brief-cancel]').forEach(b => b.addEventListener('click', () => {
    _briefEditing = null; _render();
  }));
  _el.querySelectorAll('[data-brief-del-bullet]').forEach(b => b.addEventListener('click', () => {
    const { si, bi } = _briefIdx(b); _brief = deleteBullet(_brief, si, bi); _render(); _persist();
  }));
  _el.querySelectorAll('[data-brief-up]').forEach(b => b.addEventListener('click', () => {
    const { si, bi } = _briefIdx(b); _brief = moveBullet(_brief, si, bi, -1); _render(); _persist();
  }));
  _el.querySelectorAll('[data-brief-down]').forEach(b => b.addEventListener('click', () => {
    const { si, bi } = _briefIdx(b); _brief = moveBullet(_brief, si, bi, 1); _render(); _persist();
  }));
  _el.querySelectorAll('[data-brief-add-bullet]').forEach(b => b.addEventListener('click', () => {
    const { si } = _briefIdx(b);
    _brief = addBullet(_brief, si, '');
    // open the new (last) bullet for editing straight away
    const secs = (_brief && _brief.sections) || [];
    _briefEditing = { si, bi: (secs[si] && secs[si].bullets ? secs[si].bullets.length - 1 : 0) };
    _render();
    const inp = _el.querySelector('.brief-edit-input');
    if (inp) inp.focus();
  }));
  _el.querySelectorAll('[data-brief-del-section]').forEach(b => b.addEventListener('click', () => {
    const { si } = _briefIdx(b); _brief = deleteSection(_brief, si); _render(); _persist();
  }));

  // Notes: toggle a small inline note form, save via the shared notes store.
  _el.querySelectorAll('[data-brief-note]').forEach(b => b.addEventListener('click', () => {
    const idx = _briefIdx(b);
    _briefEditing = null;
    _briefNoteFor = (_briefNoteFor && _briefNoteFor.si === idx.si && _briefNoteFor.bi === idx.bi) ? null : idx;
    _render();
    const ta = _el.querySelector('.brief-note-input');
    if (ta) ta.focus();
  }));
  _el.querySelectorAll('[data-brief-note-cancel]').forEach(b => b.addEventListener('click', () => {
    _briefNoteFor = null; _render();
  }));
  _el.querySelectorAll('[data-brief-note-save]').forEach(b => b.addEventListener('click', () => _saveBriefNote(b)));

  // Citation chip -> open that paper in the Library.
  _el.querySelectorAll('.brief-cite[data-paper-id]').forEach(chip => chip.addEventListener('click', () => {
    const paperId = chip.dataset.paperId;
    if (!paperId) return;
    window.__rcPendingPaper = paperId;
    window.dispatchEvent(new CustomEvent('rc:open-paper', { detail: { paperId }, bubbles: true }));
    window.location.hash = '#/library';
  }));
}

// ---------------------------------------------------------------------------
// Brief — grounded bullet outline (session-level). Editable, note-able.
// ---------------------------------------------------------------------------

function _briefButtonEnabled() {
  const topic = ((_el.querySelector('#brainstorm-search-input') || {}).value || '').trim() || _topic;
  const { papers, draftId } = store.getState();
  let hasPapers = false;
  for (const p of papers.values()) { if (p.paper_id !== draftId) { hasPapers = true; break; } }
  return topic.length > 0 || hasPapers || _libraryIds.size > 0;
}

async function _generateBrief() {
  if (!_el || _briefLoading) return;
  const topic = ((_el.querySelector('#brainstorm-search-input') || {}).value || '').trim() || _topic;
  if (topic) _topic = topic;
  _briefLoading = true;
  _briefError = null;
  _briefEditing = null;
  _briefNoteFor = null;
  _render();

  try {
    const data = await api.brief({ topic, sessionPaperIds: [..._libraryIds] });
    if (data && data.ok && data.brief) {
      _brief = data.brief;
      _briefError = (data.brief.sections || []).length === 0
        ? 'No grounded bullets yet — add a few papers to your library first, then generate.'
        : null;
    } else {
      _briefError = (data && data.error) || 'Could not generate a brief.';
    }
  } catch (err) {
    _briefError = err.message || 'Could not generate a brief.';
  } finally {
    _briefLoading = false;
    _render();
    _persist();
  }
}

async function _saveBriefNote(btn) {
  const { si, bi } = _briefIdx(btn);
  const ta = _el.querySelector('.brief-note-input');
  const comment = (ta ? ta.value : '').trim();
  if (!comment) { _briefNoteFor = null; _render(); return; }
  const secs = (_brief && _brief.sections) || [];
  const bullet = secs[si] && secs[si].bullets ? secs[si].bullets[bi] : null;
  const excerpt = bullet ? String(bullet.text || '') : '';
  try {
    await api.saveNote(buildNoteRecord('freeform', { comment, sourceExcerpt: excerpt }));
    showToast('Saved to Notes', 'info');
  } catch (err) {
    showToast(err.message || 'Could not save note', 'error');
  }
  _briefNoteFor = null;
  _render();
}

// --- brief rendering (model fields are pre-escaped by briefModel) ----------

function _briefSectionHtml() {
  const enabled = _briefButtonEnabled();
  const btnLabel = _briefLoading ? 'Generating…' : (_brief ? 'Regenerate brief' : 'Generate brief');
  let body;
  if (_briefLoading) {
    body = '<div class="brainstorm-brief-loading muted">Generating a grounded brief from your papers&hellip;</div>';
  } else if (_briefError && !_brief) {
    body = `<div class="brainstorm-brief-error">${escapeHtml(_briefError)}
      <button id="brainstorm-brief-retry-btn" class="btn btn-sm">Retry</button></div>`;
  } else if (_brief) {
    const model = briefModel(_brief);
    if (model.isEmpty) {
      body = `<div class="brainstorm-brief-empty muted">${escapeHtml(_briefError
        || 'No grounded bullets — add a few papers, then regenerate.')}</div>`;
    } else {
      body = `<p class="brainstorm-brief-caption muted">AI-suggested from your brainstorm &mdash; grounded in your papers, edit freely.</p>
        <div class="brief-sections">${model.sections.map(_briefSectionCardHtml).join('')}</div>`;
    }
  } else {
    body = '<div class="brainstorm-brief-empty muted">Generate a brief to turn your papers into headings with cited bullet points you can edit and note.</div>';
  }
  return `
    <div class="brainstorm-brief-section">
      <div class="brainstorm-brief-head">
        <h3>Brief</h3>
        <button id="brainstorm-brief-btn" class="btn btn-accent btn-sm"${(enabled && !_briefLoading) ? '' : ' disabled'}>${escapeHtml(btnLabel)}</button>
      </div>
      ${body}
    </div>`;
}

function _briefSectionCardHtml(sec) {
  const bullets = sec.bullets.map(b => _briefBulletHtml(sec.index, b)).join('');
  return `
    <div class="brief-section" data-si="${sec.index}">
      <div class="brief-section-head">
        <span class="brief-section-title">${sec.title}</span>
        <button class="brief-icon-btn brief-del-section" data-brief-del-section data-si="${sec.index}" title="Remove section">Remove</button>
      </div>
      <ul class="brief-bullets">${bullets}</ul>
      <button class="btn btn-xs brief-add-bullet" data-brief-add-bullet data-si="${sec.index}">+ bullet</button>
    </div>`;
}

function _briefBulletHtml(si, b) {
  const editing = _briefEditing && _briefEditing.si === si && _briefEditing.bi === b.index;
  if (editing) {
    return `<li class="brief-bullet brief-bullet-editing" data-si="${si}" data-bi="${b.index}">
      <input class="brief-edit-input" type="text" value="${escapeHtml(b.rawText)}" aria-label="Edit bullet">
      <button class="btn btn-xs" data-brief-save data-si="${si}" data-bi="${b.index}">Save</button>
      <button class="btn btn-xs btn-ghost" data-brief-cancel>Cancel</button>
    </li>`;
  }
  const noting = _briefNoteFor && _briefNoteFor.si === si && _briefNoteFor.bi === b.index;
  const cites = b.citations.map(c =>
    `<span class="brief-cite" data-paper-id="${c.paperId}" title="Open ${c.label}">${c.label}</span>`).join('');
  const citesHtml = cites
    ? `<span class="brief-cites">${cites}</span>`
    : (b.userAdded ? '<span class="brief-cite brief-cite-yours">your note</span>' : '');
  const noteForm = noting ? `
    <div class="brief-note-form">
      <textarea class="brief-note-input" rows="2" placeholder="Add a note to frame this point&hellip;"></textarea>
      <div class="brief-note-actions">
        <button class="btn btn-xs" data-brief-note-save data-si="${si}" data-bi="${b.index}">Save note</button>
        <button class="btn btn-xs btn-ghost" data-brief-note-cancel>Cancel</button>
      </div>
    </div>` : '';
  return `<li class="brief-bullet" data-si="${si}" data-bi="${b.index}">
    <div class="brief-bullet-main">
      <span class="brief-bullet-text">${b.text}</span>
      ${citesHtml}
    </div>
    <div class="brief-bullet-actions">
      <button class="brief-icon-btn" data-brief-edit data-si="${si}" data-bi="${b.index}" title="Edit">Edit</button>
      <button class="brief-icon-btn" data-brief-up data-si="${si}" data-bi="${b.index}" title="Move up">&uarr;</button>
      <button class="brief-icon-btn" data-brief-down data-si="${si}" data-bi="${b.index}" title="Move down">&darr;</button>
      <button class="brief-icon-btn" data-brief-note data-si="${si}" data-bi="${b.index}" title="Add note">+ note</button>
      <button class="brief-icon-btn" data-brief-del-bullet data-si="${si}" data-bi="${b.index}" title="Delete">&times;</button>
    </div>
    ${noteForm}
  </li>`;
}
