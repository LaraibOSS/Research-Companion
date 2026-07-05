/**
 * main.js — Boot script for the Research Lab SPA.
 *
 * 1. Fetch /api/lab and /api/papers snapshots -> populate store
 * 2. Connect SSE
 * 3. Start hash router
 * 4. Wire top bar: draft chip, connection pill
 */

import * as store from './store.js';
import * as api from './api.js';
import { connectSSE } from './sse.js';
import { startRouter, registerRoute } from './router.js';
import * as libraryView from './views/library.js';
import * as graphView from './views/graph.js';
import * as draftView from './views/draft.js';
import * as compareView from './views/compare.js';
import * as askView from './views/ask.js';

// ---------------------------------------------------------------------------
// Register routes
// ---------------------------------------------------------------------------
registerRoute('/library', libraryView);
registerRoute('/graph',   graphView);
registerRoute('/draft',   draftView);
registerRoute('/compare', compareView);
registerRoute('/ask',     askView);

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------
async function boot() {
  // Fetch snapshots
  try {
    const [lab, papers] = await Promise.all([api.getLab(), api.getPapers()]);
    store.resetFromSnapshot({ lab, papers });
  } catch (err) {
    console.warn('[boot] failed to load snapshots:', err);
  }

  // Connect SSE
  connectSSE(store, async () => {
    // Resync after reconnect gap
    try {
      const [lab, papers] = await Promise.all([api.getLab(), api.getPapers()]);
      store.resetFromSnapshot({ lab, papers });
    } catch (err) {
      console.warn('[sse] resync failed:', err);
    }
  });

  // Wire nav rail active state
  document.querySelectorAll('[data-route]').forEach(btn => {
    btn.addEventListener('click', () => {
      window.location.hash = '#' + btn.dataset.route;
    });
  });

  // Wire "+ Add papers" button in top bar
  const addBtn = document.getElementById('topbar-add');
  if (addBtn) {
    addBtn.addEventListener('click', () => {
      // Navigate to library view (which has the add input)
      window.location.hash = '#/library';
      setTimeout(() => {
        const input = document.getElementById('lib-add-input');
        if (input) input.focus();
      }, 50);
    });
  }

  // Connection pill
  function updateConnectionPill() {
    const pill = document.getElementById('connection-pill');
    if (!pill) return;
    const conn = store.getState().connection;
    pill.className = `conn-pill conn-${conn}`;
    pill.textContent = conn === 'connected' ? 'Live'
      : conn === 'reconnecting' ? 'Reconnecting...'
      : 'Offline';
  }
  store.subscribe('connection', updateConnectionPill);
  updateConnectionPill();

  // Draft chip in top bar
  function updateDraftChip() {
    const chip = document.getElementById('draft-chip');
    if (!chip) return;
    const { draftId, papers } = store.getState();
    if (!draftId) {
      chip.textContent = '';
      chip.style.display = 'none';
    } else {
      const paper = papers.get(draftId);
      const label = paper ? paper.title : draftId;
      chip.textContent = `★ ${label}`;
      chip.style.display = '';
    }
  }
  store.subscribe(['draft', 'papers'], updateDraftChip);
  updateDraftChip();

  // Start router
  const viewEl = document.getElementById('view');
  startRouter(viewEl);
}

boot();
