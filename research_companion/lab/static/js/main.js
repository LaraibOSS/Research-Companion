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
import * as brainstormView from './views/brainstorm.js';
import * as timelineView from './views/timeline.js';
import * as gapsView from './views/gaps.js';
import * as reportView from './views/report.js';
import * as settingsView from './views/settings.js';
import { initGraph, setMapping } from './graph/graphview.js';
import { nodeToVis, edgeToVis } from './graph/mapping.js';
import { openModal } from './components/ingestModal.js';
import { ensureActiveResearch } from './researchGuard.js';
import { mountDock } from './components/progressDock.js';
import { mountSuggestionsPanel } from './components/suggestionsPanel.js';
import { mountConversePanel } from './components/conversePanel.js';
import { mountCitationsPanel } from './components/citationsPanel.js';
import { mountPlacementPanel } from './components/placementPanel.js';
import { mountReader } from './components/reader.js';
import { bannerText, coverageCounts, missingCount, coverageSource } from './citationsHelpers.js';
import { needsMetadata, metadataBannerText } from './libraryHelpers.js';
import { activitySummary, citationDownloadTargets, isResolving } from './activityHelpers.js';
import { themeVars, applyTheme } from './theme.js';
import * as suggestionsView from './views/suggestions.js';
import * as researchesView from './views/researches.js';
import * as notesView from './views/notes.js';
import { openHelpPanel } from './components/helpPanel.js';
import { mountWorkspaceSwitcher } from './components/workspaceSwitcher.js';
import { openWelcomeDialog } from './components/welcomeDialog.js';
import { noKeyBannerModel, shouldShowWelcome, WELCOME_SEEN_KEY } from './keyPromptHelpers.js';

// ---------------------------------------------------------------------------
// Register routes
// ---------------------------------------------------------------------------
registerRoute('/home',        homeView);
registerRoute('/brainstorm',  brainstormView);
registerRoute('/library',     libraryView);
registerRoute('/graph',       graphView);
registerRoute('/draft',       draftView);
registerRoute('/timeline',    timelineView);
registerRoute('/gaps',        gapsView);
registerRoute('/report',      reportView);
registerRoute('/compare',     compareView);
registerRoute('/ask',         askView);
registerRoute('/settings',    settingsView);
registerRoute('/suggestions', suggestionsView);
registerRoute('/researches',  researchesView);
registerRoute('/notes',       notesView);

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
      // First-launch key prompt: show once, or whenever the LLM key is missing.
      let seen = false;
      try { seen = localStorage.getItem(WELCOME_SEEN_KEY) === '1'; } catch { /* noop */ }
      if (shouldShowWelcome(settings, { seen })) {
        openWelcomeDialog(settings);
      }
    }
  } catch (err) {
    console.warn('[boot] failed to load snapshots:', err);
  }

  // Initial suggestions fetch (non-fatal)
  api.getSuggestions().then(data => {
    if (data && Array.isArray(data.suggestions)) {
      store.setSuggestions(data.suggestions);
    }
  }).catch(err => {
    console.warn('[boot] failed to load suggestions:', err);
  });

  // Initial citation coverage fetch (non-fatal) — W5-C3
  api.getDraftCitations()
    .then(d => store.setCitationCoverage(d))
    .catch(() => {});

  // Initial workspaces fetch (non-fatal) + topbar switcher (W4-F1)
  api.getWorkspaces()
    .then(data => store.setWorkspaces(data))
    .catch(() => {});
  mountWorkspaceSwitcher(store, api);

  // Boot hydration for background jobs (non-fatal; 404 = older server) — W5-ACT
  api.getJobs()
    .then(d => store.setActiveJobs(d && d.jobs ? d.jobs : []))
    .catch(() => {});

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
    addBtn.addEventListener('click', () => ensureActiveResearch(() => openModal('upload')));
  }

  // Mount the persistent progress dock
  const dockEl = document.getElementById('dock');
  if (dockEl) {
    mountDock(dockEl, store, api);
  }

  // Mount the global suggestions panel (F3) once at boot
  mountSuggestionsPanel(store, api);

  // Mount the global companion converse panel (F4) once at boot
  mountConversePanel(api);

  // Mount the citations coverage panel (W5-C3) once at boot
  mountCitationsPanel(store, api);

  // Mount the citation placement panel (draft-quality check) once at boot
  mountPlacementPanel(store, api);

  // Mount the paper reader overlay once at boot (listens for rc:open-reader)
  mountReader(store, api);

  // Activity indicator (W5-ACT)
  function updateActivityIndicator() {
    const indicator = document.getElementById('activity-indicator');
    const labelEl   = document.getElementById('activity-label');
    if (!indicator || !labelEl) return;
    const { activeJobs } = store.getState();
    const { count, label } = activitySummary(activeJobs);
    if (count > 0) {
      indicator.style.display = '';
      labelEl.textContent = label;
    } else {
      indicator.style.display = 'none';
      labelEl.textContent = '';
    }
  }
  store.subscribe('activity', updateActivityIndicator);
  updateActivityIndicator();

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

  // Ack tour step when suggestions panel opened
  window.addEventListener('rc:toggle-suggestions', () => {
    localStorage.setItem('rc.tourMetSuggestions', '1');
  });

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

  // No-key banner: blocking (amber) when the LLM key is missing, softer when
  // only the optional Hugging Face token is missing.
  const noKeyBanner = document.getElementById('no-key-banner');
  const noKeyText = document.getElementById('no-key-text');
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
    const model = noKeyBannerModel(settings);
    noKeyBanner.classList.toggle('visible', model.visible);
    noKeyBanner.classList.toggle('soft', model.tone === 'soft');
    if (model.visible) {
      if (noKeyText) noKeyText.textContent = model.message + ' → ';
      if (noKeyLink) noKeyLink.textContent = model.linkText;
    }
  }
  store.subscribe('settings', updateNoKeyBanner);
  updateNoKeyBanner();

  // Help button — full help panel (W3-F7)
  const helpBtn = document.getElementById('topbar-help');
  if (helpBtn) {
    helpBtn.addEventListener('click', () => openHelpPanel());
  }

  // Placement button — citation placement panel (draft-quality check)
  const placementBtn = document.getElementById('topbar-placement');
  if (placementBtn) {
    placementBtn.addEventListener('click', () => {
      window.dispatchEvent(new CustomEvent('rc:toggle-placement'));
    });
  }

  // Citations coverage banner (W5-C3)
  const citationsBanner     = document.getElementById('citations-banner');
  const citationsBannerText = document.getElementById('citations-banner-text');
  const citationsBannerLink = document.getElementById('citations-banner-link');
  const citationsBannerCollapse = document.getElementById('citations-banner-collapse');

  if (citationsBannerLink) {
    citationsBannerLink.addEventListener('click', (e) => {
      e.preventDefault();
      window.dispatchEvent(new CustomEvent('rc:toggle-citations'));
    });
  }
  if (citationsBannerCollapse) {
    citationsBannerCollapse.addEventListener('click', () => {
      try { sessionStorage.setItem('rc.citationsBannerCollapsed', '1'); } catch { /* noop */ }
      if (citationsBanner) citationsBanner.classList.remove('visible');
    });
  }

  function updateCitationsBanner() {
    if (!citationsBanner) return;
    const { draftId, citationCoverage, activeJobs } = store.getState();
    const counts = coverageCounts(citationCoverage);
    const collapsed = (() => {
      try { return sessionStorage.getItem('rc.citationsBannerCollapsed') === '1'; } catch { return false; }
    })();
    const visible = !!(
      draftId &&
      counts.total > 0 &&
      counts.in_library < counts.total &&
      !collapsed
    );
    citationsBanner.classList.toggle('visible', visible);
    if (visible && citationsBannerText) {
      const downloadTargets = citationDownloadTargets(activeJobs);
      if (downloadTargets.size > 0) {
        citationsBannerText.textContent =
          `Downloading cited papers… (${counts.in_library} of ${counts.total} in library)`;
      } else if (isResolving(activeJobs)) {
        citationsBannerText.textContent = 'Checking references…';
      } else {
        citationsBannerText.textContent = bannerText(counts, coverageSource(citationCoverage));
      }
    }
  }
  store.subscribe(['citations', 'draft', 'activity'], updateCitationsBanner);
  updateCitationsBanner();

  // Missing-metadata banner (aggregate) — session-collapsible
  const metadataBanner         = document.getElementById('metadata-banner');
  const metadataBannerTextEl   = document.getElementById('metadata-banner-text');
  const metadataBannerLink     = document.getElementById('metadata-banner-link');
  const metadataBannerCollapse = document.getElementById('metadata-banner-collapse');

  if (metadataBannerLink) {
    metadataBannerLink.addEventListener('click', (e) => {
      e.preventDefault();
      window.location.hash = '#/library';
    });
  }
  if (metadataBannerCollapse) {
    metadataBannerCollapse.addEventListener('click', () => {
      try { sessionStorage.setItem('rc.metadataBannerCollapsed', '1'); } catch { /* noop */ }
      if (metadataBanner) metadataBanner.classList.remove('visible');
    });
  }

  function updateMetadataBanner() {
    if (!metadataBanner) return;
    const { papers } = store.getState();
    let count = 0;
    for (const paper of papers.values()) {
      if (needsMetadata(paper)) count++;
    }
    const collapsed = (() => {
      try { return sessionStorage.getItem('rc.metadataBannerCollapsed') === '1'; } catch { return false; }
    })();
    const visible = count > 0 && !collapsed;
    metadataBanner.classList.toggle('visible', visible);
    if (visible && metadataBannerTextEl) {
      metadataBannerTextEl.textContent = metadataBannerText(count);
    }
  }
  store.subscribe('papers', updateMetadataBanner);
  updateMetadataBanner();

  // Start router
  const viewEl = document.getElementById('view');
  startRouter(viewEl);
}

boot();
