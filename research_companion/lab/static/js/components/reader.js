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
import { buildNoteRecord } from '../noteRecord.js';
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
import {
  simplifiedModel,
  simplifiedDisplayState,
} from '../readerSimplifiedHelpers.js';
import { pollDecision } from '../oaLinkHelpers.js';

// Verbatim copy — see task-3 brief. Keep in sync with any product-copy review.
const SIMPLIFIED_EMPTY_COPY =
  "This paper hasn't been analyzed yet — run analysis from the Library to get the simplified view.";
const SIMPLIFIED_NOTE_COPY =
  'This is a simplified aid — it may lose nuance; check the Original tab for the real thing.';
const TAB_LABELS = { original: 'Original', simplified: 'Simplified', text: 'Text' };

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

// Simplified tab state — reset per _renderContent() call / on close, same
// discipline as the PDF state above. Cached response is keyed to the paper
// currently open in the reader (there is only ever one).
let _simplifiedData = null;       // GET /simplified response, or null until fetched
let _simplifiedFetchPromise = null; // in-flight GET /simplified promise (dedupes re-activation)
let _simplifiedShowAuto = false;  // "Show auto summary" toggle override while a rewrite exists
let _readerModelSections = [];    // buildReaderModel(payload).sections — for bullet section labels

// Per-open generation token. The PDF-tab code above guards its async
// continuations with an identity check (`_pdfFrame !== iframe`) because it
// has a natural identity object to compare; the Simplified-tab continuations
// (the no-PDF prefetch, the lazy /simplified fetch, and the Simplify-further
// job poll) have no such object, so they capture this counter instead.
// Incremented once per _open_() call (i.e. once per reader open, including
// reopening the SAME paper) — anything that captured an older value is from
// a superseded open and must bail before mutating shared state (_simplifiedData)
// or painting, no matter what the `_open` boolean happens to read at that
// moment (closing without reopening leaves the token unchanged, which is
// fine: the panel is already torn down by _close(), so there's nothing left
// to poison, and the very next _renderContent() resets _simplifiedData
// regardless).
let _readerGeneration = 0;

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
  _simplifiedData = null;
  _simplifiedFetchPromise = null;
  _simplifiedShowAuto = false;
  _readerModelSections = [];
  // Return focus to the element that opened the reader, if still around.
  if (_lastFocus && typeof _lastFocus.focus === 'function' && document.contains(_lastFocus)) {
    _lastFocus.focus();
  }
  _lastFocus = null;
}

async function _open_(detail) {
  const gen = ++_readerGeneration; // mint this open's generation token
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

  _renderContent(payload, detail, gen);
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

async function _renderContent(payload, detail, gen) {
  // Superseded by a newer open — e.g. a rapid close-then-reopen onto a
  // DIFFERENT paper while _open_'s own upstream getPaperText() fetch for
  // THIS open was still resolving: _open_'s `if (!_open) return;` guard
  // only catches a plain close (nothing reopened), not a reopen (which sets
  // _open back to true for the NEW paper) — so without this check a stale
  // _renderContent(payloadA, ...) call would still run and paint paper A's
  // content over whatever paper B has already rendered. This single check
  // protects PDF papers too: the no-PDF prefetch block below has its own
  // gen check, but PDF papers never run that block, so they had no guard
  // against this race at all before this line existed.
  if (gen !== _readerGeneration) return;

  // Fresh PDF-tab state for this open — a previous paper's iframe/timer/events
  // must never bleed into this render.
  _clearPdfMissTimer();
  _pdfFrame = null;
  _pdfFindEvents = [];
  _pdfQuoteRequested = false;
  _pdfSearchPhrase = '';

  // Fresh Simplified-tab state for this open — a previous paper's cached
  // /simplified response (and the auto/rewrite toggle) must never bleed in.
  _simplifiedData = null;
  _simplifiedFetchPromise = null;
  _simplifiedShowAuto = false;

  const model = buildReaderModel(payload);
  const rawSections = (payload && Array.isArray(payload.sections)) ? payload.sections : [];
  _readerModelSections = model.sections;

  // No-PDF papers: readerTabs' default active tab (Simplified vs. Text)
  // depends on has_extraction, which the /text payload doesn't carry. Fetch
  // /simplified up front ONLY for this case (one extra GET) and keep the
  // loading state showing until it resolves; PDF papers always default to
  // Original regardless of has_extraction, so they never need this.
  if (!model.hasPdf) {
    let prefetched = null;
    try {
      prefetched = await _apiRef.getSimplified(detail.paperId);
    } catch (err) {
      console.error('[reader] simplified prefetch failed', err);
      prefetched = null;
    }
    // Superseded by a newer open (e.g. the user closed and immediately
    // opened a different paper while this GET was in flight) — bail before
    // touching _simplifiedData or painting a panel that no longer belongs
    // to us. gen !== _readerGeneration subsumes the plain !_open check: any
    // reopen (same or different paper) mints a new token.
    if (gen !== _readerGeneration) return;
    _simplifiedData = prefetched;
  }

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
  const saveNoteBtn = `<button class="reader-save-note-btn btn btn-sm btn-secondary" type="button" title="Save a note about this paper" aria-label="Save note">Save note</button>`;
  const headerHtml = `
    <div class="reader-header">
      <span class="reader-title">${escapeHtml(headerTitle)}</span>
      <div class="reader-header-actions">
        ${saveNoteBtn}
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

  // Tab shell — three tabs (Original/Simplified/Text) for PDF papers, two
  // (Simplified/Text) otherwise. Rendered from tabState.tabs (a loop) so a
  // no-PDF paper gets its two-tab bar too, rather than the earlier interim
  // hardcoded Original+Text pair gated on model.hasPdf (commit c83ac7b).
  const tabState = readerTabs(model.hasPdf, !!(_simplifiedData && _simplifiedData.has_extraction));
  const hasTabs = tabState.tabs.length > 1;

  const tabsHtml = hasTabs ? `
    <div class="reader-tabs" role="tablist">
      ${tabState.tabs.map(t => `
      <button type="button" class="reader-tab${tabState.active === t ? ' reader-tab--active' : ''}"
              role="tab" aria-selected="${tabState.active === t}" data-tab="${t}">${escapeHtml(TAB_LABELS[t] || t)}</button>`).join('')}
    </div>` : '';

  const pdfPaneHtml = tabState.tabs.includes('original')
    ? `<div class="reader-pdf-pane"${tabState.active === 'original' ? '' : ' hidden'}></div>`
    : '';

  const simplifiedPaneHtml = tabState.tabs.includes('simplified')
    ? `<div class="reader-simplified-pane"${tabState.active === 'simplified' ? '' : ' hidden'}></div>`
    : '';

  const bodyHiddenAttr = (hasTabs && tabState.active !== 'text') ? ' hidden' : '';
  const bodyHtml = `<div class="reader-body"${bodyHiddenAttr}>${noticeHtml}${figuresNoticeHtml}${emptyHtml}${sectionsHtml}</div>`;

  _panel.innerHTML = headerHtml + tabsHtml + navHtml + pdfPaneHtml + simplifiedPaneHtml + bodyHtml;
  _bindClose();
  _bindNav();
  _bindSaveNote(detail, headerTitle);
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
// Save note (header action)
// ---------------------------------------------------------------------------

/**
 * Wire the header "Save note" button: read the current text selection
 * (guarded — window.getSelection can throw/be absent in odd embeds) and post
 * a 'reader' note. The selection only becomes the note's `quote` when the
 * Text tab is the one actually on screen (the only tab whose selection maps
 * onto extracted-text char offsets the rest of the app understands);
 * otherwise it's still captured as `sourceExcerpt` for context.
 * @param {object} detail - the rc:open-reader event detail ({ paperId, ... })
 * @param {string} headerTitle - the title shown in the reader header
 */
function _bindSaveNote(detail, headerTitle) {
  const btn = _panel.querySelector('.reader-save-note-btn');
  if (!btn) return;
  btn.addEventListener('click', async () => {
    // Reader notes carry no draft_section_id, so the server's (paper_id,
    // draft_section_id) dedupe never catches a rapid double-click here —
    // guard it client-side instead.
    if (btn.disabled) return;
    btn.disabled = true;
    let selection = '';
    try {
      const sel = window.getSelection && window.getSelection();
      selection = sel ? String(sel.toString() || '').trim() : '';
    } catch {
      selection = '';
    }
    const textTab = _panel.querySelector('.reader-tab[data-tab="text"]');
    const onTextTab = !textTab || textTab.classList.contains('reader-tab--active');
    try {
      await _apiRef.saveNote(buildNoteRecord('reader', {
        paperId: detail.paperId,
        paperTitle: headerTitle,
        sourceExcerpt: selection,
        quote: (onTextTab && selection) ? selection : '',
      }));
      showToast('Saved to Notes', 'info');
    } catch (err) {
      showToast(`Failed to save note: ${err.message}`, 'error');
    } finally {
      btn.disabled = false;
    }
  });
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
  const simplifiedPane = _panel.querySelector('.reader-simplified-pane');
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
    if (simplifiedPane) simplifiedPane.hidden = true;
    bodyEl.hidden = true;
    _ensurePdfFrame(pdfPane, detail);
  } else if (tabName === 'simplified' && simplifiedPane) {
    if (pdfPane) pdfPane.hidden = true;
    simplifiedPane.hidden = false;
    bodyEl.hidden = true;
    _ensureSimplifiedPane(simplifiedPane, detail);
  } else {
    if (pdfPane) pdfPane.hidden = true;
    if (simplifiedPane) simplifiedPane.hidden = true;
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
// Simplified tab — lazy fetch, bullet rendering, section links, Simplify further
// ---------------------------------------------------------------------------

/**
 * Ensure the Simplified pane has content, fetching GET /simplified on the
 * FIRST activation only. For no-PDF papers _simplifiedData is usually already
 * populated by _renderContent's up-front prefetch (needed for the tab
 * default), so this is a cache hit and paints immediately with no refetch.
 * @param {HTMLElement} pane
 * @param {object} detail
 */
function _ensureSimplifiedPane(pane, detail) {
  if (_simplifiedData) {
    _renderSimplifiedPane(pane, detail);
    return;
  }
  if (_simplifiedFetchPromise) return; // already in flight from a prior activation

  // Captured now (synchronously, while this IS the current open) so the
  // continuations below can tell a superseded open apart from the current
  // one after the fetch resolves — see the _readerGeneration comment.
  const gen = _readerGeneration;

  pane.innerHTML = `
    <div class="reader-loading">
      <span class="reader-spin" aria-hidden="true"></span>
      <span>Loading…</span>
    </div>`;

  _simplifiedFetchPromise = _apiRef.getSimplified(detail.paperId)
    .then((resp) => {
      // Superseded by a newer open — bail WITHOUT touching _simplifiedData
      // or _simplifiedFetchPromise: a newer generation's own render already
      // reset both, and clobbering them here could stomp its in-flight fetch.
      if (gen !== _readerGeneration) return;
      _simplifiedFetchPromise = null;
      _simplifiedData = resp;
      const freshPane = _panel.querySelector('.reader-simplified-pane');
      if (freshPane) _renderSimplifiedPane(freshPane, detail);
    })
    .catch((err) => {
      if (gen !== _readerGeneration) return;
      _simplifiedFetchPromise = null;
      console.error('[reader] simplified fetch failed', err);
      const freshPane = _panel.querySelector('.reader-simplified-pane');
      if (freshPane) {
        freshPane.innerHTML = `<div class="reader-error">Couldn't load the simplified view.</div>`;
      }
    });
}

/** Map section id (string) -> nav label ("n. Title"), from the current paper's sections. */
function _buildSectionLabelMap() {
  const map = new Map();
  sectionNav(_readerModelSections).forEach((n) => map.set(String(n.id), n.label));
  return map;
}

/**
 * Normalize a cached rewrite's groups to the same {title, bullets:[{text,
 * sectionId}]} shape simplifiedModel() produces, so one bullet renderer
 * serves both views. This is the ONE place the server's section_id key is
 * renamed to sectionId.
 */
function _normalizeRewriteGroups(groups) {
  return (Array.isArray(groups) ? groups : []).map((g) => ({
    title: (g && g.title) || '',
    bullets: ((g && Array.isArray(g.bullets)) ? g.bullets : []).map((b) => ({
      text: (b && b.text) || '',
      sectionId: (b && b.section_id) || null,
    })),
  }));
}

function _renderSimplifiedBullet(bullet, sectionLabelMap) {
  const text = escapeHtml(bullet.text || '');
  const sectionId = bullet.sectionId;
  if (!sectionId) return `<li class="simplified-bullet">${text}</li>`;

  const label = sectionLabelMap.get(String(sectionId));
  if (label === undefined) {
    // The cited section isn't in the CURRENT reader sections (e.g. it was
    // empty and got dropped by buildReaderModel) — a link here would call
    // _setActive with an id matching nothing, which clears every active
    // nav/section highlight rather than navigating anywhere. Render a
    // plain, non-clickable label with the raw id instead.
    return `<li class="simplified-bullet">${text} <span class="muted">${escapeHtml(String(sectionId))}</span></li>`;
  }
  const link = ` <a href="#" class="simplified-bullet-link" data-section-id="${escapeHtml(String(sectionId))}">${escapeHtml(label)}</a>`;
  return `<li class="simplified-bullet">${text}${link}</li>`;
}

function _renderSimplifiedGroups(groups, sectionLabelMap) {
  return groups.map((g) => `
    <div class="simplified-group">
      <h4>${escapeHtml(g.title)}</h4>
      <ul class="simplified-bullet-list">${g.bullets.map((b) => _renderSimplifiedBullet(b, sectionLabelMap)).join('')}</ul>
    </div>`).join('');
}

/**
 * Paint the Simplified pane per simplifiedDisplayState(). The "Show auto
 * summary" toggle (_simplifiedShowAuto) only ever applies on top of the
 * 'rewrite' view — it swaps which content renders without discarding the
 * cached rewrite, and a matching link switches back.
 * @param {HTMLElement} pane
 * @param {object} detail
 */
function _renderSimplifiedPane(pane, detail) {
  const resp = _simplifiedData;
  if (!pane || !resp) return;

  const rewrite = resp.rewrite;
  const displayState = simplifiedDisplayState({
    hasExtraction: !!resp.has_extraction,
    rewrite,
    providerConfigured: !!resp.provider_configured,
  });
  const sectionLabelMap = _buildSectionLabelMap();
  const showingAuto = displayState.view !== 'rewrite' || _simplifiedShowAuto;

  let bodyHtml;
  if (displayState.view === 'empty') {
    bodyHtml = `<div class="reader-empty">${escapeHtml(SIMPLIFIED_EMPTY_COPY)}</div>`;
  } else if (showingAuto) {
    const model = simplifiedModel(resp.extraction);
    const backLinkHtml = (displayState.view === 'rewrite')
      ? `<div class="simplified-note"><a href="#" class="simplified-toggle-link" data-toggle="rewrite">Back to AI-simplified summary</a></div>`
      : '';
    bodyHtml = _renderSimplifiedGroups(model.groups, sectionLabelMap)
      + `<div class="simplified-note">${escapeHtml(SIMPLIFIED_NOTE_COPY)}</div>`
      + backLinkHtml;
  } else {
    const groups = _normalizeRewriteGroups(rewrite.groups);
    // Provenance line: "AI-simplified · <model> · [Regenerate]" — each
    // segment is optional. The Regenerate button (same showButton gate as
    // the standalone one below) only appears when a provider is actually
    // configured; without it there's nothing to regenerate WITH.
    const provenanceParts = ['AI-simplified'];
    if (rewrite.model) provenanceParts.push(escapeHtml(rewrite.model));
    if (resp.provider_configured) {
      provenanceParts.push('<button type="button" class="btn btn-sm btn-simplify-further">Regenerate</button>');
    }
    // The toggle only makes sense when there's an auto extraction to show —
    // a rewrite can outlive its extraction cache (e.g. a prompt-sha bump
    // invalidates load_extraction while simplified.json still holds an
    // older rewrite); simplifiedModel(null) would just render zero groups.
    const toggleHtml = resp.has_extraction
      ? `<div class="simplified-note"><a href="#" class="simplified-toggle-link" data-toggle="auto">Show auto summary</a></div>`
      : '';
    bodyHtml = `<div class="simplified-provenance">${provenanceParts.join(' · ')}</div>`
      + _renderSimplifiedGroups(groups, sectionLabelMap)
      + `<div class="simplified-note">${escapeHtml(SIMPLIFIED_NOTE_COPY)}</div>`
      + toggleHtml;
  }

  // A standalone "Simplify further" button only when the rewrite itself
  // isn't the thing on screen (its own provenance line above already carries
  // the button, relabeled "Regenerate").
  const standaloneButtonHtml = (displayState.view !== 'rewrite' && displayState.showButton)
    ? `<div class="simplified-actions"><button type="button" class="btn btn-sm btn-simplify-further">Simplify further</button></div>`
    : '';

  pane.innerHTML = bodyHtml + standaloneButtonHtml;
  _bindSimplifiedPane(pane, detail);
}

function _bindSimplifiedPane(pane, detail) {
  const toggleLink = pane.querySelector('.simplified-toggle-link');
  if (toggleLink) {
    toggleLink.addEventListener('click', (e) => {
      e.preventDefault();
      _simplifiedShowAuto = toggleLink.dataset.toggle === 'auto';
      _renderSimplifiedPane(pane, detail);
    });
  }

  pane.querySelectorAll('.simplified-bullet-link').forEach((a) => {
    a.addEventListener('click', (e) => {
      e.preventDefault();
      _activateTab('text', detail);
      _setActive(a.dataset.sectionId);
    });
  });

  const btn = pane.querySelector('.btn-simplify-further');
  if (btn) _wireSimplifyButton(btn, detail);
}

function _wireSimplifyButton(btn, detail) {
  const originalLabel = btn.textContent;
  btn.addEventListener('click', async () => {
    if (btn.disabled) return;
    // Captured at click-time, while this button's pane is definitely the
    // current open; threaded through the whole job-watch chain below so
    // every continuation can detect a close+reopen that happened while the
    // job was running.
    const gen = _readerGeneration;
    btn.disabled = true;
    btn.textContent = 'Simplifying…';
    try {
      const res = await _apiRef.postSimplify(detail.paperId);
      if (gen !== _readerGeneration) return; // superseded before the job even started polling
      _watchSimplifyJob(res.job_id, detail, gen, () => {
        if (gen !== _readerGeneration) return; // this button may not even be on screen anymore
        btn.disabled = false;
        btn.textContent = originalLabel;
      });
    } catch (err) {
      // gen mismatch catches a supersede-by-reopen; !_open additionally
      // catches a PLAIN close (no reopen) — gen alone doesn't change in
      // that case, so without the extra check this could still restore a
      // detached button and pop a toast for a reader nobody is looking at.
      if (gen !== _readerGeneration || !_open) return;
      btn.disabled = false;
      btn.textContent = originalLabel;
      showToast(`Simplify failed: ${err.message}`, 'error');
    }
  });
}

const _SIMPLIFY_POLL_MS = 1000;

/**
 * Poll GET /api/jobs/{id} for a "Simplify further" job, exactly mirroring
 * views/library.js's _watchFindPdfJob (same pure pollDecision from
 * oaLinkHelpers.js, same two counters). On any terminal outcome, re-fetch
 * /simplified and re-render the pane so the cache and the on-screen content
 * never disagree; onGiveUp is the fallback that re-enables the CALLER's
 * button directly in case the pane itself is gone by then (e.g. the user
 * switched away from the Simplified tab, which does not tear the pane down
 * but a later close/render would).
 *
 * `gen` is the generation token captured when the job was kicked off. Every
 * branch that would mutate _simplifiedData, touch the panel, call onGiveUp,
 * or show a toast checks it first and bails on a mismatch — otherwise a job
 * for paper A that outlives a close+reopen onto paper B would (a) poison
 * B's cached /simplified response with A's content once A's job finishes,
 * and (b) pop toasts for a job the user can no longer see or care about.
 * @param {string} jobId
 * @param {object} detail
 * @param {number} gen
 * @param {() => void} [onGiveUp]
 */
function _watchSimplifyJob(jobId, detail, gen, onGiveUp) {
  let consecutiveFailures = 0;
  let elapsedPolls = 0;

  const finalRefresh = async () => {
    try {
      const resp = await _apiRef.getSimplified(detail.paperId);
      if (gen !== _readerGeneration) return; // superseded — do not poison a newer open's cache
      _simplifiedData = resp;
      _simplifiedShowAuto = false; // a just-(re)generated rewrite is what should show
      const pane = _panel.querySelector('.reader-simplified-pane');
      if (pane) _renderSimplifiedPane(pane, detail);
    } catch (err) {
      console.warn('[reader] simplified refresh after simplify failed', err);
    }
  };

  const poll = async () => {
    if (gen !== _readerGeneration) return; // superseded — stop polling, nothing left to update

    elapsedPolls += 1;
    let job = null;
    let err = null;
    try {
      job = await _apiRef.getJob(jobId);
    } catch (e) {
      err = e;
    }

    // gen mismatch catches a supersede-by-reopen; !_open additionally
    // catches a PLAIN close (no reopen) — gen alone doesn't change in that
    // case, so without the extra check a job for an already-closed reader
    // could still call onGiveUp/finalRefresh and pop the "failed" toast
    // below.
    if (gen !== _readerGeneration || !_open) return;

    if (!err) {
      consecutiveFailures = 0; // any successful poll resets the failure streak
      if (job && job.status !== 'running') {
        if (onGiveUp) onGiveUp();
        if (job.status === 'failed') {
          showToast(`Simplify failed: ${job.detail || 'unknown error'}`, 'error');
        }
        await finalRefresh();
        return;
      }
    }

    const decision = pollDecision({
      status: job ? job.status : undefined,
      error: err,
      consecutiveFailures,
      elapsedPolls,
    });

    switch (decision) {
      case 'continue':
        setTimeout(poll, _SIMPLIFY_POLL_MS);
        return;
      case 'retry-transient':
        consecutiveFailures += 1;
        setTimeout(poll, _SIMPLIFY_POLL_MS);
        return;
      case 'stop-404':
        if (onGiveUp) onGiveUp();
        await finalRefresh();
        return;
      case 'give-up':
      default:
        if (onGiveUp) onGiveUp();
        await finalRefresh();
        // A fresh check: finalRefresh() just awaited its own GET, a gap
        // during which the reader could have been closed (or superseded)
        // even though the check above still held at the time.
        if (gen === _readerGeneration && _open) {
          showToast('Simplify is taking unusually long — refresh to check its status.', 'info');
        }
        return;
    }
  };

  poll();
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
