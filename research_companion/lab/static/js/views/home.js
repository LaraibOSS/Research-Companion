/**
 * views/home.js — Home Dashboard (route /home, default landing).
 * W3-F2.
 *
 * Zones:
 *   0/1  Hero (or onboarding if no draft + tour not dismissed)
 *   2    Next-best-action strip (up to 3 cards)
 *   3    Top-3 open suggestions compact list
 *   4    Journey sparkline + timeline
 */

import * as store from '../store.js';
import * as api from '../api.js';
import { selectNextActions } from '../nextAction.js';
import { mergeJourney, sparklinePath, severityDonut } from '../journeyHelpers.js';
import { onboardingStep, renderOnboarding } from '../components/onboarding.js';
import { openModal } from '../components/ingestModal.js';
import { escapeHtml, timeAgo } from '../format.js';
import { explainerBanner } from '../components/explainer.js';

let _el = null;
let _unsub = null;

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

export function mount(el) {
  _el = el;
  _unsub = store.subscribe(['suggestions', 'journey', 'papers', 'draft', 'settings'], _render);
  api.getJourney()
    .then(data => store.setJourney(data))
    .catch(err => console.warn('[home] journey fetch failed', err));
  _render();
  // Explainer banner (shown once until dismissed)
  const banner = explainerBanner(
    'home',
    'Your research journey at a glance — start with the suggested next action.',
  );
  if (banner && el) el.prepend(banner);
}

export function unmount() {
  if (_unsub) { _unsub(); _unsub = null; }
  _el = null;
}

// ---------------------------------------------------------------------------
// Render
// ---------------------------------------------------------------------------

function _render() {
  if (!_el) return;
  const state = store.getState();

  const { draftId, papers, suggestions, suggestionCounts, settings, journey, failures } = state;

  const draft = draftId ? papers.get(draftId) : null;
  const tourDismissed = _localStorage('rc.tourDismissed');
  const showOnboarding = (!draftId || !_hasPapers(papers, draftId)) && !tourDismissed;

  // Zone 1 — hero or onboarding
  let zone1Html;
  if (showOnboarding) {
    zone1Html = `<div id="home-zone1-ob"></div>`;
  } else if (draft) {
    zone1Html = _heroHtml(draft, papers, suggestions, suggestionCounts, journey);
  } else {
    zone1Html = _skeletonHtml('home-hero', 80);
  }

  // Zone 2 — NBA strip
  const actions = selectNextActions({
    settings,
    draftId,
    papers,
    failures: failures || {},
    suggestions: Array.isArray(suggestions) ? suggestions : [],
    suggestionCounts,
  });
  const zone2Html = _nbaHtml(actions);

  // Zone 3 — top-3 open suggestions
  const openSugs = (Array.isArray(suggestions) ? suggestions : [])
    .filter(s => s.status === 'open')
    .slice(0, 3);
  const totalOpen = (suggestionCounts && suggestionCounts.open) || 0;
  const zone3Html = _sugsHtml(openSugs, totalOpen);

  // Zone 4 — journey
  const zone4Html = _journeyHtml(journey);

  _el.innerHTML = `
    <div class="home-view">
      ${zone1Html}
      ${zone2Html}
      ${zone3Html}
      ${zone4Html}
    </div>`;

  // Wire zone 1 onboarding if needed
  if (showOnboarding) {
    const obEl = _el.querySelector('#home-zone1-ob');
    if (obEl) {
      renderOnboarding(state, obEl, {
        openIngest: (tab) => openModal(tab),
        onDismiss: () => _render(),
      });
    }
  }

  // Wire NBA card clicks
  _el.querySelectorAll('[data-nba-route]').forEach(card => {
    card.addEventListener('click', () => {
      window.location.hash = card.dataset.nbaRoute;
    });
  });
  _el.querySelectorAll('[data-nba-action]').forEach(card => {
    card.addEventListener('click', () => {
      const action = card.dataset.nbaAction;
      if (action === 'open-suggestions') {
        window.dispatchEvent(new CustomEvent('rc:toggle-suggestions'));
      } else if (action === 'open-ingest') {
        openModal('single');
      }
    });
  });
}

// ---------------------------------------------------------------------------
// Hero card
// ---------------------------------------------------------------------------

function _heroHtml(draft, papers, suggestions, suggestionCounts, journey) {
  const title = escapeHtml(draft.title || draft.paper_id || 'Untitled');

  // Version from journey
  let versionLabel = '';
  if (journey && Array.isArray(journey.versions) && journey.versions.length > 0) {
    const latest = journey.versions[journey.versions.length - 1];
    versionLabel = `v${latest.version}`;
  }

  // Last activity
  let lastActivity = '';
  if (journey && Array.isArray(journey.events) && journey.events.length > 0) {
    lastActivity = timeAgo(journey.events[0].at);
  } else if (journey && Array.isArray(journey.versions) && journey.versions.length > 0) {
    const latest = journey.versions[journey.versions.length - 1];
    lastActivity = timeAgo(latest.added_at);
  }

  // Stat blocks
  const open = (suggestionCounts && suggestionCounts.open) || 0;
  const bySev = (suggestionCounts && suggestionCounts.by_severity) || null;
  const donutSegs = severityDonut({ open, by_severity: bySev });
  const donutSvg = _donutSvg(donutSegs, 28);

  // Paper count (non-draft)
  let paperCount = 0;
  for (const [id, p] of papers) {
    if (id !== draft.paper_id && !p.is_draft) paperCount++;
  }

  // Addressed count
  const addressed = Array.isArray(suggestions)
    ? suggestions.filter(s => s.status === 'addressed').length
    : 0;
  const total = Array.isArray(suggestions) ? suggestions.length : 0;

  return `
    <div class="home-hero">
      <div class="home-hero-main">
        <div class="home-hero-title">${title}</div>
        <div class="home-hero-meta">
          ${versionLabel ? `<span class="home-version-pill">${escapeHtml(versionLabel)}</span>` : ''}
          ${lastActivity ? `<span class="home-last-activity">Last activity ${escapeHtml(lastActivity)}</span>` : ''}
        </div>
      </div>
      <div class="home-hero-stats">
        <div class="home-stat-block">
          ${donutSvg}
          <span class="home-stat-value">${open}</span>
          <span class="home-stat-label">Open</span>
        </div>
        <div class="home-stat-block">
          <span class="home-stat-value">${paperCount}</span>
          <span class="home-stat-label">Papers</span>
        </div>
        <div class="home-stat-block">
          <span class="home-stat-value">${addressed}/${total}</span>
          <span class="home-stat-label">Addressed</span>
        </div>
      </div>
    </div>`;
}

function _donutSvg(segs, size) {
  if (segs.length === 1 && segs[0].frac === 1) {
    return `<svg class="home-donut" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
      <circle cx="${size/2}" cy="${size/2}" r="${size/2 - 2}" fill="none"
        stroke="${segs[0].color}" stroke-width="4"/>
    </svg>`;
  }

  const cx = size / 2;
  const cy = size / 2;
  const r = size / 2 - 3;
  const circumference = 2 * Math.PI * r;

  let offset = 0;
  let paths = '';
  for (const seg of segs) {
    const len = seg.frac * circumference;
    paths += `<circle cx="${cx}" cy="${cy}" r="${r}" fill="none"
      stroke="${seg.color}" stroke-width="5"
      stroke-dasharray="${len.toFixed(2)} ${(circumference - len).toFixed(2)}"
      stroke-dashoffset="${(-offset).toFixed(2)}"
      transform="rotate(-90 ${cx} ${cy})"/>`;
    offset += len;
  }

  return `<svg class="home-donut" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">${paths}</svg>`;
}

// ---------------------------------------------------------------------------
// NBA strip
// ---------------------------------------------------------------------------

function _nbaHtml(actions) {
  if (!actions || actions.length === 0) return '';

  const cards = actions.map((action, i) => {
    const isPrimary = i === 0;
    const cls = `home-nba-card${isPrimary ? ' primary' : ''}`;
    const tag = isPrimary ? `<div class="home-nba-tag">Do this next</div>` : '';
    const dataAttr = action.route
      ? `data-nba-route="${escapeHtml(action.route)}"`
      : `data-nba-action="${escapeHtml(action.action || '')}"`;

    return `
      <div class="${cls}" ${dataAttr} role="button" tabindex="0">
        ${tag}
        <div class="home-nba-label">${escapeHtml(action.label)}</div>
        <div class="home-nba-detail">${escapeHtml(action.detail)}</div>
      </div>`;
  }).join('');

  return `
    <div>
      <div class="home-section-title">Next Steps</div>
      <div class="home-nba-strip">${cards}</div>
    </div>`;
}

// ---------------------------------------------------------------------------
// Suggestions compact list
// ---------------------------------------------------------------------------

function _sugsHtml(openSugs, totalOpen) {
  if (totalOpen === 0) return '';

  const rows = openSugs.map(s => {
    const sevColor = `var(--sev-${escapeHtml(s.severity || 'low')})`;
    // Source label disambiguates same-titled suggestions targeting different sections
    // (older payloads carry only section_id, no label)
    const src = s.source || {};
    const srcLabel = src.label || (src.section_id ? `§${src.section_id}` : '');
    const srcHtml = srcLabel
      ? `<span class="home-sug-src muted">${escapeHtml(srcLabel)}</span>`
      : '';
    return `
      <div class="home-sug-row">
        <span class="home-sug-dot" style="background:${sevColor}"></span>
        <span class="home-sug-title">${escapeHtml(s.title || '')}</span>
        ${srcHtml}
        <span class="home-sug-kind">${escapeHtml(s.kind || '')}</span>
      </div>`;
  }).join('');

  const footer = totalOpen > 3
    ? `<div class="home-sugs-footer"><a href="#/suggestions">View all ${totalOpen} suggestions</a></div>`
    : '';

  return `
    <div>
      <div class="home-section-title">Open Suggestions</div>
      <div class="home-sugs-list">
        ${rows}
        ${footer}
      </div>
    </div>`;
}

// ---------------------------------------------------------------------------
// Journey section
// ---------------------------------------------------------------------------

function _journeyHtml(journey) {
  if (!journey) {
    return `
      <div>
        <div class="home-section-title">Journey</div>
        <div class="home-skeleton" style="height:48px;margin-bottom:16px"></div>
        <div class="home-skeleton" style="height:120px"></div>
      </div>`;
  }

  const versions = journey.versions || [];
  const events = journey.events || [];
  const countsOverTime = journey.counts_over_time || [];
  const merged = mergeJourney(versions, events);

  const pathStr = sparklinePath(countsOverTime, 920, 48);
  const sparklineHtml = pathStr
    ? `<svg class="home-sparkline" viewBox="0 0 920 48" preserveAspectRatio="none">
        <path d="${escapeHtml(pathStr)}"/>
      </svg>`
    : '';

  const timelineHtml = merged.length === 0
    ? `<p class="muted" style="font-size:13px">No journey events yet.</p>`
    : merged.map(entry => `
      <div class="home-journey-entry ${escapeHtml(entry.icon)}">
        <div class="home-journey-dot"></div>
        <div class="home-journey-content">
          <div class="home-journey-title">${escapeHtml(entry.title)}</div>
          ${entry.sub ? `<div class="home-journey-sub">${escapeHtml(entry.sub)}</div>` : ''}
        </div>
        <div class="home-journey-time">${escapeHtml(timeAgo(entry.at))}</div>
      </div>`).join('');

  return `
    <div>
      <div class="home-section-title">Journey</div>
      ${sparklineHtml}
      <div class="home-journey-list">${timelineHtml}</div>
    </div>`;
}

// ---------------------------------------------------------------------------
// Skeleton
// ---------------------------------------------------------------------------

function _skeletonHtml(cls, height) {
  return `<div class="${cls} home-skeleton" style="height:${height}px"></div>`;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function _localStorage(key) {
  try { return localStorage.getItem(key); } catch { return null; }
}

function _hasPapers(papers, draftId) {
  for (const [id, p] of papers) {
    if (id !== draftId && !p.is_draft) return true;
  }
  return false;
}
