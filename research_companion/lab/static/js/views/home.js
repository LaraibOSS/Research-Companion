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
import { emptyHeroModel } from '../homeHelpers.js';
import { confirmDialog } from '../components/confirmDialog.js';
import { shouldSuggestNewResearch } from '../researchNudgeHelpers.js';

let _el = null;
let _unsub = null;

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

export function mount(el) {
  _el = el;
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

  _el.innerHTML = `
    <div class="home-view">
      ${zone1Html}
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
        openModal('upload');
      } else if (action === 'open-ingest-draft') {
        _addDraftWithNudge();
      } else if (action === 'open-citations') {
        window.dispatchEvent(new CustomEvent('rc:toggle-citations'));
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

// ---------------------------------------------------------------------------
// Empty (no-draft) welcome hero
// ---------------------------------------------------------------------------

const _STEP_CAPTIONS = [
  { key: 'connect', label: '① Connect' },
  { key: 'add_draft', label: '② Draft' },
  { key: 'ingest', label: '③ Papers' },
  { key: 'meet_suggestions', label: '④ Review' },
];

function _emptyHeroHtml(state) {
  const model = emptyHeroModel(state);
  // meet_suggestions and done both map onto the "Review" caption.
  const activeCaptionKey = model.activeStep === 'done' ? 'meet_suggestions' : model.activeStep;

  const stepsHtml = _STEP_CAPTIONS
    .map(s => `<span class="${s.key === activeCaptionKey ? 'is-active' : ''}">${s.label}</span>`)
    .join(' · ');

  return `
    <div class="home-empty-hero">
      <div class="home-empty-hero-brand"><span class="home-empty-hero-mark">◆</span> <span>${escapeHtml(model.heading)}</span></div>
      <p class="home-empty-hero-sub">${escapeHtml(model.subline)}</p>
      <div class="home-empty-hero-actions">
        <button class="btn btn-accent" id="home-hero-draft">★ Add your draft</button>
        <button class="btn" id="home-hero-folder">Ingest a folder</button>
      </div>
      <div class="home-empty-hero-steps">${stepsHtml}</div>
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
