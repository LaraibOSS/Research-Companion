/**
 * views/ask.js — Ask view (F4).
 *
 * Centered column: question textarea + scope select + Ask button.
 * Answers rendered as markdown-lite via the pure renderAnswerHtml()
 * (node-tested; escapeHtml FIRST — LLM output never reaches innerHTML raw).
 * Citation chips: hover -> mini-card, click -> library drawer (via citeMiniCard).
 * Session history kept in-memory only (cleared on reload).
 */

import * as api from '../api.js';
import * as store from '../store.js';
import { escapeHtml } from '../format.js';
import { showToast } from '../components/toast.js';
import { openSaveViewModal } from '../components/saveViewModal.js';
import { canSave } from '../viewsHelpers.js';
import { attachCiteHandlers } from '../components/citeMiniCard.js';
import { explainerBanner } from '../components/explainer.js';
import { tip } from '../glossary.js';

// ---------------------------------------------------------------------------
// Pure: renderAnswerHtml (exported for node --test)
// Extracted to js/answerHtml.js; re-exported here so existing imports still work.
// ---------------------------------------------------------------------------

// NOTE: a bare re-export does NOT create a local binding in ESM — the local
// import below is required for _renderHistory()'s own use of the function.
import { renderAnswerHtml } from '../answerHtml.js';

export { renderAnswerHtml };

// ---------------------------------------------------------------------------
// View state (module-level; history is session-only, cleared on reload)
// ---------------------------------------------------------------------------

let _el = null;
let _pending = false;
let _history = [];       // [{ question, scopeLabel, res }] newest first
let _citeCleanup = null; // cleanup fn from attachCiteHandlers

// ---------------------------------------------------------------------------
// Mount / Unmount
// ---------------------------------------------------------------------------

export function mount(el) {
  _el = el;
  _render();
  _loadSections();
}

export function unmount() {
  if (_citeCleanup) { _citeCleanup(); _citeCleanup = null; }
  _el = null;
}

// ---------------------------------------------------------------------------
// Render skeleton of the view
// ---------------------------------------------------------------------------

function _render() {
  if (!_el) return;

  // Explainer banner (dismissable, persisted)
  const banner = explainerBanner(
    'ask',
    'Answers are grounded: every claim cites a section you ingested.',
  );

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

  if (banner) _el.insertBefore(banner, _el.firstChild);

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

  // "Save this subgraph" button click (delegated — citeMiniCard handles cite clicks)
  const hist = _el.querySelector('#ask-history');
  hist.addEventListener('click', _onSaveSubgraphClick);

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

  // Tear down previous cite handlers before rebuilding HTML
  if (_citeCleanup) { _citeCleanup(); _citeCleanup = null; }

  if (_history.length === 0) {
    hist.innerHTML = `
      <div class="ask-empty-state muted">
        <span class="ask-empty-icon">&#x1F4AC;</span>
        Answers appear here &mdash; try asking about the papers you ingested.
      </div>
    `;
    return;
  }

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
    const hasSaveable = canSave(res.grounding);
    const groundingHtml = nSources > 0 ? `
      <div class="ask-grounding muted"${tip('grounded')}>
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

  // Wire citation chip hover/click via shared citeMiniCard component
  _citeCleanup = attachCiteHandlers(hist, (n) => {
    // Find the citation across all history entries
    for (const entry of _history) {
      const found = (entry.res.citations || []).find(c => c.n === n);
      if (found) return found;
    }
    return null;
  });
}

// ---------------------------------------------------------------------------
// "Save this subgraph" button click handler (cite clicks handled by citeMiniCard)
// ---------------------------------------------------------------------------

function _onSaveSubgraphClick(e) {
  const saveBtn = e.target.closest('.ask-save-subgraph-btn');
  if (!saveBtn) return;
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
}
