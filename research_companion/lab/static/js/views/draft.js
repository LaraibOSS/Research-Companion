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
import { draftSectionModel } from '../draftHelpers.js';
import { buildNoteRecord } from '../noteRecord.js';
import { claimAuditBadge, claimAuditSummaryLine, CLAIM_AUDIT_DISCLAIMER } from '../claimAuditHelpers.js';
import { sectionFromHash } from '../handoffHelpers.js';
// strengthColor is used for chip dot colors (paper strength) below

let _el = null;
let _unsub = null;
let _selectedSectionId = null;
let _alignment = null;   // cached { sections: [...] }
let _audit = null;       // last GET /api/claim-audit?target=draft payload
let _auditing = false;
let _auditError = null;
// True when the section list is the draft's OWN outline (no alignment computed
// yet) rather than per-paper alignment — drives the "Analyze this draft"
// affordance. See draftSectionModel().
let _fromOutline = false;
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
  _unsub = store.subscribe(['papers', 'alignment', 'activity'], () => {
    // The claim-audit job publishes JobStarted/JobFinished on 'activity'.
    // Clearing the in-flight flag first lets the _render below fetch the
    // stored result, so badges appear without a manual reload.
    if (_auditing) {
      const { activeJobs } = store.getState();
      const stillRunning = activeJobs
        && [...activeJobs.values()].some(j => j && j.kind === 'claim-audit');
      if (!stillRunning) _auditing = false;
    }
    _render();
  });
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
  _fromOutline = false;
  _selectedSectionId = null;
  _opportunities = null;
  _oppExpandedSections = new Set();
  _oppExpandedInitialized = false;
  _oppRegistry = [];
  _alignRegistry = [];
  _audit = null;
  _auditing = false;
  _auditError = null;
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

  // Load / refresh the stored claim audit. Non-fatal: an absent or failed
  // audit just means no badges, never a blocked alignment view. Skipped while
  // a check is in flight so an in-progress run does not clear the last result.
  if (!_auditing) {
    try {
      const data = await api.getClaimAudit('draft');
      _audit = (data && data.audit) || null;
    } catch {
      _audit = null;
    }
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

  // Section list = per-paper alignment when it exists; otherwise fall back to
  // the draft's OWN outline (GET /api/sections) so a freshly-created or
  // just-set draft shows its sections instead of "No sections found."
  let sections = (_alignment && _alignment.sections) || [];
  _fromOutline = false;
  if (sections.length === 0) {
    let outline = [];
    try {
      outline = await api.getSections();
    } catch {
      outline = [];
    }
    const model = draftSectionModel(sections, outline);
    sections = model.sections;
    _fromOutline = model.fromOutline;
  }

  if (!_el) return;

  // A caller may name the section: views/suggestions.js links to
  // #/draft?section=<id> so "this suggestion is about section 4" lands there.
  // That link existed and this view never read it, so it always opened the
  // first section. Only honoured when the id is really one of ours.
  const asked = sectionFromHash(window.location.hash);
  if (asked && sections.some(s => s.section_id === asked)) {
    _selectedSectionId = asked;
  }

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
    ${_toolbarHtml()}
    <div class="draft-layout">
      <div class="draft-section-list" id="draft-section-list"></div>
      <div class="draft-detail" id="draft-detail"></div>
    </div>
  `;

  _wireToolbar();
  _renderSectionList(sections);
  _renderDetail(sections);
}

// ---------------------------------------------------------------------------
// Toolbar: "Analyze this draft" (bulk-align every library paper against the
// current draft). Alignment normally runs at ingest time; a draft created or
// set afterwards has none, so this is the one-click, opt-in way to (re)run it.
// ---------------------------------------------------------------------------

// Count non-draft library papers that finished analysis (can be aligned).
function _analyzablePaperCount() {
  const { draftId, papers } = store.getState();
  let n = 0;
  for (const p of papers.values()) {
    if (p.paper_id !== draftId && p.status === 'done') n += 1;
  }
  return n;
}

// True while the bulk-align job is in flight — derived from the shared active-
// jobs map (set by JobStarted, cleared by JobFinished) rather than a local flag,
// so the button auto-resets when the job ends even across re-renders.
function _analyzeJobRunning() {
  const { activeJobs } = store.getState();
  if (!activeJobs) return false;
  for (const job of activeJobs.values()) {
    if (job.kind === 'analyze') return true;
  }
  return false;
}

function _toolbarHtml() {
  const count = _analyzablePaperCount();
  const running = _analyzeJobRunning();
  const hint = (_fromOutline && !running)
    ? `<span class="draft-toolbar-hint muted">This draft hasn't been analyzed against your library yet.</span>`
    : '';
  const label = running ? 'Analyzing…' : 'Analyze this draft';
  const disabled = (running || count === 0) ? 'disabled' : '';
  const titleAttr = count === 0
    ? 'title="Add and analyze papers first"'
    : `title="Aligns all ${count} analyzed paper${count !== 1 ? 's' : ''} in your library against this draft (uses your model)"`;
  // Claim audit is opt-in and costs a model call per cited passage, so it is
  // a separate action from Analyze rather than part of it.
  const hasAlignments = (_alignment && (_alignment.sections || [])
    .some(s => (s.alignments || []).length > 0));
  const auditLabel = _auditing ? 'Checking citations…' : 'Check citations';
  const auditDisabled = (!hasAlignments || _auditing || running) ? 'disabled' : '';
  const summaryLine = claimAuditSummaryLine(_audit && _audit.summary);

  return `
    <div class="draft-toolbar">
      ${hint}
      <button class="btn btn-sm btn-accent draft-analyze-btn" id="draft-analyze-btn" ${disabled} ${titleAttr}>
        ${escapeHtml(label)}
      </button>
      <button class="btn btn-sm btn-secondary draft-audit-btn" id="draft-audit-btn" type="button"
              title="Check whether each cited passage actually supports what we said about it (uses your model)"
              ${auditDisabled}>
        ${escapeHtml(auditLabel)}
      </button>
    </div>
    ${_auditError ? `<div class="draft-audit-error">${escapeHtml(_auditError)}</div>` : ''}
    ${summaryLine ? `<div class="draft-audit-summary">
        <span>${escapeHtml(summaryLine)}</span>
        <span class="muted draft-audit-note">${escapeHtml(CLAIM_AUDIT_DISCLAIMER)}</span>
      </div>` : ''}`;
}

function _wireToolbar() {
  const btn = _el.querySelector('#draft-analyze-btn');
  if (btn) btn.addEventListener('click', _analyzeDraft);
  const auditBtn = _el.querySelector('#draft-audit-btn');
  if (auditBtn) auditBtn.addEventListener('click', _runAudit);
}

// ---------------------------------------------------------------------------
// Claim audit (opt-in; NOT_SUPPORTED is the only adverse outcome)
// ---------------------------------------------------------------------------

/** Match a stored audit back to the evidence it was computed for.
 *  Keyed on section + paper + quote so a re-ordered alignment never labels
 *  the wrong passage; anything that does not match shows no badge at all. */
function _auditFor(sectionId, paperId, quote) {
  const sections = (_audit && _audit.sections) || [];
  const sec = sections.find(s => String(s.section_id || '') === String(sectionId || ''));
  if (!sec) return null;
  const align = (sec.alignments || []).find(a => String(a.paper_id || '') === String(paperId || ''));
  if (!align) return null;
  const hit = (align.evidence || []).find(e => String(e.quote || '') === String(quote || ''));
  return hit ? hit.audit : null;
}

function _auditBadgeHtml(sectionId, paperId, quote) {
  const b = claimAuditBadge(_auditFor(sectionId, paperId, quote));
  if (!b.show) return '';
  const detail = b.reason ? `${b.title} — ${b.reason}` : b.title;
  return `<span class="draft-audit-badge audit-${escapeHtml(b.tone)}"
           title="${escapeHtml(detail)}">${escapeHtml(b.label)}</span>`;
}

async function _runAudit() {
  if (_auditing) return;
  _auditing = true;
  _auditError = null;
  _render();
  try {
    const res = await api.runClaimAudit('draft');
    if (!res || !res.ok) {
      _auditError = (res && res.error) || 'Could not start the citation check.';
      _auditing = false;
      _render();
      return;
    }
    showToast('Checking citations against their sources…', 'info');
    // the job publishes JobStarted/JobFinished on 'activity'; _render refetches
  } catch (err) {
    _auditError = err.message || 'Could not start the citation check.';
    _auditing = false;
    _render();
  }
}

async function _analyzeDraft() {
  if (_analyzeJobRunning()) return;
  const btn = _el && _el.querySelector('#draft-analyze-btn');
  if (btn) { btn.disabled = true; btn.textContent = 'Analyzing…'; }  // optimistic until JobStarted arrives
  try {
    const res = await api.analyzeDraft();
    if (res && res.ok) {
      showToast(`Analyzing ${res.total} paper${res.total !== 1 ? 's' : ''} against your draft…`, 'info');
      // The bulk-align job publishes AlignmentReady per paper (repaints as
      // sections populate) and JobStarted/JobFinished (drives the button state).
    } else {
      showToast((res && res.error) || 'Could not start analysis.', 'error');
      if (btn) { btn.disabled = _analyzablePaperCount() === 0; btn.textContent = 'Analyze this draft'; }
    }
  } catch (err) {
    showToast(`Analysis failed to start: ${err.message}`, 'error');
    if (btn) { btn.disabled = false; btn.textContent = 'Analyze this draft'; }
  }
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

  const saveBtn = form.querySelector('.draft-note-save');
  saveBtn.addEventListener('click', async () => {
    const comment = ((textarea && textarea.value) || '').trim();
    if (!comment) { form.remove(); return; }
    // A freeform note carries no paper_id, so the server's (paper_id,
    // draft_section_id) dedupe can't catch a rapid double-click here —
    // guard it client-side instead (mirrors reader/paper/ask Save handlers).
    if (saveBtn.disabled) return;
    saveBtn.disabled = true;
    try {
      await api.saveNote(buildNoteRecord('freeform', { sectionId, sectionTitle, comment }));
      showToast('Saved to Notes', 'info');
    } catch (err) {
      showToast(`Failed to save note: ${err.message}`, 'error');
    } finally {
      saveBtn.disabled = false;
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
        <footer>${verifiedBadge}${_auditBadgeHtml(sectionId, a.paper_id, ev.quote || '')}<span class="ev-open-hint muted">&#8599; open in source</span></footer>
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
