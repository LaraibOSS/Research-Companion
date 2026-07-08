/**
 * components/reader.js — The paper Reader overlay.
 *
 * A wide, modal reading surface (distinct from the 420px drawer). Mounted ONCE
 * from main.js. It is the sole listener for CustomEvent('rc:open-reader',
 * { detail: { paperId, sectionId?, quote?, title? } }) — click surfaces (Task 4)
 * only dispatch the event; all fetch logic lives here.
 *
 * On open it fetches GET /api/papers/{id}/text?q=<quote>, splits the text into
 * sections via readerHelpers, and renders a section nav + reading column with an
 * optional <mark> around the located quote.
 */

import * as store from '../store.js';
import * as api from '../api.js';
import { showToast } from './toast.js';
import { escapeHtml } from '../format.js';
import {
  buildReaderModel,
  sectionNav,
  resolveActiveSection,
  quoteRangeWithinSection,
} from '../readerHelpers.js';

// ---------------------------------------------------------------------------
// Overlay state
// ---------------------------------------------------------------------------

let _overlay = null;
let _panel = null;
let _open = false;
let _apiRef = api;
let _lastFocus = null;

// ---------------------------------------------------------------------------
// Exported mount
// ---------------------------------------------------------------------------

/**
 * Mount the reader overlay once into document.body.
 * @param {object} storeRef — store module (injected for parity/testability)
 * @param {object} apiRef   — api module (injected for testability)
 */
export function mountReader(storeRef = store, apiRef = api) {
  if (_overlay) return;

  _apiRef = apiRef;

  _overlay = document.createElement('div');
  _overlay.className = 'reader-overlay';
  _overlay.id = 'reader-overlay';
  _overlay.setAttribute('aria-hidden', 'true');

  _panel = document.createElement('div');
  _panel.className = 'reader-panel';
  _panel.setAttribute('role', 'dialog');
  _panel.setAttribute('aria-modal', 'true');
  _panel.setAttribute('aria-label', 'Paper reader');

  _overlay.appendChild(_panel);
  document.body.appendChild(_overlay);

  // Backdrop click (outside the panel) closes.
  _overlay.addEventListener('mousedown', (e) => {
    if (e.target === _overlay) _close();
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && _open) _close();
  });

  window.addEventListener('rc:open-reader', (e) => {
    const detail = (e && e.detail) || {};
    if (!detail.paperId) return; // guard: ignore events without a paper
    _open_(detail);
  });
}

// ---------------------------------------------------------------------------
// Open / close
// ---------------------------------------------------------------------------

function _show() {
  _open = true;
  _lastFocus = document.activeElement;
  _overlay.classList.add('open');
  _overlay.setAttribute('aria-hidden', 'false');
  document.body.style.overflow = 'hidden';
}

function _close() {
  if (!_open) return;
  _open = false;
  _overlay.classList.remove('open');
  _overlay.setAttribute('aria-hidden', 'true');
  document.body.style.overflow = '';
  _panel.innerHTML = '';
  // Return focus to the element that opened the reader, if still around.
  if (_lastFocus && typeof _lastFocus.focus === 'function' && document.contains(_lastFocus)) {
    _lastFocus.focus();
  }
  _lastFocus = null;
}

async function _open_(detail) {
  _show();
  _renderLoading();

  let payload;
  try {
    payload = await _apiRef.getPaperText(detail.paperId, detail.quote);
  } catch (err) {
    if (err && err.status === 404) {
      _renderError('This paper has no readable text yet.');
    } else {
      _renderError("Couldn't load this paper.");
      showToast("Couldn't load this paper", 'error');
      console.error('[reader] fetch error', err);
    }
    return;
  }

  // A late close (Escape during the fetch) — do not clobber it.
  if (!_open) return;

  _renderContent(payload, detail);
}

// ---------------------------------------------------------------------------
// Render — loading / error / content
// ---------------------------------------------------------------------------

function _prefersReducedMotion() {
  return typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

function _closeButtonHtml() {
  return `<button class="reader-close" aria-label="Close reader">&times;</button>`;
}

function _renderLoading() {
  _panel.innerHTML = `
    <div class="reader-header">
      <span class="reader-title">Loading…</span>
      <div class="reader-header-actions">${_closeButtonHtml()}</div>
    </div>
    <div class="reader-loading">
      <span class="reader-spin" aria-hidden="true"></span>
      <span>Loading…</span>
    </div>`;
  _bindClose();
  _focusClose();
}

function _renderError(message) {
  _panel.innerHTML = `
    <div class="reader-header">
      <span class="reader-title">Reader</span>
      <div class="reader-header-actions">${_closeButtonHtml()}</div>
    </div>
    <div class="reader-error">${escapeHtml(message)}</div>`;
  _bindClose();
  _focusClose();
}

function _renderContent(payload, detail) {
  const model = buildReaderModel(payload);
  const rawSections = (payload && Array.isArray(payload.sections)) ? payload.sections : [];

  // Prefer the payload title, fall back to what the caller passed.
  const headerTitle = (payload && payload.title) || detail.title || model.title;
  _panel.setAttribute('aria-label', `Reading: ${headerTitle}`);

  // Resolve which section to highlight on the RAW (offset-bearing) sections,
  // then confirm the id survives into the model (empty sections may be dropped).
  let activeId = resolveActiveSection(rawSections, detail.sectionId, model.quoteRange);
  const modelIds = model.sections.map(s => s.id);
  if (!modelIds.includes(activeId)) activeId = model.sections.length ? model.sections[0].id : null;

  // Map section id -> absolute char_start (for quote-relative slicing).
  const charStartById = {};
  for (const s of rawSections) charStartById[s.section_id] = s.char_start || 0;

  const quoteRequested = !!detail.quote;
  const quoteMissing = quoteRequested && !model.quoteRange;

  // Header
  const pdfLink = model.hasPdf
    ? `<a class="reader-pdf-link" href="${escapeHtml(_apiRef.paperPdfUrl(detail.paperId))}" target="_blank" rel="noopener">View original PDF ↗</a>`
    : '';
  const headerHtml = `
    <div class="reader-header">
      <span class="reader-title">${escapeHtml(headerTitle)}</span>
      <div class="reader-header-actions">
        ${pdfLink}
        ${_closeButtonHtml()}
      </div>
    </div>`;

  // Nav
  const navRows = sectionNav(model.sections).map(n => `
    <button class="reader-nav-row reader-nav-level-${n.level >= 2 ? 2 : 1}${n.id === activeId ? ' active' : ''}"
            data-section-id="${escapeHtml(String(n.id))}">
      ${escapeHtml(n.label)}
    </button>`).join('');
  const navHtml = `<nav class="reader-nav" aria-label="Sections">${navRows}</nav>`;

  // Body
  const noticeHtml = quoteMissing
    ? `<div class="reader-notice">Couldn't locate the exact quote in this paper — showing the paper.</div>`
    : '';

  const sectionsHtml = model.sections.map(s => {
    const isActive = s.id === activeId;
    const tag = s.level >= 2 ? 'h4' : 'h3';
    let textHtml;
    const rel = isActive
      ? quoteRangeWithinSection(charStartById[s.id] || 0, s.text, model.quoteRange)
      : null;
    if (rel) {
      const before = escapeHtml(s.text.slice(0, rel[0]));
      const marked = escapeHtml(s.text.slice(rel[0], rel[1]));
      const after = escapeHtml(s.text.slice(rel[1]));
      textHtml = `${before}<mark class="reader-quote">${marked}</mark>${after}`;
    } else {
      textHtml = escapeHtml(s.text);
    }
    const idAttr = escapeHtml(String(s.id));
    return `
      <section class="reader-section${isActive ? ' reader-section--active' : ''}"
               data-section-id="${idAttr}" id="reader-sec-${idAttr}">
        <${tag} class="reader-section-title">${escapeHtml(s.title || '')}</${tag}>
        <div class="reader-text">${textHtml}</div>
      </section>`;
  }).join('');

  const bodyHtml = `<div class="reader-body">${noticeHtml}${sectionsHtml}</div>`;

  _panel.innerHTML = headerHtml + navHtml + bodyHtml;
  _bindClose();
  _bindNav();
  _focusClose();

  // Scroll the active section (or its mark) into view.
  _scrollToActive(activeId);
}

// ---------------------------------------------------------------------------
// Highlight / scroll
// ---------------------------------------------------------------------------

function _scrollToActive(activeId) {
  if (!activeId) return;
  const sec = _panel.querySelector(`#reader-sec-${CSS && CSS.escape ? CSS.escape(String(activeId)) : String(activeId)}`);
  if (!sec) return;
  const target = sec.querySelector('.reader-quote') || sec;
  const behavior = _prefersReducedMotion() ? 'auto' : 'smooth';
  try {
    target.scrollIntoView({ behavior, block: 'start' });
  } catch {
    target.scrollIntoView();
  }
}

function _setActive(id) {
  _panel.querySelectorAll('.reader-section').forEach(sec => {
    sec.classList.toggle('reader-section--active', sec.dataset.sectionId === id);
  });
  _panel.querySelectorAll('.reader-nav-row').forEach(row => {
    row.classList.toggle('active', row.dataset.sectionId === id);
  });
  _scrollToActive(id);
}

// ---------------------------------------------------------------------------
// Event binding
// ---------------------------------------------------------------------------

function _bindClose() {
  _panel.querySelector('.reader-close')?.addEventListener('click', _close);
}

function _bindNav() {
  _panel.querySelectorAll('.reader-nav-row').forEach(row => {
    row.addEventListener('click', () => _setActive(row.dataset.sectionId));
  });
}

function _focusClose() {
  _panel.querySelector('.reader-close')?.focus();
}
