/**
 * views/ask.js — Ask view (F4).
 *
 * Centered column: question textarea + scope select + Ask button.
 * Answers rendered as markdown-lite via the pure renderAnswerHtml()
 * (node-tested; escapeHtml FIRST — LLM output never reaches innerHTML raw).
 * Citation chips: hover -> mini-card, click -> library drawer.
 * Session history kept in-memory only (cleared on reload).
 */

import * as api from '../api.js';
import * as store from '../store.js';
import { escapeHtml, authorsLine } from '../format.js';
import { open as drawerOpen } from '../components/drawer.js';
import { showToast } from '../components/toast.js';
import { openSaveViewModal } from '../components/saveViewModal.js';
import { canSave } from '../viewsHelpers.js';

// ---------------------------------------------------------------------------
// Pure: renderAnswerHtml (exported for node --test)
// ---------------------------------------------------------------------------

/**
 * Render an LLM answer as minimal markdown-lite HTML.
 *
 * SECURITY: the whole answer is passed through escapeHtml FIRST, so no
 * markup from the model (e.g. a <script> tag) can ever survive; all tags
 * below are constructed from the escaped text.
 *
 * Supports: paragraphs on blank lines, **bold**, `code` spans, "- " lists,
 * and [S#]/[#] citation tags -> <sup class="cite" data-n="#">[#]</sup>.
 *
 * @param {string|null} answer
 * @param {Array<{n:number}>} [citations]  — reserved; chips are resolved
 *   against the citations list at event time in the view
 * @returns {string} safe HTML
 */
export function renderAnswerHtml(answer, citations = []) {
  const escaped = escapeHtml(answer == null ? '' : String(answer));

  const inline = (s) => s
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\[S?(\d+)\]/g, '<sup class="cite" data-n="$1">[$1]</sup>');

  const blocks = escaped
    .split(/\n[ \t]*\n/)
    .map(b => b.trim())
    .filter(Boolean);

  return blocks.map(block => {
    const lines = block.split('\n').map(l => l.trim()).filter(Boolean);
    if (lines.length > 0 && lines.every(l => l.startsWith('- '))) {
      const items = lines.map(l => `<li>${inline(l.slice(2).trim())}</li>`).join('');
      return `<ul>${items}</ul>`;
    }
    return `<p>${inline(lines.join('<br>'))}</p>`;
  }).join('');
}

// ---------------------------------------------------------------------------
// View state (module-level; history is session-only, cleared on reload)
// ---------------------------------------------------------------------------

let _el = null;
let _pending = false;
let _history = [];       // [{ question, scopeLabel, res }] newest first
let _miniCard = null;    // floating citation mini-card element

// ---------------------------------------------------------------------------
// Mount / Unmount
// ---------------------------------------------------------------------------

export function mount(el) {
  _el = el;
  _render();
  _loadSections();
}

export function unmount() {
  _hideMiniCard();
  _el = null;
}

// ---------------------------------------------------------------------------
// Render skeleton of the view
// ---------------------------------------------------------------------------

function _render() {
  if (!_el) return;
  _el.innerHTML = `
    <div class="ask-col">
      <div class="ask-form">
        <textarea id="ask-input" class="ask-input" rows="3"
                  placeholder="Ask a question about your library..."></textarea>
        <div class="ask-form-row">
          <select id="ask-scope" class="ask-scope">
            <option value="">Whole lab</option>
          </select>
          <button id="ask-btn" class="btn btn-accent">Ask</button>
        </div>
        <div id="ask-error" class="ask-error" style="display:none"></div>
      </div>
      <div id="ask-pending" style="display:none">
        <div class="ask-skeleton">
          <div class="skeleton-line" style="width:90%"></div>
          <div class="skeleton-line" style="width:75%"></div>
          <div class="skeleton-line" style="width:82%"></div>
        </div>
      </div>
      <div id="ask-history" class="ask-history"></div>
    </div>
  `;

  const input = _el.querySelector('#ask-input');
  const btn = _el.querySelector('#ask-btn');

  btn.addEventListener('click', _submit);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      _submit();
    }
  });
  // Grow the textarea with content
  input.addEventListener('input', () => {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 240) + 'px';
  });

  // Citation chip interactions (delegated on the history container)
  const hist = _el.querySelector('#ask-history');
  hist.addEventListener('mouseover', _onCiteHover);
  hist.addEventListener('mouseout', (e) => {
    if (e.target.closest && e.target.closest('.cite')) _hideMiniCard();
  });
  hist.addEventListener('click', _onHistoryClick);

  _renderHistory();
  _setPending(_pending);
}

async function _loadSections() {
  try {
    const sections = await api.getSections();
    if (!_el) return;
    const select = _el.querySelector('#ask-scope');
    if (!select || !Array.isArray(sections)) return;
    sections.forEach((sec, idx) => {
      const opt = document.createElement('option');
      opt.value = sec.section_id || '';
      opt.textContent = `§${idx + 1} ${sec.title || sec.section_id || ''}`;
      select.appendChild(opt);
    });
  } catch {
    // No draft / sections unavailable — "Whole lab" remains the only scope
  }
}

// ---------------------------------------------------------------------------
// Submit
// ---------------------------------------------------------------------------

async function _submit() {
  if (!_el || _pending) return;
  const input = _el.querySelector('#ask-input');
  const select = _el.querySelector('#ask-scope');
  const question = (input.value || '').trim();
  if (!question) return;

  const sectionId = select.value || null;
  const scopeLabel = sectionId
    ? ((select.options[select.selectedIndex] || {}).textContent || '')
    : 'Whole lab';

  _setError(null);
  _setPending(true);
  try {
    const res = await api.ask(question, sectionId);
    _history.unshift({ question, scopeLabel, res });
    if (_el) {
      _el.querySelector('#ask-input').value = '';
      _renderHistory();
    }
  } catch (err) {
    _setError(err.message);
    showToast(`Ask failed: ${err.message}`, 'error');
  } finally {
    _setPending(false);
  }
}

function _setPending(on) {
  _pending = on;
  if (!_el) return;
  const btn = _el.querySelector('#ask-btn');
  const pendingEl = _el.querySelector('#ask-pending');
  if (btn) {
    btn.disabled = on;
    btn.textContent = on ? 'Asking...' : 'Ask';
  }
  if (pendingEl) pendingEl.style.display = on ? '' : 'none';
}

function _setError(msg) {
  if (!_el) return;
  const errEl = _el.querySelector('#ask-error');
  if (!errEl) return;
  if (msg) {
    errEl.textContent = msg;
    errEl.style.display = '';
  } else {
    errEl.textContent = '';
    errEl.style.display = 'none';
  }
}

// ---------------------------------------------------------------------------
// History rendering (newest first)
// ---------------------------------------------------------------------------

const NO_MATERIAL_RE = /no relevant material/i;

function _renderHistory() {
  if (!_el) return;
  const hist = _el.querySelector('#ask-history');
  if (!hist) return;

  hist.innerHTML = _history.map((entry, idx) => {
    const { question, scopeLabel, res } = entry;
    const citations = res.citations || [];
    const unverified = res.unverified_quotes || [];
    const muted = NO_MATERIAL_RE.test(res.answer || '');

    // Grounding strip: N sources across M papers
    const paperIds = new Set(
      ((res.grounding && res.grounding.paper_ids) && res.grounding.paper_ids.length
        ? res.grounding.paper_ids
        : citations.map(c => c.paper_id)),
    );
    const nSources = citations.length;
    const nodeIds = (res.grounding && Array.isArray(res.grounding.node_ids))
      ? res.grounding.node_ids
      : [];
    const hasSaveable = canSave(res.grounding);
    const groundingHtml = nSources > 0 ? `
      <div class="ask-grounding muted">
        Grounded in ${nSources} source${nSources !== 1 ? 's' : ''}
        across ${paperIds.size} paper${paperIds.size !== 1 ? 's' : ''}
        &mdash; <a href="#/library" class="ask-library-link">view in library</a>
      </div>` : '';
    const saveSubgraphHtml = hasSaveable ? `
      <div class="ask-save-subgraph">
        <button class="btn btn-secondary btn-sm ask-save-subgraph-btn"
                data-entry="${idx}">Save this subgraph</button>
      </div>` : '';

    const unverifiedHtml = unverified.length > 0 ? `
      <div class="ask-unverified">
        <div class="ask-unverified-title">
          &#9888; ${unverified.length} quoted span${unverified.length !== 1 ? 's' : ''}
          could not be verified against sources
        </div>
        <ul class="ask-unverified-list">
          ${unverified.map(q => {
            const s = String(q == null ? '' : q);
            const shown = s.length > 120 ? s.slice(0, 120) + '…' : s;
            return `<li>${escapeHtml(shown)}</li>`;
          }).join('')}
        </ul>
      </div>` : '';

    return `
      <div class="ask-entry" data-entry="${idx}">
        <div class="ask-question">
          <span class="ask-q-mark muted">Q</span>
          <span>${escapeHtml(question)}</span>
          <span class="ask-scope-tag muted">${escapeHtml(scopeLabel)}</span>
        </div>
        <div class="ask-answer-card${muted ? ' ask-answer-muted' : ''}">
          <div class="ask-answer-body">${renderAnswerHtml(res.answer, citations)}</div>
          ${groundingHtml}
          ${saveSubgraphHtml}
          ${unverifiedHtml}
        </div>
      </div>
    `;
  }).join('');
}

// ---------------------------------------------------------------------------
// Citation chip: hover mini-card + click -> library drawer
// ---------------------------------------------------------------------------

function _citationFor(target) {
  const chip = target.closest && target.closest('.cite');
  if (!chip) return null;
  const entryEl = chip.closest('.ask-entry');
  if (!entryEl) return null;
  const entry = _history[Number(entryEl.dataset.entry)];
  if (!entry) return null;
  const n = Number(chip.dataset.n);
  const citation = (entry.res.citations || []).find(c => c.n === n) || null;
  return citation ? { chip, citation } : null;
}

function _onCiteHover(e) {
  const hit = _citationFor(e.target);
  if (!hit) return;
  const { chip, citation } = hit;

  if (!_miniCard) {
    _miniCard = document.createElement('div');
    _miniCard.className = 'cite-minicard';
    document.body.appendChild(_miniCard);
  }
  _miniCard.innerHTML = `
    <div class="cite-minicard-title">${escapeHtml(citation.title || citation.paper_id || '')}</div>
    ${citation.section_title
      ? `<div class="cite-minicard-section muted">&sect; ${escapeHtml(citation.section_title)}</div>`
      : ''}
    ${citation.cited
      ? '<span class="badge badge-ok">cited</span>'
      : '<span class="badge badge-warn">retrieved</span>'}
  `;
  const rect = chip.getBoundingClientRect();
  _miniCard.style.display = 'block';
  const cardW = 280;
  const left = Math.max(8, Math.min(rect.left, window.innerWidth - cardW - 8));
  _miniCard.style.left = `${left}px`;
  _miniCard.style.top = `${rect.bottom + 6}px`;
}

function _hideMiniCard() {
  if (_miniCard) _miniCard.style.display = 'none';
}

function _onHistoryClick(e) {
  // "Save this subgraph" button
  const saveBtn = e.target.closest('.ask-save-subgraph-btn');
  if (saveBtn) {
    const entryIdx = Number(saveBtn.dataset.entry);
    const entry = _history[entryIdx];
    if (entry) {
      const nodeIds = (entry.res.grounding && Array.isArray(entry.res.grounding.node_ids))
        ? entry.res.grounding.node_ids
        : [];
      openSaveViewModal({
        question: entry.question,
        nodeIds,
      });
    }
    return;
  }

  const hit = _citationFor(e.target);
  if (!hit) return;
  _hideMiniCard();
  _openPaperDrawer(hit.citation.paper_id, hit.citation.title);
}

function _openPaperDrawer(paperId, fallbackTitle) {
  const { papers } = store.getState();
  const paper = papers.get(paperId);
  const title = paper ? paper.title : (fallbackTitle || paperId);
  const html = `
    <div class="drawer-header">
      <h2 class="drawer-title">${escapeHtml(title || 'Untitled')}</h2>
      ${paper
        ? `<div class="muted">${escapeHtml(authorsLine(paper.authors || [], paper.year))}</div>`
        : ''}
    </div>
    <div class="drawer-section">
      <div class="drawer-section-title">Paper ID</div>
      <div>${escapeHtml(paperId || '')}</div>
    </div>
    <div class="drawer-section drawer-actions">
      <button class="btn btn-secondary btn-full" id="ask-drawer-library">Open library</button>
    </div>
  `;
  drawerOpen(html);
  const btn = document.getElementById('ask-drawer-library');
  if (btn) {
    btn.addEventListener('click', () => {
      window.location.hash = '#/library';
    });
  }
}
