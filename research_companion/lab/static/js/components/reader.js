/**
 * components/reader.js — The paper Reader overlay.
 *
 * A wide, modal reading surface (distinct from the 420px drawer). Mounted ONCE
 * from main.js. It is the sole listener for CustomEvent('rc:open-reader',
 * { detail: { paperId, sectionId?, quote?, charStart?, charEnd?, title? } }) —
 * click surfaces (Task 4) only dispatch the event; all fetch logic lives here.
 *
 * On open it fetches GET /api/papers/{id}/text?q=<quote>, splits the text into
 * sections via readerHelpers, and renders a section nav + reading column with an
 * optional <mark> around the highlighted span. When the caller supplies an
 * explicit absolute [charStart, charEnd] span (e.g. a Q&A citation chip) that
 * range is highlighted directly — no ?q= locate needed.
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
  effectiveQuoteRange,
  hasReadableText,
  sectionBlocks,
  blockIntersectsRange,
} from '../readerHelpers.js';
import {
  buildViewerUrl,
  normalizeQuoteForSearch,
  readerTabs,
  findMissState,
  findDispatchParams,
} from '../readerPdfHelpers.js';

// ---------------------------------------------------------------------------
// Overlay state
// ---------------------------------------------------------------------------

let _overlay = null;
let _panel = null;
let _open = false;
let _apiRef = api;
let _lastFocus = null;

// PDF (Original) tab state — reset per _renderContent() call / on close.
// A same-origin, same-page-lifetime iframe: never recreated across tab flips.
const PDF_INIT_GRACE_MS = 500;   // time to let viewer.mjs attach PDFViewerApplication after load
const PDF_MISS_TIMEOUT_MS = 4000; // time to wait for a find result before declaring a miss
let _pdfFrame = null;
let _pdfMissTimer = null;
let _pdfFindEvents = [];
let _pdfQuoteRequested = false; // normalizeQuoteForSearch(quote) was non-empty (a search was launched)
let _pdfSearchPhrase = ''; // the normalized phrase, kept for the post-subscribe re-dispatch

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
  _clearPdfMissTimer();
  _pdfFrame = null;
  _pdfFindEvents = [];
  _pdfQuoteRequested = false;
  _pdfSearchPhrase = '';
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

// ---------------------------------------------------------------------------
// Section body — block model rendering
// ---------------------------------------------------------------------------

/**
 * Render a section's body from its typed block model (see readerHelpers'
 * sectionBlocks). Blocks whose [start,end) intersect the active quote range
 * render in RAW mode (escaped + <mark>-sliced straight off the section's raw
 * text, pre-wrap preserved) — paragraph joining/hyphen-repair/whitespace
 * collapsing is skipped for exactly those blocks so the quote-highlight span
 * is never disturbed. All other blocks render "pretty" per their kind.
 *
 * @param {string} sectionText — the section's raw (already char-sliced) text
 * @param {string} sectionTitle
 * @param {number[]|null} quoteRange — section-relative [start, end) or null
 * @returns {string} HTML
 */
function _renderSectionBlocks(sectionText, sectionTitle, quoteRange) {
  const blocks = sectionBlocks(sectionText, sectionTitle);
  return blocks.map(b => {
    if (blockIntersectsRange(b, quoteRange)) {
      const markStart = Math.max(b.start, Math.min(quoteRange[0], b.end));
      const markEnd = Math.max(b.start, Math.min(quoteRange[1], b.end));
      const before = escapeHtml(sectionText.slice(b.start, markStart));
      const marked = escapeHtml(sectionText.slice(markStart, markEnd));
      const after = escapeHtml(sectionText.slice(markEnd, b.end));
      return `<div class="reader-raw">${before}<mark class="reader-quote">${marked}</mark>${after}</div>`;
    }
    switch (b.kind) {
      case 'heading-echo':
        return '';
      case 'caption':
        return b.text ? `<p class="reader-caption">${escapeHtml(b.text)}</p>` : '';
      case 'display':
        return b.text ? `<div class="reader-display">${escapeHtml(b.text)}</div>` : '';
      case 'table':
        return b.text.trim() ? `<pre class="reader-table">${escapeHtml(b.text)}</pre>` : '';
      case 'para':
      default:
        return b.text ? `<p class="reader-para">${escapeHtml(b.text)}</p>` : '';
    }
  }).join('');
}

function _renderContent(payload, detail) {
  // Fresh PDF-tab state for this open — a previous paper's iframe/timer/events
  // must never bleed into this render.
  _clearPdfMissTimer();
  _pdfFrame = null;
  _pdfFindEvents = [];
  _pdfQuoteRequested = false;
  _pdfSearchPhrase = '';

  const model = buildReaderModel(payload);
  const rawSections = (payload && Array.isArray(payload.sections)) ? payload.sections : [];

  // Prefer the payload title, fall back to what the caller passed.
  const headerTitle = (payload && payload.title) || detail.title || model.title;
  _panel.setAttribute('aria-label', `Reading: ${headerTitle}`);

  // Effective highlight range: an explicit detail [charStart, charEnd] (the
  // Q&A citation exact-span path) wins over any quote_range the payload
  // located; degenerate detail ranges fall back to the payload range.
  const effectiveRange = effectiveQuoteRange(detail, model.quoteRange);

  // Resolve which section to highlight on the RAW (offset-bearing) sections,
  // then confirm the id survives into the model (empty sections may be dropped).
  let activeId = resolveActiveSection(rawSections, detail.sectionId, effectiveRange);
  const modelIds = model.sections.map(s => s.id);
  if (!modelIds.includes(activeId)) activeId = model.sections.length ? model.sections[0].id : null;

  // Map section id -> absolute char_start (for quote-relative slicing).
  const charStartById = {};
  for (const s of rawSections) charStartById[s.section_id] = s.char_start || 0;

  const quoteRequested = !!detail.quote;
  const quoteMissing = quoteRequested && !model.quoteRange;
  const emptyText = !hasReadableText(model);

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

  const emptyHtml = emptyText
    ? `<div class="reader-empty">No extracted text for this paper${model.hasPdf ? ' — it may be a scanned PDF. Use “View original PDF” above to read it.' : '.'}</div>`
    : '';

  // Figures/charts never make it into the extracted text — say so plainly.
  // When there's an Original (PDF) tab, point at it directly; otherwise fall
  // back to the external PDF link (kept unchanged in the header).
  const figuresNoticeHtml = (!emptyText && model.hasPdf)
    ? `<div class="reader-figures-notice">Figures and charts aren't part of the text view — switch to the Original tab to see them as typeset.</div>`
    : '';

  const sectionsHtml = emptyText ? '' : model.sections.map(s => {
    const isActive = s.id === activeId;
    const tag = s.level >= 2 ? 'h4' : 'h3';
    const rel = isActive
      ? quoteRangeWithinSection(charStartById[s.id] || 0, s.text, effectiveRange)
      : null;
    const bodyInnerHtml = _renderSectionBlocks(s.text, s.title, rel);
    const idAttr = escapeHtml(String(s.id));
    return `
      <section class="reader-section${isActive ? ' reader-section--active' : ''}"
               data-section-id="${idAttr}" id="reader-sec-${idAttr}">
        <${tag} class="reader-section-title">${escapeHtml(s.title || '')}</${tag}>
        <div class="reader-text">${bodyInnerHtml}</div>
      </section>`;
  }).join('');

  // Two-tab shell (Original PDF / Text) — only when the paper has a PDF.
  // The Text pane's own body-rendering logic above is untouched; here we only
  // decide whether it starts hidden (Original is the default active tab).
  const tabState = readerTabs(model.hasPdf);
  const hasTabs = tabState.tabs.length > 1;

  const tabsHtml = hasTabs ? `
    <div class="reader-tabs" role="tablist">
      <button type="button" class="reader-tab${tabState.active === 'original' ? ' reader-tab--active' : ''}"
              role="tab" aria-selected="${tabState.active === 'original'}" data-tab="original">Original</button>
      <button type="button" class="reader-tab${tabState.active === 'text' ? ' reader-tab--active' : ''}"
              role="tab" aria-selected="${tabState.active === 'text'}" data-tab="text">Text</button>
    </div>` : '';

  const pdfPaneHtml = hasTabs
    ? `<div class="reader-pdf-pane"${tabState.active === 'original' ? '' : ' hidden'}></div>`
    : '';

  const bodyHiddenAttr = (hasTabs && tabState.active !== 'text') ? ' hidden' : '';
  const bodyHtml = `<div class="reader-body"${bodyHiddenAttr}>${noticeHtml}${figuresNoticeHtml}${emptyHtml}${sectionsHtml}</div>`;

  _panel.innerHTML = headerHtml + tabsHtml + navHtml + pdfPaneHtml + bodyHtml;
  _bindClose();
  _bindNav();
  if (hasTabs) {
    _bindTabs(detail);
    // Activate the default tab now — this is what lazily creates the PDF
    // iframe on first activation of Original (the default when hasPdf).
    _activateTab(tabState.active, detail);
  }
  _focusClose();

  // Scroll the active section (or its mark) into view.
  _scrollToActive(activeId);
}

// ---------------------------------------------------------------------------
// Original (PDF) tab — lazy iframe, tab switching, miss/failure detection
// ---------------------------------------------------------------------------

function _bindTabs(detail) {
  _panel.querySelectorAll('.reader-tab').forEach((btn) => {
    btn.addEventListener('click', () => _activateTab(btn.dataset.tab, detail));
  });
}

function _activateTab(tabName, detail) {
  const pdfPane = _panel.querySelector('.reader-pdf-pane');
  const bodyEl = _panel.querySelector('.reader-body');
  if (!bodyEl) return;

  // Any tab switch dismisses a shown/pending miss notice.
  const notice = pdfPane && pdfPane.querySelector('.reader-pdf-notice');
  if (notice) notice.remove();

  _panel.querySelectorAll('.reader-tab').forEach((btn) => {
    const isActive = btn.dataset.tab === tabName;
    btn.classList.toggle('reader-tab--active', isActive);
    btn.setAttribute('aria-selected', String(isActive));
  });

  if (tabName === 'original' && pdfPane) {
    pdfPane.hidden = false;
    bodyEl.hidden = true;
    _ensurePdfFrame(pdfPane, detail);
  } else {
    if (pdfPane) pdfPane.hidden = true;
    bodyEl.hidden = false;
  }
}

function _clearPdfMissTimer() {
  if (_pdfMissTimer) {
    clearTimeout(_pdfMissTimer);
    _pdfMissTimer = null;
  }
}

function _ensurePdfFrame(pdfPane, detail) {
  if (_pdfFrame) return; // already created — never recreated on tab flips
  const quote = detail.quote || '';
  _pdfSearchPhrase = normalizeQuoteForSearch(quote);
  _pdfQuoteRequested = !!_pdfSearchPhrase;

  const iframe = document.createElement('iframe');
  iframe.className = 'reader-pdf-frame';
  iframe.title = 'Original PDF';
  iframe.addEventListener('error', () => _handlePdfLoadFailure(iframe));
  iframe.addEventListener('load', () => _handlePdfLoad(iframe, pdfPane));
  iframe.src = buildViewerUrl(detail.paperId, { quote });

  _pdfFrame = iframe;
  pdfPane.appendChild(iframe);
}

function _handlePdfLoad(iframe, pdfPane) {
  // Grace period for viewer.mjs to finish attaching window.PDFViewerApplication
  // after the iframe's load event fires; if it never shows up, treat the
  // viewer as failed rather than leave a blank pane.
  setTimeout(() => {
    if (_pdfFrame !== iframe) return; // stale: reader closed/reopened since
    let app = null;
    try {
      app = iframe.contentWindow && iframe.contentWindow.PDFViewerApplication;
    } catch {
      app = null;
    }
    if (!app) {
      _handlePdfLoadFailure(iframe);
      return;
    }
    if (_pdfQuoteRequested) _subscribeFindEvents(iframe, app);
  }, PDF_INIT_GRACE_MS);
}

function _subscribeFindEvents(iframe, app) {
  try {
    Promise.resolve(app.initializedPromise).then(() => {
      if (_pdfFrame !== iframe) return; // stale: reader closed/reopened since
      let eventBus = null;
      try {
        eventBus = iframe.contentWindow.PDFViewerApplication.eventBus;
      } catch {
        eventBus = null;
      }
      if (!eventBus) return;

      // updatefindmatchescount fires as pages are progressively scanned;
      // updatefindcontrolstate fires with the terminal state once the whole
      // document has been searched (FOUND=0 / NOT_FOUND=1 / WRAPPED=2 are
      // terminal for a single find-all pass; PENDING=3 means still running).
      const record = (evt, isFinal) => {
        const total = (evt && evt.matchesCount && typeof evt.matchesCount.total === 'number')
          ? evt.matchesCount.total : 0;
        _pdfFindEvents.push({ total, final: isFinal });
        _maybeShowMissNotice(false);
      };
      const onMatchesCount = (evt) => record(evt, false);
      const onControlState = (evt) => record(evt, !!evt && evt.state !== 3);

      try {
        eventBus.on('updatefindmatchescount', onMatchesCount);
        eventBus.on('updatefindcontrolstate', onControlState);
      } catch {
        return;
      }

      // The #search fragment launches the viewer's own find, which can
      // complete BEFORE these listeners attach (verified: on a local server
      // the fragment find finishes ~0.5s after documentloaded, while this
      // subscription lands after iframe load + the init grace period) — its
      // events would be lost and the timeout would declare a false miss.
      // Re-dispatching the same query forces a deterministic re-search whose
      // events always arrive after the listeners above.
      try {
        eventBus.dispatch('find', findDispatchParams(_pdfSearchPhrase));
      } catch {
        return;
      }

      _clearPdfMissTimer();
      _pdfMissTimer = setTimeout(() => _maybeShowMissNotice(true), PDF_MISS_TIMEOUT_MS);
    }).catch(() => {});
  } catch {
    // Any cross-origin/reach-in failure — miss-detection is best-effort only,
    // the viewer itself is unaffected.
  }
}

function _maybeShowMissNotice(timeoutFired) {
  if (!_pdfQuoteRequested) return;
  const state = findMissState(_pdfFindEvents, timeoutFired);
  if (state === 'pending') return;
  _clearPdfMissTimer();
  if (state === 'missed') {
    _showPdfMissNotice();
  } else {
    // A late match after the timeout: retract the now-wrong miss notice.
    const stale = _panel && _panel.querySelector('.reader-pdf-notice');
    if (stale) stale.remove();
  }
}

function _showPdfMissNotice() {
  const pdfPane = _panel.querySelector('.reader-pdf-pane');
  if (!pdfPane || pdfPane.querySelector('.reader-pdf-notice')) return;
  const notice = document.createElement('div');
  notice.className = 'reader-pdf-notice';
  notice.textContent = "Couldn't locate this quote in the PDF — the Text tab has it highlighted.";
  pdfPane.insertBefore(notice, pdfPane.firstChild);
}

function _handlePdfLoadFailure(iframe) {
  if (_pdfFrame !== iframe) return; // stale: reader closed/reopened since
  _clearPdfMissTimer();
  const textBtn = _panel.querySelector('.reader-tab[data-tab="text"]');
  if (textBtn && !textBtn.classList.contains('reader-tab--active')) textBtn.click();
  showToast('PDF viewer failed to load — showing text view', 'error');
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
