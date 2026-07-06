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
  suggestionCounts: { open: 0, by_severity: null },
  suggestions: [],
  lastAddressedIds: [],
  settings: {},
  views: [],
  journey: null,
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
