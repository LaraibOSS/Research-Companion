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
import { opportunityModel } from '../opportunityHelpers.js';
import { buildNoteRecord } from '../noteRecord.js';
// strengthColor is used for chip dot colors (paper strength) below

let _el = null;
let _unsub = null;
let _selectedSectionId = null;
let _alignment = null;   // cached { sections: [...] }
// Evidence quotes for the currently-rendered detail, indexed by data-quote-idx.
// Kept out of HTML attributes (quotes may contain quotes/newlines).
let _evidenceQuotes = [];

// Uncited-paper opportunities (GET /api/draft/opportunities), cached raw and
// re-normalized via opportunityModel() on every section-list render.
let _opportunities = null;         // { draft_id, sections: [...] } | null
let _oppExpandedSections = new Set(); // section_ids whose opportunity block is expanded
// Seeds _oppExpandedSections with every section that has opportunities the
// FIRST time they load, so the block defaults to expanded rather than
// collapsed; a user's own toggle (add/delete on _oppExpandedSections) is
// never overwritten again after that (see _render()).
let _oppExpandedInitialized = false;
// Suggestion+context lookup for opportunity row buttons (quote / Save note),
// indexed by data-opp-idx. Kept out of HTML attributes for the same reason
// as _evidenceQuotes above (quotes/titles may contain quotes/newlines).
let _oppRegistry = [];
// Cited-alignment evidence lookup for the per-quote Save-note button,
// indexed by data-align-idx. Kept out of HTML attributes for the same reason
// as _evidenceQuotes/_oppRegistry above (quotes/titles may contain quotes/
// newlines unsafe for HTML attributes).
let _alignRegistry = [];

// ---------------------------------------------------------------------------
// Stance ordering
// ---------------------------------------------------------------------------

const STANCE_ORDER = ['strengthens', 'challenges', 'alternative'];

const STANCE_COLORS = {
  strengthens: '#3fb950',
  challenges:  '#f85149',
  alternative: '#58a6ff',
};

// Focus hint text for an opportunity row, derived from its relation.
const OPP_FOCUS_HINTS = {
  strengthens: 'Could strengthen this section',
  challenges:  'Challenges the claims in this section',
  alternative: 'Offers an alternative approach for this section',
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
  _opportunities = null;
  _oppExpandedSections = new Set();
  _oppExpandedInitialized = false;
  _oppRegistry = [];
  _alignRegistry = [];
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

  // Load / refresh uncited-paper opportunities. Non-fatal: a failure here
  // must not block the (already-working) alignment view — just render with
  // zero opportunity blocks.
  try {
    _opportunities = await api.getOpportunities();
  } catch {
    _opportunities = { draft_id: null, sections: [] };
  }

  // Seed the expand-state set ONCE, so every section that has opportunities
  // defaults to expanded rather than collapsed. Gated on _oppExpandedInitialized
  // staying false until a load has ACTUALLY seeded >=1 section — a naive
  // "flip true on the first _render() no matter what" would wrongly latch
  // the seed as done on an early render where opportunities are still empty
  // (e.g. the very first paint, before the backend has anything to offer),
  // permanently skipping the seed once they populate on a later re-render.
  // Once at least one section IS seeded, the flag stays true so a later
  // re-render (a fresh 'papers'/'alignment' notify) never re-adds a section
  // the user has since collapsed.
  if (!_oppExpandedInitialized) {
    const oppSectionsSeed = opportunityModel((_opportunities && _opportunities.sections) || []);
    let seededAny = false;
    for (const o of oppSectionsSeed) {
      if (o.count > 0) {
        _oppExpandedSections.add(o.sectionId);
        seededAny = true;
      }
    }
    if (seededAny) _oppExpandedInitialized = true;
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

  const { draftId, papers: _draftPapers } = store.getState();
  const draftPaper = draftId ? _draftPapers.get(draftId) : null;
  const draftTitle = draftPaper ? (draftPaper.title || draftId) : draftId;

  // Uncited-paper opportunities, keyed by section_id — used here only for a
  // lightweight "+n" count badge. The full block (rationale, evidence quote,
  // Save note) renders in the detail column for the CURRENTLY SELECTED
  // section only (see _renderDetail / _renderOpportunityBlock) — a nav row
  // is too narrow for that much content, and cramming it into every row
  // would duplicate it across the whole list.
  const oppSections = opportunityModel((_opportunities && _opportunities.sections) || []);
  const oppBySectionId = new Map(oppSections.map(o => [o.sectionId, o]));

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

    // Lightweight "+n" badge — count only. The opportunities themselves
    // (rationale/evidence/Save note) render in the detail column once this
    // section is selected; see _renderDetail.
    const opp = oppBySectionId.get(sec.section_id);
    const oppBadgeHtml = (opp && opp.count > 0)
      ? `<span class="draft-opp-count-badge" title="${escapeHtml(String(opp.count))} uncited paper${opp.count !== 1 ? 's' : ''} could help here">+${opp.count}</span>`
      : '';

    return `
      <div class="draft-section-row${isActive ? ' draft-section-active' : ''}${hasChallenges ? ' draft-section-challenges' : ''}"
           data-section-id="${escapeHtml(sec.section_id)}">
        <div class="draft-section-title-row">
          <span class="draft-section-num">${idx + 1}.</span>
          <span class="draft-section-name">${escapeHtml(sec.title || sec.section_id)}</span>
          ${oppBadgeHtml}
          <button class="draft-note-btn" type="button" data-section-id="${escapeHtml(sec.section_id)}" title="Add a note to this section" aria-label="Add note to section">&#65291; note</button>
          <button class="draft-read-btn" data-section-id="${escapeHtml(sec.section_id)}" title="Read this section" aria-label="Read section">Read</button>
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

  // Read button on each section row -> open the reader at that draft section.
  listEl.querySelectorAll('.draft-read-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();  // don't trigger the row's select-and-repaint
      if (!draftId) return;
      window.dispatchEvent(new CustomEvent('rc:open-reader', {
        detail: { paperId: draftId, sectionId: btn.dataset.sectionId, title: draftTitle },
      }));
    });
  });

  // "+ note" button on each section row -> tiny inline free-form note form.
  listEl.querySelectorAll('.draft-note-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();  // don't trigger the row's select-and-repaint
      const sectionId = btn.dataset.sectionId;
      const sec = sections.find(s => s.section_id === sectionId);
      _toggleSectionNoteForm(btn, sectionId, sec ? (sec.title || sectionId) : sectionId);
    });
  });
}

// ---------------------------------------------------------------------------
// Section-row free-form note — tiny inline form, no modal.
// ---------------------------------------------------------------------------

/**
 * Toggle a tiny inline free-form note form beneath a section row. Save posts
 * buildNoteRecord('freeform', { sectionId, sectionTitle, comment }); Cancel
 * (or an empty comment) just discards the form.
 * @param {HTMLElement} btn - the "+ note" button that was clicked
 * @param {string} sectionId
 * @param {string} sectionTitle
 */
function _toggleSectionNoteForm(btn, sectionId, sectionTitle) {
  const row = btn.closest('.draft-section-row');
  if (!row) return;

  const existing = row.querySelector('.draft-note-form');
  if (existing) { existing.remove(); return; } // toggle off

  const form = document.createElement('div');
  form.className = 'draft-note-form';
  form.innerHTML = `
    <textarea class="draft-note-input" rows="2" placeholder="Add a note…" aria-label="Note text"></textarea>
    <div class="draft-note-form-actions">
      <button type="button" class="btn btn-sm btn-accent draft-note-save">Save note</button>
      <button type="button" class="btn btn-sm btn-secondary draft-note-cancel">Cancel</button>
    </div>
  `;
  row.appendChild(form);

  // Stop clicks/keys inside the form from bubbling up to the row's
  // select-and-repaint handler.
  form.addEventListener('click', (e) => e.stopPropagation());

  const textarea = form.querySelector('.draft-note-input');
  if (textarea) textarea.focus();

  form.querySelector('.draft-note-cancel').addEventListener('click', () => form.remove());

  form.querySelector('.draft-note-save').addEventListener('click', async () => {
    const comment = ((textarea && textarea.value) || '').trim();
    if (!comment) { form.remove(); return; }
    try {
      await api.saveNote(buildNoteRecord('freeform', { sectionId, sectionTitle, comment }));
      showToast('Saved to Notes', 'info');
    } catch (err) {
      showToast(`Failed to save note: ${err.message}`, 'error');
    }
    form.remove();
  });
}

// ---------------------------------------------------------------------------
// Uncited-paper opportunities block — rendered in the detail column (right)
// for the CURRENTLY SELECTED section only, below its existing detail content.
// ---------------------------------------------------------------------------

function _renderOpportunityBlock(opp) {
  const expanded = _oppExpandedSections.has(opp.sectionId);
  const rowsHtml = expanded
    ? opp.suggestions.map(s => _renderOpportunityRow(opp, s)).join('')
    : '';

  return `
    <div class="draft-opp-block">
      <button class="draft-opp-toggle" type="button"
              data-opp-section-id="${escapeHtml(opp.sectionId)}"
              aria-expanded="${expanded ? 'true' : 'false'}">
        <span class="draft-opp-caret">${expanded ? '▾' : '▸'}</span>
        Uncited papers that could help here (${opp.count})
      </button>
      ${expanded ? `<div class="draft-opp-rows">${rowsHtml}</div>` : ''}
    </div>
  `;
}

function _renderOpportunityRow(opp, s) {
  const color = STANCE_COLORS[s.relation] || '#8b949e';
  const icon = stanceIcon(s.relation);
  const relevancePct = Math.round((s.relevance || 0) * 100);
  const hint = OPP_FOCUS_HINTS[s.relation] || '';

  // Register the full suggestion (+ section context) out-of-band; the quote
  // and Save-note buttons reference it by index (mirrors _evidenceQuotes:
  // quotes/titles may contain characters unsafe for HTML attributes).
  const idx = _oppRegistry.push({
    paperId: s.paperId,
    title: s.title,
    relation: s.relation,
    relevance: s.relevance,
    rationale: s.rationale,
    quote: s.quote,
    quoteSectionId: s.quoteSectionId,
    sectionId: opp.sectionId,
    sectionTitle: opp.sectionTitle,
  }) - 1;

  const quoteHtml = s.quote
    ? `
      <button class="draft-opp-quote-btn" type="button"
              data-opp-idx="${idx}" title="Open in source paper">
        <span class="draft-opp-quote-text">${escapeHtml(s.quote)}</span>
        <span class="ev-open-hint muted">&#8599; open in source</span>
      </button>
    `
    : '';

  return `
    <div class="draft-opp-row" style="border-left:3px solid ${escapeHtml(color)}">
      <div class="draft-opp-row-header">
        <span class="draft-stance-icon" style="color:${escapeHtml(color)}"${tip(s.relation)}>${escapeHtml(icon)}</span>
        <span class="draft-opp-title">${escapeHtml(s.title || s.paperId)}</span>
        <span class="muted draft-opp-relevance">${relevancePct}%</span>
      </div>
      ${hint ? `<div class="draft-opp-hint muted">${escapeHtml(hint)}</div>` : ''}
      ${s.rationale ? `<p class="draft-opp-rationale">${escapeHtml(s.rationale)}</p>` : ''}
      ${quoteHtml}
      <button class="draft-opp-save-btn" type="button" data-opp-idx="${idx}">Save note</button>
    </div>
  `;
}

function _wireOpportunityBlock(detailEl, sections) {
  // Toggle expand/collapse for the current section's block.
  detailEl.querySelectorAll('.draft-opp-toggle').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const sectionId = btn.dataset.oppSectionId;
      if (_oppExpandedSections.has(sectionId)) {
        _oppExpandedSections.delete(sectionId);
      } else {
        _oppExpandedSections.add(sectionId);
      }
      _renderDetail(sections);
    });
  });

  // Quote click -> open the suggested (uncited) paper in the reader at that quote.
  detailEl.querySelectorAll('.draft-opp-quote-btn').forEach(btn => {
    const openSource = () => {
      const idx = Number(btn.dataset.oppIdx);
      const rec = _oppRegistry[idx];
      if (!rec) return;
      window.dispatchEvent(new CustomEvent('rc:open-reader', {
        detail: { paperId: rec.paperId, quote: rec.quote, title: rec.title },
      }));
    };
    btn.addEventListener('click', (e) => { e.stopPropagation(); openSource(); });
  });

  // Save note -> POST /api/notes, then toast. Routed through
  // buildNoteRecord('opportunity', ...) (not a hand-built object) so the
  // saved note carries kind:"opportunity" — without this it silently
  // defaulted to kind:"freeform" server-side, which broke the Notes view's
  // Opportunity kind-filter (fix round, see task-3-report.md).
  detailEl.querySelectorAll('.draft-opp-save-btn').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const idx = Number(btn.dataset.oppIdx);
      const rec = _oppRegistry[idx];
      if (!rec || btn.disabled) return;
      btn.disabled = true;
      try {
        await api.saveNote(buildNoteRecord('opportunity', {
          paperId: rec.paperId,
          paperTitle: rec.title,
          sectionId: rec.sectionId,
          sectionTitle: rec.sectionTitle,
          relation: rec.relation,
          relevance: rec.relevance,
          rationale: rec.rationale,
          quote: rec.quote,
          quoteSectionId: rec.quoteSectionId,
        }));
        showToast('Saved to Notes', 'info');
      } catch (err) {
        showToast(`Failed to save note: ${err.message}`, 'error');
      } finally {
        btn.disabled = false;
      }
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

  // Uncited-paper opportunities for the CURRENTLY SELECTED section. Reset the
  // row registry for this render; _renderOpportunityRow fills it (mirrors
  // _evidenceQuotes). Computed here (not just in the alignments-present
  // branch below) so a section with zero *aligned* papers can still surface
  // uncited-paper opportunities.
  _oppRegistry = [];
  const oppSections = opportunityModel((_opportunities && _opportunities.sections) || []);
  const opp = oppSections.find(o => o.sectionId === sec.section_id) || null;
  const oppHtml = (opp && opp.count > 0) ? _renderOpportunityBlock(opp) : '';

  if (alignments.length === 0) {
    detailEl.innerHTML = `
      <div class="draft-detail-header">
        <h2 class="draft-detail-title">${secIdx + 1}. ${escapeHtml(sec.title || sec.section_id)}</h2>
      </div>
      <div class="draft-empty-align muted">No papers aligned to this section yet.</div>
      ${oppHtml}
    `;
    _wireOpportunityBlock(detailEl, sections);
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

  // Reset the evidence-quote / align-note registries for this render;
  // _renderAlignCard fills both.
  _evidenceQuotes = [];
  _alignRegistry = [];

  const groupHtml = STANCE_ORDER.map(relation => {
    const items = groups[relation];
    if (!items || items.length === 0) return '';
    return items.map(a => _renderAlignCard(a, relation, sec.section_id, sec.title)).join('');
  }).join('');

  detailEl.innerHTML = `
    <div class="draft-detail-header">
      <h2 class="draft-detail-title">${secIdx + 1}. ${escapeHtml(sec.title || sec.section_id)}</h2>
      <div class="draft-counts muted">${escapeHtml(countsLine)}</div>
    </div>
    <div class="draft-align-cards">${groupHtml}</div>
    <div class="draft-detail-footer">
      <a class="draft-graph-link" href="#/graph?section=${encodeURIComponent(sec.section_id)}">view in graph &rarr;</a>
    </div>
    ${oppHtml}
  `;

  // Wire paper title clicks -> library drawer
  detailEl.querySelectorAll('.draft-paper-link').forEach(link => {
    link.addEventListener('click', (e) => {
      e.preventDefault();
      const pid = link.dataset.paperId;
      if (pid) _openPaperDrawer(pid);
    });
  });

  // Wire evidence-quote clicks -> open the cited source paper at the quote.
  detailEl.querySelectorAll('.evidence-clickable').forEach(bq => {
    const openSource = () => {
      const pid = bq.dataset.paperId;
      if (!pid) return;
      const idx = Number(bq.dataset.quoteIdx);
      const quote = _evidenceQuotes[idx] || '';
      const { papers } = store.getState();
      const cited = papers.get(pid);
      const title = cited ? (cited.title || pid) : pid;
      window.dispatchEvent(new CustomEvent('rc:open-reader', {
        detail: { paperId: pid, quote, title },
      }));
    };
    bq.addEventListener('click', openSource);
    bq.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        openSource();
      }
    });
  });

  // Wire the cited-alignment "Save note" buttons (beside each evidence quote).
  detailEl.querySelectorAll('.draft-align-save-btn').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const idx = Number(btn.dataset.alignIdx);
      const rec = _alignRegistry[idx];
      if (!rec) return;
      try {
        await api.saveNote(buildNoteRecord('alignment', {
          paperId: rec.paperId,
          paperTitle: rec.paperTitle,
          sectionId: rec.sectionId,
          sectionTitle: rec.sectionTitle,
          relation: rec.relation,
          relevance: rec.relevance,
          rationale: rec.rationale,
          quote: rec.quote,
        }));
        showToast('Saved to Notes', 'info');
      } catch (err) {
        showToast(`Failed to save note: ${err.message}`, 'error');
      }
    });
  });

  _wireOpportunityBlock(detailEl, sections);
}

// ---------------------------------------------------------------------------
// Alignment card
// ---------------------------------------------------------------------------

function _renderAlignCard(a, relation, sectionId, sectionTitle) {
  const color = STANCE_COLORS[relation] || '#8b949e';
  const icon  = stanceIcon(relation);
  const relevancePct = a.relevance != null ? Math.round(a.relevance * 100) : 0;

  const evidenceHtml = (a.evidence || []).map(ev => {
    const verifiedBadge = ev.verified
      ? `<span class="badge badge-ok"${tip('verified')}>&#10003; verified</span>${ev.match ? `<span class="muted ev-match">${escapeHtml(ev.match)}</span>` : ''}`
      : `<span class="badge badge-warn"${tip('unverified')}>unverified</span>`;
    // Store the quote text out-of-band and reference it by index; clicking opens
    // the CITED paper in the reader at this quote.
    const quoteIdx = _evidenceQuotes.push(ev.quote || '') - 1;
    // Register the full alignment + this evidence quote out-of-band (mirrors
    // _oppRegistry: quotes/titles may contain characters unsafe for HTML
    // attributes); the beside-the-blockquote Save-note button references it
    // by index.
    const alignIdx = _alignRegistry.push({
      paperId: a.paper_id,
      paperTitle: a.paper_title,
      sectionId,
      sectionTitle,
      relation,
      relevance: a.relevance,
      rationale: a.rationale,
      quote: ev.quote || '',
    }) - 1;
    return `
      <blockquote class="evidence-quote draft-evidence evidence-clickable"
                  role="button" tabindex="0"
                  data-paper-id="${escapeHtml(a.paper_id)}" data-quote-idx="${quoteIdx}"
                  title="Open in source paper">
        <p>${escapeHtml(ev.quote || '')}</p>
        <footer>${verifiedBadge}<span class="ev-open-hint muted">&#8599; open in source</span></footer>
      </blockquote>
      <button class="draft-align-save-btn btn btn-sm btn-secondary" type="button" data-align-idx="${alignIdx}">Save note</button>
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
