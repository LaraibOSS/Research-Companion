/**
 * store.js — Module-level application state for the Research Lab.
 * DOM-free: no document/window references.
 *
 * State shape:
 *   papers:     Map<paper_id, paper>
 *   draftId:    string | null
 *   sections:   []
 *   lab:        { counts: {} }
 *   jobs:       Map<string, job>
 *   connection: 'connected' | 'reconnecting' | 'disconnected'
 *   failures:   {}
 *   graphSeq:   number
 *   ingestLog:  Array<{ok, label, path?, stage?, error?, paperId, seq}>
 *   ingestManifest: Array<{path, name, relPath, status, reason}>
 *   views:      Array<{view_id, name, created_at, source, node_ids, pinned}>
 */

import { applyEvent as _applyEvent } from './reducer.js';
import { diffStatuses, countOpen, highestOpenSeverity } from './components/suggestionHelpers.js';

// ---------------------------------------------------------------------------
// Module state
// ---------------------------------------------------------------------------

const _state = {
  papers: new Map(),
  draftId: null,
  sections: [],
  lab: { counts: {} },
  jobs: new Map(),
  connection: 'disconnected',
  failures: {},
  graphSeq: 0,
  ingestLog: [],
  ingestManifest: [],
  suggestionCounts: { open: 0, by_severity: null },
  suggestions: [],
  lastAddressedIds: [],
  settings: {},
  views: [],
  journey: null,
  workspaces: { list: [], activeId: null },
  citationCoverage: null,
  citationPlacement: null,
  activeJobs: new Map(),
};

// Subscribers: Map<topic, Set<fn>>
const _subscribers = new Map();

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Get a shallow copy of the current state (Map references are shared).
 * @returns {object}
 */
export function getState() {
  return { ..._state };
}

/**
 * Subscribe a callback to one or more topics.
 * @param {string|string[]} topics
 * @param {Function} fn  — called with no args when any of the topics change
 * @returns {() => void}  — unsubscribe function
 */
export function subscribe(topics, fn) {
  const topicList = Array.isArray(topics) ? topics : [topics];
  for (const topic of topicList) {
    if (!_subscribers.has(topic)) _subscribers.set(topic, new Set());
    _subscribers.get(topic).add(fn);
  }
  return () => {
    for (const topic of topicList) {
      const set = _subscribers.get(topic);
      if (set) set.delete(fn);
    }
  };
}

/**
 * Notify all subscribers for the given topics.
 * @param {string[]} topics
 */
export function notify(topics) {
  const seen = new Set();
  for (const topic of topics) {
    const set = _subscribers.get(topic);
    if (!set) continue;
    for (const fn of set) {
      if (!seen.has(fn)) {
        seen.add(fn);
        try { fn(); } catch (e) { console.error('[store] subscriber error', e); }
      }
    }
  }
}

/**
 * Apply an SSE event via the reducer and notify changed topics.
 * @param {object} evt
 * @returns {string[]} changed topics
 */
export function applyAndNotify(evt) {
  const topics = _applyEvent(_state, evt);
  if (topics.length) notify(topics);
  return topics;
}

/**
 * Update connection status and notify 'connection' subscribers.
 * @param {'connected'|'reconnecting'|'disconnected'} status
 */
export function setConnection(status) {
  _state.connection = status;
  notify(['connection']);
}

/**
 * Reset the papers/sections/lab state from a fresh snapshot
 * (used after SSE reconnection gap).
 * @param {{ papers: object[], lab: object, sections: object[] }} snapshot
 */
export function resetFromSnapshot(snapshot) {
  _state.papers.clear();
  _state.failures = {};
  _state.graphSeq = 0;
  _state.jobs = new Map();
  _state.ingestLog = [];
  _state.ingestManifest = [];

  for (const p of (snapshot.papers || [])) {
    _state.papers.set(p.paper_id, p);
  }
  if (snapshot.lab) {
    _state.lab = snapshot.lab;
    if (snapshot.lab.draft_id !== undefined) {
      _state.draftId = snapshot.lab.draft_id;
    }
  }
  if (snapshot.sections) {
    _state.sections = snapshot.sections;
  }
  notify(['papers', 'lab', 'sections', 'connection']);
}

/**
 * Set draftId and notify 'draft' topic.
 * @param {string|null} id
 */
export function setDraft(id) {
  _state.draftId = id;
  notify(['draft']);
}

/**
 * Set suggestion counts and notify 'suggestions' subscribers.
 * @param {{ open: number, by_severity?: object|null }} counts
 */
export function setSuggestionCounts(counts) {
  _state.suggestionCounts = counts;
  notify(['suggestions']);
}

/**
 * Set the full suggestions list. Diffs vs previous to track addressed IDs.
 * Also recomputes suggestionCounts from the list (keeps in sync with F1 bell).
 * Notifies ['suggestions'].
 * @param {Array} list
 */
export function setSuggestions(list) {
  const prev = _state.suggestions;
  const next = Array.isArray(list) ? list : [];
  const { addressed } = diffStatuses(prev, next);
  _state.lastAddressedIds = addressed;
  _state.suggestions = next;

  // Recompute counts from list
  const open = countOpen(next);
  const bySeverity = {};
  for (const s of next) {
    if (s.status === 'open') {
      bySeverity[s.severity] = (bySeverity[s.severity] || 0) + 1;
    }
  }
  _state.suggestionCounts = {
    open,
    by_severity: Object.keys(bySeverity).length > 0 ? bySeverity : null,
  };

  notify(['suggestions']);
}

/**
 * Set settings from GET /api/settings and notify 'settings' subscribers.
 * @param {object} settings
 */
export function setSettings(settings) {
  _state.settings = settings;
  notify(['settings']);
}

/**
 * Set the saved-views list and notify 'views' subscribers.
 * @param {Array} views
 */
export function setViews(views) {
  _state.views = Array.isArray(views) ? views : [];
  notify(['views']);
}

/**
 * Set the workspaces snapshot (from GET /api/workspaces) and notify
 * 'workspaces' subscribers (W4-F1, additive).
 * @param {{ active?: string|null, workspaces?: Array }} data
 */
export function setWorkspaces(data) {
  const d = data || {};
  _state.workspaces = {
    list: Array.isArray(d.workspaces) ? d.workspaces : [],
    activeId: d.active || null,
  };
  notify(['workspaces']);
}

/**
 * Set journey data and notify 'journey' subscribers.
 * @param {object} data
 */
export function setJourney(data) {
  _state.journey = data;
  notify(['journey']);
}

// ---------------------------------------------------------------------------
// Converse conversations (W3-F4)
// ---------------------------------------------------------------------------

// conversations: Map<threadKey, { conversationId, messages, threadState }>
// Managed entirely by conversePanel.js; store just provides the container.
// Exposed here so other modules could inspect thread history if needed.
if (!_state.conversations) {
  _state.conversations = new Map();
}

/**
 * Get the conversations Map (session-only; not persisted).
 * @returns {Map}
 */
export function getConversations() {
  return _state.conversations;
}

// ---------------------------------------------------------------------------
// Citation coverage state (W5-C3)
// ---------------------------------------------------------------------------

/**
 * Set the full citation coverage response and notify 'citations' subscribers.
 * Called at boot (non-fatal) and on panel open (lazy fetch).
 * @param {object|null} data — GET /api/draft/citations response shape
 */
export function setCitationCoverage(data) {
  _state.citationCoverage = data || null;
  notify(['citations']);
}

/**
 * Set the full citation-placement response and notify 'placement' subscribers.
 * Called on panel open (lazy fetch). Shape: GET /api/draft/placement response.
 * @param {object|null} data
 */
export function setCitationPlacement(data) {
  _state.citationPlacement = data || null;
  notify(['placement']);
}

// ---------------------------------------------------------------------------
// Background-activity state (W5-ACT)
// ---------------------------------------------------------------------------

/**
 * Replace the activeJobs Map from a GET /api/jobs array and notify 'activity'.
 * Each item in the array must have { job_id, kind, label, target }.
 * Called at boot for hydration (non-fatal GET /api/jobs).
 * @param {Array} list — [{job_id, kind, label, target, status}] or null/undefined
 */
export function setActiveJobs(list) {
  _state.activeJobs = new Map();
  const items = Array.isArray(list) ? list : [];
  for (const job of items) {
    _state.activeJobs.set(job.job_id, {
      kind:   job.kind   || '',
      label:  job.label  || '',
      target: job.target || '',
    });
  }
  notify(['activity']);
}

// ---------------------------------------------------------------------------
// Ingest manifest state (folder-ingest per-file status list)
// ---------------------------------------------------------------------------

/**
 * Seed the ingest manifest from the scan/ingest file list at the start of a
 * folder ingest run and notify 'ingestManifest' subscribers.
 * @param {Array} files — [{path, name, rel_path, already_in_library}]
 */
export function startIngestManifest(files) {
  const rows = (Array.isArray(files) ? files : []).map(f => ({
    path: f.path || '',
    name: f.name || f.path || '',
    relPath: f.rel_path || f.name || f.path || '',
    status: f.already_in_library ? 'skipped' : 'queued',
    reason: f.already_in_library ? 'already in library' : '',
  }));
  _state.ingestManifest = rows;
  notify(['ingestManifest']);
}
