/**
 * js/components/conversePanel.js — Floating companion chat (W3-F4).
 *
 * FAB: 48px accent circle, fixed bottom:20px right:20px, z-320.
 * Panel: 400px wide, slide/fade in, z-350.
 *
 * Mounted ONCE from main.js. Listens for CustomEvent('rc:discuss') to
 * set context and open panel.
 *
 * Pure helpers (node-testable): deriveContext, nextThreadState.
 */

import { escapeHtml } from '../format.js';
import { renderAnswerHtml, renderUnverifiedHtml } from '../answerHtml.js';
import { attachCiteHandlers } from './citeMiniCard.js';

// ---------------------------------------------------------------------------
// Pure: deriveContext(route, opts) — node-tested
// ---------------------------------------------------------------------------

/**
 * Derive a context descriptor from the current route + optional opts.
 *
 * @param {string} route  — e.g. '/draft', '/library', '/ask'
 * @param {{ paperId?: string|null, rcDiscussEvent?: {type:string, id?:string} }} [opts]
 * @returns {{ type: string, id: string|null }}
 */
export function deriveContext(route, opts = {}) {
  // rc:discuss event takes highest priority
  if (opts.rcDiscussEvent) {
    const { type, id } = opts.rcDiscussEvent;
    return { type: type || 'review', id: id || null };
  }
  // Library drawer open with a specific paper
  if (opts.paperId) {
    return { type: 'paper', id: opts.paperId };
  }
  // Route-based fallback
  if (route === '/draft') {
    return { type: 'alignment', id: null };
  }
  return { type: 'review', id: null };
}

// ---------------------------------------------------------------------------
// Pure: nextThreadState(state, event) — node-tested
// ---------------------------------------------------------------------------

/**
 * State machine: idle -> sending -> idle | error
 *
 * @param {'idle'|'sending'|'error'} state
 * @param {'send'|'success'|'error'|'retry'} event
 * @returns {'idle'|'sending'|'error'}
 */
export function nextThreadState(state, event) {
  switch (state) {
    case 'idle':
      if (event === 'send') return 'sending';
      return 'idle';
    case 'sending':
      if (event === 'success') return 'idle';
      if (event === 'error')   return 'error';
      return 'sending';
    case 'error':
      if (event === 'retry')   return 'sending';
      if (event === 'send')    return 'sending';
      return 'error';
    default:
      return 'idle';
  }
}

// ---------------------------------------------------------------------------
// Pure: threadKey(context) — node-tested
// ---------------------------------------------------------------------------

/**
 * Derive a stable Map key from a context descriptor.
 * @param {{ type: string, id: string|null }} ctx
 * @returns {string}
 */
export function threadKey(ctx) {
  return `${ctx.type}:${ctx.id || ''}`;
}

// ---------------------------------------------------------------------------
// Context short labels
// ---------------------------------------------------------------------------

const CONTEXT_LABELS = {
  review:      'Review',
  alignment:   'Alignment',
  suggestions: 'Suggestions',
  gaps:        'Gaps',
  paper:       'Paper',
};

function _contextLabel(ctx) {
  const base = CONTEXT_LABELS[ctx.type] || ctx.type;
  return ctx.id ? `${base}: ${ctx.id.length > 20 ? ctx.id.slice(0, 20) + '…' : ctx.id}` : base;
}

// ---------------------------------------------------------------------------
// Panel module state
// ---------------------------------------------------------------------------

let _fab        = null;   // HTMLElement
let _panel      = null;   // HTMLElement
let _open       = false;
let _newAnswerDot = false; // dot indicator when answer arrived while closed

let _context    = { type: 'review', id: null };
let _apiRef     = null;
let _cleanupHandlers = []; // cite handler cleanup fns

// Thread store: Map<key, { conversationId, messages, threadState }>
const _threads  = new Map();

// ---------------------------------------------------------------------------
// Exported mount (called once from main.js)
// ---------------------------------------------------------------------------

/**
 * Mount the FAB + panel once.
 * @param {object} apiRef  — api module (injected)
 */
export function mountConversePanel(apiRef) {
  if (_fab) return; // already mounted
  _apiRef = apiRef;

  // Create FAB
  _fab = document.createElement('button');
  _fab.id = 'converse-fab';
  _fab.className = 'converse-fab';
  _fab.setAttribute('aria-label', 'Open companion chat');
  _fab.setAttribute('title', 'Companion chat');
  _fab.innerHTML = `
    <svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24"
         fill="none" stroke="currentColor" stroke-width="2"
         stroke-linecap="round" stroke-linejoin="round">
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
    </svg>
    <span class="converse-fab-dot" id="converse-fab-dot" style="display:none"></span>
  `;
  document.body.appendChild(_fab);

  // Create panel
  _panel = document.createElement('div');
  _panel.id = 'converse-panel';
  _panel.className = 'converse-panel';
  _panel.setAttribute('role', 'complementary');
  _panel.setAttribute('aria-label', 'Companion chat panel');
  _panel.style.display = 'none';
  document.body.appendChild(_panel);

  // Wire FAB click
  _fab.addEventListener('click', _toggle);

  // Listen for rc:discuss from suggestions panel / timeline
  window.addEventListener('rc:discuss', _onRcDiscuss);

  // Listen for Escape to close
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && _open) _close();
  });

  _renderPanel();
}

// ---------------------------------------------------------------------------
// Open / close / toggle
// ---------------------------------------------------------------------------

function _toggle() {
  if (_open) _close(); else _openPanel();
}

function _openPanel() {
  if (!_panel) return;
  _open = true;
  _newAnswerDot = false;
  _updateFabDot();
  _panel.style.display = 'flex';
  // Trigger CSS transition
  requestAnimationFrame(() => {
    _panel.classList.add('converse-panel-open');
  });
  _renderPanel();
  _scrollToBottom();
}

function _close() {
  if (!_panel) return;
  _open = false;
  _panel.classList.remove('converse-panel-open');
  // Hide after transition
  const dur = 240;
  setTimeout(() => {
    if (!_open && _panel) _panel.style.display = 'none';
  }, dur);
}

function _updateFabDot() {
  const dot = document.getElementById('converse-fab-dot');
  if (dot) dot.style.display = _newAnswerDot ? 'block' : 'none';
}

// ---------------------------------------------------------------------------
// rc:discuss event handler
// ---------------------------------------------------------------------------

function _onRcDiscuss(e) {
  const { type, id } = (e && e.detail) || {};
  if (type) {
    _context = { type, id: id || null };
  }
  _openPanel();
}

// ---------------------------------------------------------------------------
// Current thread helpers
// ---------------------------------------------------------------------------

function _key() {
  return threadKey(_context);
}

function _thread() {
  const k = _key();
  if (!_threads.has(k)) {
    _threads.set(k, { conversationId: null, messages: [], threadState: 'idle' });
  }
  return _threads.get(k);
}

// ---------------------------------------------------------------------------
// Render panel
// ---------------------------------------------------------------------------

function _renderPanel() {
  if (!_panel) return;

  // Cleanup previous cite handlers
  _cleanupHandlers.forEach(fn => fn());
  _cleanupHandlers = [];

  const thread = _thread();
  const ctx = _context;
  const label = _contextLabel(ctx);
  const isDefault = ctx.type === 'review' && !ctx.id;

  const messagesHtml = thread.messages.map((msg, idx) => {
    if (msg.role === 'user') {
      return `
        <div class="converse-bubble converse-bubble-user">
          <div class="converse-bubble-text">${escapeHtml(msg.text)}</div>
        </div>`;
    }
    // companion message
    if (msg.pending) {
      return `
        <div class="converse-bubble converse-bubble-companion" id="converse-pending">
          <div class="converse-shimmer">
            <div class="converse-shimmer-line" style="width:90%"></div>
            <div class="converse-shimmer-line" style="width:72%"></div>
            <div class="converse-shimmer-line" style="width:81%"></div>
          </div>
        </div>`;
    }
    if (msg.error) {
      return `
        <div class="converse-bubble converse-bubble-companion converse-bubble-error">
          <div class="converse-error-text">${escapeHtml(msg.errorText || 'Request failed')}</div>
          <button class="btn btn-secondary btn-sm converse-retry-btn" data-idx="${idx}">Retry</button>
        </div>`;
    }
    const unverifiedHtml = msg.unverified && msg.unverified.length
      ? renderUnverifiedHtml(msg.unverified)
      : '';
    return `
      <div class="converse-bubble converse-bubble-companion" data-msg-idx="${idx}">
        <div class="converse-answer-body">${msg.html || ''}</div>
        ${unverifiedHtml}
      </div>`;
  }).join('');

  const isSending = thread.threadState === 'sending';

  _panel.innerHTML = `
    <div class="converse-header">
      <span class="converse-title">Companion</span>
      <div class="converse-context-chips">
        <span class="converse-context-chip${isDefault ? ' converse-context-chip-default' : ''}">
          ${escapeHtml(label)}
          ${!isDefault
            ? `<button class="converse-chip-clear" aria-label="Clear context">&times;</button>`
            : ''}
        </span>
      </div>
      <span class="converse-history-hint"
            title="Conversation history persists for this session only"
            aria-label="History persists on this device">&#128274;</span>
      <button class="converse-close" aria-label="Close">&times;</button>
    </div>
    <div class="converse-body" id="converse-body">
      ${messagesHtml || '<div class="converse-empty muted">Ask anything about your research.</div>'}
    </div>
    <div class="converse-footer">
      <textarea
        id="converse-input"
        class="converse-input"
        rows="1"
        placeholder="Ask a question…"
        ${isSending ? 'disabled' : ''}
        maxlength="4000"
      ></textarea>
      <button id="converse-send" class="btn btn-accent converse-send-btn" ${isSending ? 'disabled' : ''}>
        Send
      </button>
    </div>
  `;

  // Wire close button
  _panel.querySelector('.converse-close').addEventListener('click', _close);

  // Wire chip clear
  const clearBtn = _panel.querySelector('.converse-chip-clear');
  if (clearBtn) {
    clearBtn.addEventListener('click', () => {
      _context = { type: 'review', id: null };
      _renderPanel();
    });
  }

  // Wire retry buttons
  _panel.querySelectorAll('.converse-retry-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const idx = Number(btn.dataset.idx);
      _retryMessage(idx);
    });
  });

  // Wire textarea auto-grow + submit
  const input = _panel.querySelector('#converse-input');
  const sendBtn = _panel.querySelector('#converse-send');

  if (input) {
    input.addEventListener('input', () => {
      input.style.height = 'auto';
      input.style.height = Math.min(input.scrollHeight, 120) + 'px';
    });
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        _sendMessage();
      }
    });
  }

  if (sendBtn) {
    sendBtn.addEventListener('click', _sendMessage);
  }

  // Attach cite handlers to each companion message
  _panel.querySelectorAll('.converse-bubble-companion[data-msg-idx]').forEach(bubble => {
    const msgIdx = Number(bubble.dataset.msgIdx);
    const msg = thread.messages[msgIdx];
    if (!msg || !msg.citations) return;
    const cleanup = attachCiteHandlers(bubble, (n) => {
      return msg.citations.find(c => c.n === n) || null;
    });
    _cleanupHandlers.push(cleanup);
  });
}

function _scrollToBottom() {
  const body = document.getElementById('converse-body');
  if (body) body.scrollTop = body.scrollHeight;
}

// ---------------------------------------------------------------------------
// Send / retry
// ---------------------------------------------------------------------------

async function _sendMessage() {
  const input = document.getElementById('converse-input');
  if (!input) return;
  const text = (input.value || '').trim();
  if (!text) return;

  const thread = _thread();
  if (thread.threadState === 'sending') return;

  input.value = '';
  input.style.height = 'auto';

  // Push user bubble
  thread.messages.push({ role: 'user', text });
  // Push pending companion bubble
  thread.messages.push({ role: 'companion', pending: true });
  thread.threadState = nextThreadState(thread.threadState, 'send');

  _renderPanel();
  _scrollToBottom();

  await _doSend(text, thread);
}

async function _retryMessage(errorIdx) {
  const thread = _thread();
  // Find the last user message before errorIdx
  let userMsg = null;
  for (let i = errorIdx - 1; i >= 0; i--) {
    if (thread.messages[i].role === 'user') {
      userMsg = thread.messages[i];
      break;
    }
  }
  if (!userMsg) return;

  // Replace error bubble with pending
  thread.messages[errorIdx] = { role: 'companion', pending: true };
  thread.threadState = nextThreadState(thread.threadState, 'retry');

  _renderPanel();
  _scrollToBottom();

  await _doSend(userMsg.text, thread);
}

async function _doSend(text, thread) {
  const pendingIdx = thread.messages.findLastIndex
    ? thread.messages.findLastIndex(m => m.pending)
    : (() => {
        for (let i = thread.messages.length - 1; i >= 0; i--) {
          if (thread.messages[i].pending) return i;
        }
        return -1;
      })();

  try {
    const body = {
      context: { type: _context.type, id: _context.id || undefined },
      message: text,
    };
    if (thread.conversationId) {
      body.conversation_id = thread.conversationId;
    }

    const res = await _apiRef.converse(body);

    thread.conversationId = res.conversation_id;
    thread.threadState = nextThreadState(thread.threadState, 'success');

    const citations = res.citations || [];
    const html = renderAnswerHtml(res.answer, citations);

    if (pendingIdx >= 0) {
      thread.messages[pendingIdx] = {
        role: 'companion',
        text: res.answer,
        html,
        citations,
        unverified: res.unverified_quotes || [],
      };
    }

    // Dot indicator if panel is closed
    if (!_open) {
      _newAnswerDot = true;
      _updateFabDot();
    }
  } catch (err) {
    thread.threadState = nextThreadState(thread.threadState, 'error');
    if (pendingIdx >= 0) {
      thread.messages[pendingIdx] = {
        role: 'companion',
        error: true,
        errorText: err.message || 'Request failed',
      };
    }
  }

  _renderPanel();
  _scrollToBottom();
}
