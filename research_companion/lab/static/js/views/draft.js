/**
 * views/draft.js — Draft alignment view (F3).
 *
 * Two-column layout:
 *   LEFT (320px)  — section list with chip strips; challenges sections get red tick
 *   RIGHT         — section detail: grouped alignment cards + evidence blockquotes
 *
 * Empty state when no draft is set.
 * Re-renders on store 'papers' and 'alignment' topic changes.
 */

import * as api from '../api.js';
import * as store from '../store.js';
import { open as drawerOpen } from '../components/drawer.js';
import { showToast } from '../components/toast.js';
import { stanceIcon, strengthColor, escapeHtml, authorsLine } from '../format.js';
import { explainerBanner } from '../components/explainer.js';
import { tip } from '../glossary.js';
// strengthColor is used for chip dot colors (paper strength) below

let _el = null;
let _unsub = null;
let _selectedSectionId = null;
let _alignment = null;   // cached { sections: [...] }

// ---------------------------------------------------------------------------
// Stance ordering
// ---------------------------------------------------------------------------

const STANCE_ORDER = ['strengthens', 'challenges', 'alternative'];

const STANCE_COLORS = {
  strengthens: '#3fb950',
  challenges:  '#f85149',
  alternative: '#58a6ff',
};

// ---------------------------------------------------------------------------
// Mount / Unmount
// ---------------------------------------------------------------------------

export function mount(el) {
  _el = el;
  _unsub = store.subscribe(['papers', 'alignment'], () => _render());
  _render();
  // Explainer banner (shown once until dismissed)
  const banner = explainerBanner(
    'draft',
    'How each section of your draft aligns with the literature.',
  );
  if (banner && el) el.prepend(banner);
}

export function unmount() {
  if (_unsub) { _unsub(); _unsub = null; }
  _el = null;
  _alignment = null;
  _selectedSectionId = null;
}

// ---------------------------------------------------------------------------
// Top-level render
// ---------------------------------------------------------------------------

async function _render() {
  if (!_el) return;

  const { draftId, papers } = store.getState();

  if (!draftId) {
    _renderNoDraft(papers);
    return;
  }

  // Show skeleton while loading alignment
  if (!_alignment) {
    _el.innerHTML = `
      <div class="draft-layout">
        <div class="draft-section-list">
          <div class="skeleton-line" style="width:80%;margin:12px 16px"></div>
          <div class="skeleton-line" style="width:65%;margin:8px 16px"></div>
          <div class="skeleton-line" style="width:72%;margin:8px 16px"></div>
        </div>
        <div class="draft-detail">
          <div class="skeleton-line" style="width:60%;margin:16px 0"></div>
          <div class="skeleton-line" style="width:90%;margin:8px 0"></div>
          <div class="skeleton-line" style="width:75%;margin:8px 0"></div>
        </div>
      </div>
    `;
  }

  // Load / refresh alignment
  try {
    _alignment = await api.getDraftAlignment();
  } catch (err) {
    if (!_el) return;
    _el.innerHTML = `<div class="draft-error muted">Could not load alignment: ${escapeHtml(err.message)}</div>`;
    return;
  }

  if (!_el) return;

  const sections = (_alignment && _alignment.sections) || [];

  // Default to first section
  if (!_selectedSectionId && sections.length > 0) {
    _selectedSectionId = sections[0].section_id;
  }

  _renderColumns(sections);
}

// ---------------------------------------------------------------------------
// No-draft empty state
// ---------------------------------------------------------------------------

function _renderNoDraft(papers) {
  const paperList = [...papers.values()];

  const listHtml = paperList.length === 0
    ? `<p class="muted" style="margin:12px 0">No papers in library yet.</p>`
    : `<ul class="draft-paper-list">
        ${paperList.map(p => `
          <li class="draft-paper-item" data-paper-id="${escapeHtml(p.paper_id)}">
            ${escapeHtml(p.title || p.paper_id)}
          </li>
        `).join('')}
       </ul>`;

  _el.innerHTML = `
    <div class="draft-empty-state">
      <div class="empty-icon">📝</div>
      <div class="empty-title">Set your draft to unlock alignment</div>
      <div class="empty-sub muted">Select a paper below to mark it as your draft manuscript.</div>
      ${listHtml}
    </div>
  `;

  // Wire paper clicks
  _el.querySelectorAll('.draft-paper-item').forEach(item => {
    item.addEventListener('click', async () => {
      const paperId = item.dataset.paperId;
      try {
        await api.setDraft(paperId);
        store.setDraft(paperId);
        showToast('Draft set', 'info');
        _render();
      } catch (err) {
        showToast(`Failed to set draft: ${err.message}`, 'error');
      }
    });
  });
}

// ---------------------------------------------------------------------------
// Two-column layout
// ---------------------------------------------------------------------------

function _renderColumns(sections) {
  _el.innerHTML = `
    <div class="draft-layout">
      <div class="draft-section-list" id="draft-section-list"></div>
      <div class="draft-detail" id="draft-detail"></div>
    </div>
  `;

  _renderSectionList(sections);
  _renderDetail(sections);
}

// ---------------------------------------------------------------------------
// Left column: section list
// ---------------------------------------------------------------------------

function _renderSectionList(sections) {
  const listEl = _el.querySelector('#draft-section-list');
  if (!listEl) return;

  if (sections.length === 0) {
    listEl.innerHTML = `<div class="muted" style="padding:16px">No sections found.</div>`;
    return;
  }

  listEl.innerHTML = sections.map((sec, idx) => {
    const hasChallenges = (sec.alignments || []).some(a => a.relation === 'challenges');
    const isActive = sec.section_id === _selectedSectionId;

    const { papers: _papers } = store.getState();
    const chipHtml = (sec.alignments || []).map(a => {
      const stanceColor = STANCE_COLORS[a.relation] || '#8b949e';
      const icon = stanceIcon(a.relation);
      // dot color: use the paper's strength color, falling back to unscored gray
      const paper = _papers.get(a.paper_id);
      const dotColor = strengthColor(paper && paper.strength ? paper.strength.band : null);
      // first word of first author OR first 15 chars of title
      let label = '';
      if (a.paper_title) {
        label = a.paper_title.length > 15 ? a.paper_title.slice(0, 15) : a.paper_title;
      }
      return `<span class="draft-chip" style="color:${escapeHtml(stanceColor)}" title="${escapeHtml(a.paper_title || '')}">
        <span style="color:${escapeHtml(dotColor)}">&#9679;</span>${escapeHtml(icon)} ${escapeHtml(label)}
      </span>`;
    }).join('');

    return `
      <div class="draft-section-row${isActive ? ' draft-section-active' : ''}${hasChallenges ? ' draft-section-challenges' : ''}"
           data-section-id="${escapeHtml(sec.section_id)}">
        <div class="draft-section-title-row">
          <span class="draft-section-num">§${idx + 1}</span>
          <span class="draft-section-name">${escapeHtml(sec.title || sec.section_id)}</span>
        </div>
        <div class="draft-chip-strip">${chipHtml}</div>
      </div>
    `;
  }).join('');

  listEl.querySelectorAll('.draft-section-row').forEach(row => {
    row.addEventListener('click', () => {
      _selectedSectionId = row.dataset.sectionId;
      _renderSectionList(sections);
      _renderDetail(sections);
    });
  });
}

// ---------------------------------------------------------------------------
// Right column: section detail
// ---------------------------------------------------------------------------

function _renderDetail(sections) {
  const detailEl = _el.querySelector('#draft-detail');
  if (!detailEl) return;

  const secIdx = sections.findIndex(s => s.section_id === _selectedSectionId);
  const sec = secIdx >= 0 ? sections[secIdx] : null;

  if (!sec) {
    detailEl.innerHTML = `<div class="muted" style="padding:16px">Select a section.</div>`;
    return;
  }

  const alignments = sec.alignments || [];

  if (alignments.length === 0) {
    detailEl.innerHTML = `
      <div class="draft-detail-header">
        <h2 class="draft-detail-title">§${secIdx + 1} ${escapeHtml(sec.title || sec.section_id)}</h2>
      </div>
      <div class="draft-empty-align muted">No papers aligned to this section yet.</div>
    `;
    return;
  }

  // Counts line
  const counts = { strengthens: 0, challenges: 0, alternative: 0 };
  for (const a of alignments) {
    if (counts[a.relation] !== undefined) counts[a.relation]++;
  }
  const countParts = [];
  if (counts.strengthens) countParts.push(`${counts.strengthens} strengthen`);
  if (counts.challenges)  countParts.push(`${counts.challenges} challenges`);
  if (counts.alternative) countParts.push(`${counts.alternative} alternative`);
  const countsLine = `${alignments.length} paper${alignments.length !== 1 ? 's' : ''}: ${countParts.join(' · ')}`;

  // Group by stance
  const groups = {
    strengthens: alignments.filter(a => a.relation === 'strengthens'),
    challenges:  alignments.filter(a => a.relation === 'challenges'),
    alternative: alignments.filter(a => a.relation === 'alternative'),
  };

  const groupHtml = STANCE_ORDER.map(relation => {
    const items = groups[relation];
    if (!items || items.length === 0) return '';
    return items.map(a => _renderAlignCard(a, relation, sec.section_id)).join('');
  }).join('');

  detailEl.innerHTML = `
    <div class="draft-detail-header">
      <h2 class="draft-detail-title">§${secIdx + 1} ${escapeHtml(sec.title || sec.section_id)}</h2>
      <div class="draft-counts muted">${escapeHtml(countsLine)}</div>
    </div>
    <div class="draft-align-cards">${groupHtml}</div>
    <div class="draft-detail-footer">
      <a class="draft-graph-link" href="#/graph?section=${encodeURIComponent(sec.section_id)}">view in graph &rarr;</a>
    </div>
  `;

  // Wire paper title clicks -> library drawer
  detailEl.querySelectorAll('.draft-paper-link').forEach(link => {
    link.addEventListener('click', (e) => {
      e.preventDefault();
      const pid = link.dataset.paperId;
      if (pid) _openPaperDrawer(pid);
    });
  });
}

// ---------------------------------------------------------------------------
// Alignment card
// ---------------------------------------------------------------------------

function _renderAlignCard(a, relation, sectionId) {
  const color = STANCE_COLORS[relation] || '#8b949e';
  const icon  = stanceIcon(relation);
  const relevancePct = a.relevance != null ? Math.round(a.relevance * 100) : 0;

  const evidenceHtml = (a.evidence || []).map(ev => {
    const verifiedBadge = ev.verified
      ? `<span class="badge badge-ok"${tip('verified')}>&#10003; verified</span>${ev.match ? `<span class="muted ev-match">${escapeHtml(ev.match)}</span>` : ''}`
      : `<span class="badge badge-warn"${tip('unverified')}>unverified</span>`;
    return `
      <blockquote class="evidence-quote draft-evidence">
        <p>${escapeHtml(ev.quote || '')}</p>
        <footer>${verifiedBadge}</footer>
      </blockquote>
    `;
  }).join('');

  return `
    <div class="draft-align-card" style="border-left:3px solid ${escapeHtml(color)}">
      <div class="draft-stance-banner" style="color:${escapeHtml(color)}"${tip(relation)}>
        <span class="draft-stance-icon">${escapeHtml(icon)}</span>
        <span class="draft-stance-word">${escapeHtml(relation)}</span>
      </div>
      <a class="draft-paper-link" href="#" data-paper-id="${escapeHtml(a.paper_id)}">
        ${escapeHtml(a.paper_title || a.paper_id)}
      </a>
      <div class="draft-relevance-row">
        <div class="draft-relevance-bar-bg">
          <div class="draft-relevance-bar-fg" style="width:${relevancePct}%;background:${escapeHtml(color)}"></div>
        </div>
        <span class="muted">${relevancePct}%</span>
      </div>
      ${a.rationale ? `<p class="draft-rationale">${escapeHtml(a.rationale)}</p>` : ''}
      ${evidenceHtml}
    </div>
  `;
}

// ---------------------------------------------------------------------------
// Open library drawer for a paper
// ---------------------------------------------------------------------------

function _openPaperDrawer(paperId) {
  const { papers } = store.getState();
  const paper = papers.get(paperId);
  if (!paper) return;
  const html = `
    <div class="drawer-header">
      <h2 class="drawer-title">${escapeHtml(paper.title || 'Untitled')}</h2>
      <div class="muted">${escapeHtml(authorsLine(paper.authors || [], paper.year))}</div>
    </div>
    <div class="drawer-section">
      <div class="drawer-section-title">Paper ID</div>
      <div>${escapeHtml(paper.paper_id)}</div>
    </div>
  `;
  drawerOpen(html);
}
