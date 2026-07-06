/**
 * main.js — Boot script for the Research Lab SPA.
 *
 * 1. Apply theme from localStorage (synchronous pre-paint already done
 *    by the inline script; here we also fetch /api/settings and let the
 *    server value win).
 * 2. Fetch /api/lab, /api/papers, /api/settings snapshots -> populate store
 * 3. Connect SSE
 * 4. Start hash router
 * 5. Wire top bar: draft chip, connection pill, suggestions bell, no-key banner
 * W3-F1.
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
import * as homeView from './views/home.js';
import * as timelineView from './views/timeline.js';
import * as settingsView from './views/settings.js';
import { initGraph, setMapping } from './graph/graphview.js';
import { nodeToVis, edgeToVis } from './graph/mapping.js';
import { openModal } from './components/ingestModal.js';
import { mountDock } from './components/progressDock.js';
import { themeVars, applyTheme } from './theme.js';

// ---------------------------------------------------------------------------
// Register routes
// ---------------------------------------------------------------------------
registerRoute('/home',     homeView);
registerRoute('/library',  libraryView);
registerRoute('/graph',    graphView);
registerRoute('/draft',    draftView);
registerRoute('/timeline', timelineView);
registerRoute('/compare',  compareView);
registerRoute('/ask',      askView);
registerRoute('/settings', settingsView);

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

  // Fetch snapshots (including settings)
  try {
    const [lab, papers, settings] = await Promise.all([
      api.getLab(),
      api.getPapers(),
      api.getSettings().catch(() => null),
    ]);
    store.resetFromSnapshot({ lab, papers });
    if (settings) {
      store.setSettings(settings);
      // Server theme wins — override localStorage
      const t = themeVars(settings);
      applyTheme(t);
    }
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

  // Draft chip in top bar — clicking navigates to the Draft view
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

  // Suggestions bell
  const bellBtn = document.getElementById('topbar-bell');
  const bellBadge = document.getElementById('bell-badge');

  if (bellBtn) {
    bellBtn.addEventListener('click', () => {
      // F3 can set window.__suggestionsBellClick OR listen for the CustomEvent
      if (typeof window.__suggestionsBellClick === 'function') {
        window.__suggestionsBellClick();
      }
      window.dispatchEvent(new CustomEvent('rc:toggle-suggestions'));
    });
  }

  function updateBell() {
    if (!bellBadge) return;
    const { suggestionCounts } = store.getState();
    const open = (suggestionCounts && suggestionCounts.open) || 0;
    if (open === 0) {
      bellBadge.classList.remove('visible');
      bellBadge.textContent = '';
      return;
    }
    bellBadge.textContent = open > 99 ? '99+' : String(open);
    bellBadge.classList.add('visible');

    // Color: highest severity present in by_severity
    const sev = (suggestionCounts && suggestionCounts.by_severity) || null;
    let color = 'var(--sev-low)';
    if (sev) {
      if (sev.critical) color = 'var(--sev-critical)';
      else if (sev.high) color = 'var(--sev-high)';
      else if (sev.medium) color = 'var(--sev-medium)';
    }
    bellBadge.style.background = color;
  }
  store.subscribe('suggestions', updateBell);
  updateBell();

  // No-key amber banner
  const noKeyBanner = document.getElementById('no-key-banner');
  const noKeyLink = document.getElementById('no-key-link');
  if (noKeyLink) {
    noKeyLink.addEventListener('click', (e) => {
      e.preventDefault();
      window.location.hash = '#/settings';
    });
  }

  function updateNoKeyBanner() {
    if (!noKeyBanner) return;
    const { settings } = store.getState();
    if (!settings || !settings.keys) {
      noKeyBanner.classList.remove('visible');
      return;
    }
    const provider = settings.provider || 'anthropic';
    const keyName = provider === 'openai' ? 'openai_api_key' : 'anthropic_api_key';
    const keySet = settings.keys[keyName] && settings.keys[keyName].set;
    noKeyBanner.classList.toggle('visible', !keySet);
  }
  store.subscribe('settings', updateNoKeyBanner);
  updateNoKeyBanner();

  // Help button (minimal drawer)
  const helpBtn = document.getElementById('topbar-help');
  if (helpBtn) {
    helpBtn.addEventListener('click', () => {
      _showHelpDrawer();
    });
  }

  // Start router
  const viewEl = document.getElementById('view');
  startRouter(viewEl);
}

// ---------------------------------------------------------------------------
// Minimal Help drawer (F7 builds the full version)
// ---------------------------------------------------------------------------
function _showHelpDrawer() {
  const existing = document.getElementById('help-drawer-overlay');
  if (existing) { existing.remove(); return; }

  const overlay = document.createElement('div');
  overlay.id = 'help-drawer-overlay';
  overlay.className = 'drawer-overlay open';

  const drawer = document.createElement('div');
  drawer.className = 'drawer open';
  drawer.innerHTML = `
    <button class="drawer-close" id="help-close" aria-label="Close help">&times;</button>
    <div class="drawer-content">
      <div class="drawer-header">
        <h2 class="drawer-title">Help &amp; Documentation</h2>
      </div>
      <p style="font-size:14px;line-height:1.6;color:var(--color-fg-dim)">
        Research Companion Lab helps you analyse papers, compare findings, and draft with evidence.
        Full documentation is available in the PDF guide and on GitHub.
      </p>
      <div style="display:flex;flex-direction:column;gap:8px;margin-top:16px">
        <a href="/static/guide.pdf" target="_blank" rel="noopener" class="btn btn-secondary btn-sm">PDF User Guide &#8599;</a>
        <a href="https://github.com" target="_blank" rel="noopener" class="btn btn-secondary btn-sm">GitHub &#8599;</a>
      </div>
    </div>`;
  overlay.appendChild(drawer);
  document.body.appendChild(overlay);

  const close = () => overlay.remove();
  overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
  document.getElementById('help-close').addEventListener('click', close);
}

boot();
