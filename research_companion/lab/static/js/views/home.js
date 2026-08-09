/**
 * views/home.js — Home Dashboard (route /home, default landing).
 * W3-F2.
 *
 * Zones:
 *   0/1  Hero (draft) or the "Research Companion" welcome hero (no draft)
 *   2    Next-best-action strip (up to 3 cards)
 *   3    Top-3 open suggestions compact list
 *   4    Journey sparkline + timeline
 */

import * as store from '../store.js';
import * as api from '../api.js';
import { selectNextActions } from '../nextAction.js';
import { mergeJourney, sparklinePath, severityDonut } from '../journeyHelpers.js';
import { openModal } from '../components/ingestModal.js';
import { escapeHtml, timeAgo } from '../format.js';
import { explainerBanner } from '../components/explainer.js';
import { emptyHeroModel, homeNavModel } from '../homeHelpers.js';
import { confirmDialog } from '../components/confirmDialog.js';
import { shouldSuggestNewResearch } from '../researchNudgeHelpers.js';

let _el = null;
let _unsub = null;
let _animatedIn = false;

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

export function mount(el) {
  _el = el;
  _animatedIn = false;
  _unsub = store.subscribe(['suggestions', 'journey', 'papers', 'draft', 'settings', 'citations'], _render);
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
// Draft-add with "new research" nudge
// ---------------------------------------------------------------------------

/**
 * Start adding a draft. If the current research already holds papers or a
 * draft, first offer to create a fresh research so each draft stays isolated.
 * Non-blocking: "Add to current" always proceeds with the upload modal.
 */
async function _addDraftWithNudge() {
  const state = store.getState();
  if (shouldSuggestNewResearch(state)) {
    const startNew = await confirmDialog({
      title: 'Start a new research for this draft?',
      message: 'This research already has papers. Keeping each draft in its own '
        + 'research keeps its graph, alignment and suggestions focused. You can '
        + 'also add the draft to the current research.',
      confirmLabel: 'Create new research',
      cancelLabel: 'Add to current',
    });
    if (startNew) {
      window.location.hash = '#/researches';
      return;
    }
  }
  openModal('upload', { draft: true });
}

// ---------------------------------------------------------------------------
// Render
// ---------------------------------------------------------------------------

function _render() {
  if (!_el) return;
  const state = store.getState();

  const { draftId, papers, suggestions, suggestionCounts, settings, journey, failures, citationCoverage } = state;

  const draft = draftId ? papers.get(draftId) : null;

  // Zone 1 — hero (draft) or welcome hero (no draft)
  let zone1Html;
  if (draft) {
    zone1Html = _heroHtml(draft, papers, suggestions, suggestionCounts, journey);
  } else {
    zone1Html = _emptyHeroHtml(state);
  }

  // Zone 2 — NBA strip
  const actions = selectNextActions({
    settings,
    draftId,
    papers,
    failures: failures || {},
    suggestions: Array.isArray(suggestions) ? suggestions : [],
    suggestionCounts,
    citationCoverage: citationCoverage || null,
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

  // Quick-nav row: the empty-state hero already embeds its own nav row
  // (below the product pillars); the populated (draft) hero does not, so
  // it's inserted here between the hero and the NBA strip.
  const navRow = draft ? _navRowHtml(state) : '';

  // One-time entrance animation class — applied only on the first render
  // after mount() (navigating away and back re-triggers it).
  const animate = _animatedIn ? '' : ' home-animate-in';
  _animatedIn = true;

  _el.innerHTML = `
    <div class="home-view${animate}">
      ${zone1Html}
      ${navRow}
      ${zone2Html}
      ${zone3Html}
      ${zone4Html}
    </div>`;

  // Wire zone 1 welcome hero buttons if needed
  if (!draft) {
    _el.querySelector('#home-hero-draft')?.addEventListener('click', () => {
      _addDraftWithNudge();
    });
    _el.querySelector('#home-hero-folder')?.addEventListener('click', () => {
      openModal('folder');
    });
  }

  // Wire NBA card clicks (and keyboard activation — Enter/Space)
  _el.querySelectorAll('[data-nba-route]').forEach(card => {
    const activate = () => {
      window.location.hash = card.dataset.nbaRoute;
    };
    card.addEventListener('click', activate);
    card.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        activate();
      }
    });
  });
  _el.querySelectorAll('[data-nba-action]').forEach(card => {
    const activate = () => {
      const action = card.dataset.nbaAction;
      if (action === 'open-suggestions') {
        window.dispatchEvent(new CustomEvent('rc:toggle-suggestions'));
      } else if (action === 'open-ingest') {
        openModal('upload');
      } else if (action === 'open-ingest-draft') {
        _addDraftWithNudge();
      } else if (action === 'open-citations') {
        window.dispatchEvent(new CustomEvent('rc:toggle-citations'));
      }
    };
    card.addEventListener('click', activate);
    card.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        activate();
      }
    });
  });

  // Wire quick-nav card clicks (and keyboard activation — Enter/Space)
  _el.querySelectorAll('[data-nav-route]').forEach(card => {
    const go = () => { window.location.hash = card.dataset.navRoute; };
    card.addEventListener('click', go);
    card.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); }
    });
  });
  _el.querySelectorAll('[data-nav-action]').forEach(card => {
    const go = () => {
      if (card.dataset.navAction === 'open-citations') {
        window.dispatchEvent(new CustomEvent('rc:toggle-citations'));
      }
    };
    card.addEventListener('click', go);
    card.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); }
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
        <div class="home-stat-block" title="Papers in this research besides your draft">
          <span class="home-stat-value">${paperCount}</span>
          <span class="home-stat-label">Related papers</span>
        </div>
        <div class="home-stat-block">
          <span class="home-stat-value">${addressed}/${total}</span>
          <span class="home-stat-label">Addressed</span>
        </div>
      </div>
    </div>`;
}

// ---------------------------------------------------------------------------
// Empty (no-draft) welcome hero
// ---------------------------------------------------------------------------

const _STEP_CAPTIONS = [
  { key: 'connect', label: '① Connect' },
  { key: 'add_draft', label: '② Draft' },
  { key: 'ingest', label: '③ Papers' },
  { key: 'meet_suggestions', label: '④ Review' },
];

// Product value pillars shown under the welcome hero's steps (empty state only).
const _PILLARS = [
  { t: 'A living knowledge graph', d: 'Every paper you add becomes connected concepts, methods, and results you can explore.' },
  { t: 'Answers you can trust', d: 'Ask in plain language — every claim is cited to the exact paper and section.' },
  { t: 'Submission-ready', d: 'Align your draft, verify each reference, and catch integrity issues before reviewers do.' },
];

function _emptyHeroHtml(state) {
  const model = emptyHeroModel(state);
  // meet_suggestions and done both map onto the "Review" caption.
  const activeCaptionKey = model.activeStep === 'done' ? 'meet_suggestions' : model.activeStep;

  const stepsHtml = _STEP_CAPTIONS
    .map(s => `<span class="${s.key === activeCaptionKey ? 'is-active' : ''}">${s.label}</span>`)
    .join(' · ');

  const pillarsHtml = `<div class="home-pillars">${_PILLARS.map(p =>
    `<div class="home-pillar"><div class="home-pillar-title">${escapeHtml(p.t)}</div>`
    + `<div class="home-pillar-desc">${escapeHtml(p.d)}</div></div>`).join('')}</div>`;

  return `
    <div class="home-empty-hero">
      <span class="home-eyebrow">Local-first research workspace</span>
      <h1 class="home-empty-hero-brand"><span class="home-empty-hero-mark">◆</span><span class="home-empty-hero-word">${escapeHtml(model.heading)}</span></h1>
      <p class="home-hero-tagline">Turn the literature into answers you can cite.</p>
      <p class="home-empty-hero-sub">${escapeHtml(model.subline)}</p>
      <div class="home-empty-hero-actions">
        <button class="btn btn-accent" id="home-hero-draft">★ Add your draft</button>
        <button class="btn" id="home-hero-folder">Ingest a folder</button>
      </div>
      <div class="home-empty-hero-steps">${stepsHtml}</div>
    </div>
    ${pillarsHtml}
    <div class="home-nav-section">
      <div class="home-section-eyebrow">Explore the workspace</div>
      ${_navRowHtml(state)}
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
// Quick-nav row
// ---------------------------------------------------------------------------

// Inline stroked SVGs copied verbatim from index.html's nav rail (same icon set).
const _NAV_ICONS = {
  library:  `<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="4" height="12" rx="1"/><rect x="7" y="3" width="4" height="12" rx="1"/><rect x="12" y="3" width="4" height="12" rx="1"/></svg>`,
  graph:    `<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="9" r="2"/><circle cx="3" cy="5" r="1.5"/><circle cx="15" cy="5" r="1.5"/><circle cx="3" cy="13" r="1.5"/><circle cx="15" cy="13" r="1.5"/><line x1="7.3" y1="7.7" x2="4.2" y2="6.2"/><line x1="10.7" y1="7.7" x2="13.8" y2="6.2"/><line x1="7.3" y1="10.3" x2="4.2" y2="11.8"/><line x1="10.7" y1="10.3" x2="13.8" y2="11.8"/></svg>`,
  draft:    `<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M11 2H5a1 1 0 0 0-1 1v12a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1V6l-3-4z"/><path d="M11 2v4h3"/><path d="M7 10l1.5 1.5L12 8"/></svg>`,
  ask:      `<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M15 2H3a1 1 0 0 0-1 1v9a1 1 0 0 0 1 1h3l3 3 3-3h3a1 1 0 0 0 1-1V3a1 1 0 0 0-1-1z"/></svg>`,
  timeline: `<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="9" r="7"/><polyline points="9,5 9,9 12,11"/></svg>`,
  citations:`<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M9 1.5c-2.9 0-5.2 2.3-5.2 5.2 0 3.6 5.2 9.3 5.2 9.3s5.2-5.7 5.2-9.3c0-2.9-2.3-5.2-5.2-5.2z"/><circle cx="9" cy="6.7" r="2"/></svg>`,
};

function _navRowHtml(state) {
  const cards = homeNavModel(state).map(n => {
    const attr = n.route
      ? `data-nav-route="${escapeHtml(n.route)}"`
      : `data-nav-action="${escapeHtml(n.action || '')}"`;
    const count = (n.count !== null && n.count !== undefined)
      ? `<span class="home-nav-count">${n.count}</span>` : '';
    return `
      <div class="home-nav-card" ${attr} role="button" tabindex="0">
        <span class="home-nav-icon">${_NAV_ICONS[n.key] || ''}</span>
        <span class="home-nav-text">
          <span class="home-nav-label">${escapeHtml(n.label)}${count}</span>
          <span class="home-nav-desc">${escapeHtml(n.desc)}</span>
        </span>
      </div>`;
  }).join('');
  return `<div class="home-nav-row">${cards}</div>`;
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
    const srcLabel = src.label || (src.section_id ? `${src.section_id}` : '');
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
        <path pathLength="1" d="${escapeHtml(pathStr)}"/>
      </svg>`
    : '';

  const timelineHtml = merged.length === 0
    ? `<p class="muted" style="font-size:13px">Your research journey will appear here.</p>`
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
