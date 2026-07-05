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
import { makeSnapshotRefresher } from './snapshotRefresher.js';
import { startRouter, registerRoute } from './router.js';
import * as libraryView from './views/library.js';
import * as graphView from './views/graph.js';
import * as draftView from './views/draft.js';
import * as compareView from './views/compare.js';
import * as askView from './views/ask.js';
import { initGraph, setMapping } from './graph/graphview.js';
import { nodeToVis, edgeToVis } from './graph/mapping.js';
import { openModal } from './components/ingestModal.js';
import { mountDock } from './components/progressDock.js';

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
  // Initialize graph engine on the persistent #graph-canvas container (once, at boot)
  const graphCanvas = document.getElementById('graph-canvas');
  if (graphCanvas && typeof vis !== 'undefined') {
    setMapping({ nodeToVis, edgeToVis });
    initGraph(graphCanvas, vis);
  }

  // Fetch snapshots
  try {
    const [lab, papers] = await Promise.all([api.getLab(), api.getPapers()]);
    store.resetFromSnapshot({ lab, papers });
  } catch (err) {
    console.warn('[boot] failed to load snapshots:', err);
  }

  // Snapshot refresher: when alignment_ready fires the reducer marks
  // paper.alignmentFresh=false; we pick that up on 'papers' notify and
  // schedule a debounced GET /api/papers to pull fresh stance_counts.
  const snapshotRefresher = makeSnapshotRefresher(
    api.getPapers,
    (papers) => {
      const state = store.getState();
      for (const p of papers) {
        const existing = state.papers.get(p.paper_id);
        if (existing && p.stance_counts) {
          existing.stance_counts = p.stance_counts;
          // Clear the stale flag now that we have fresh data
          existing.alignmentFresh = true;
        }
      }
      store.notify(['papers']);
    },
    500,
  );

  store.subscribe('papers', () => {
    const { papers } = store.getState();
    for (const paper of papers.values()) {
      if (paper.alignmentFresh === false) {
        snapshotRefresher.schedule();
        break;
      }
    }
  });

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

  // Wire "+ Add papers" button in top bar -> ingest modal
  const addBtn = document.getElementById('topbar-add');
  if (addBtn) {
    addBtn.addEventListener('click', () => openModal('single'));
  }

  // Mount the persistent progress dock
  const dockEl = document.getElementById('dock');
  if (dockEl) {
    mountDock(dockEl, store, api);
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

  // Draft chip in top bar — clicking navigates to the Draft view (F4 polish)
  const draftChipEl = document.getElementById('draft-chip');
  if (draftChipEl) {
    draftChipEl.addEventListener('click', () => {
      window.location.hash = '#/draft';
    });
  }

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
