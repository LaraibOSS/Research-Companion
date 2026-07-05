/**
 * views/compare.js — Compare view (F4).
 *
 * Header: two paper selector inputs (datalist typeahead over store.papers),
 * swap button, Compare button. Prefill from #/compare?a=<id>&b=<id>;
 * hash kept in sync on compare (via history.replaceState so the router
 * does not re-mount the view).
 *
 * Result: summary card, three overlap columns (only A / shared / only B)
 * with kind color dots from mapping.js KIND_COLORS, results table with
 * better-value bolding (pure betterValue), footer link to the library.
 */

import * as api from '../api.js';
import * as store from '../store.js';
import { escapeHtml } from '../format.js';
import { showToast } from '../components/toast.js';
import { KIND_COLORS } from '../graph/mapping.js';

// ---------------------------------------------------------------------------
// Pure: resolvePaperInput (exported for node --test)
// ---------------------------------------------------------------------------

/**
 * Resolve a selector input value to a paper_id.
 * Matches by exact paper_id first, then by unique (case-insensitive) title
 * prefix; an exact full-title match wins over an ambiguous prefix.
 * Returns null when empty, unmatched, or ambiguous.
 *
 * @param {string|null} value
 * @param {Array<{paper_id:string, title?:string}>} papers
 * @returns {string|null}
 */
export function resolvePaperInput(value, papers) {
  const v = (value == null ? '' : String(value)).trim();
  if (!v) return null;
  const list = Array.isArray(papers) ? papers : [...papers.values()];

  const byId = list.find(p => p.paper_id === v);
  if (byId) return byId.paper_id;

  const lower = v.toLowerCase();
  const prefix = list.filter(p => (p.title || '').toLowerCase().startsWith(lower));
  if (prefix.length === 1) return prefix[0].paper_id;
  if (prefix.length > 1) {
    const exact = prefix.filter(p => (p.title || '').toLowerCase() === lower);
    if (exact.length === 1) return exact[0].paper_id;
  }
  return null;
}

// ---------------------------------------------------------------------------
// Pure: betterValue (exported for node --test)
// ---------------------------------------------------------------------------

/**
 * Parse the leading float of a metric value string ("85.2±0.3" -> 85.2).
 * @returns {number|null}
 */
function _leadingFloat(v) {
  if (typeof v === 'number') return Number.isFinite(v) ? v : null;
  if (typeof v !== 'string') return null;
  const m = v.trim().match(/^[-+]?(\d+(\.\d+)?|\.\d+)/);
  return m ? parseFloat(m[0]) : null;
}

/**
 * Decide which of two metric values is better (higher wins).
 * Values are parsed as leading floats ("85.2±0.3" -> 85.2).
 * Returns 'a' | 'b' | null (null when either is unparseable, or equal).
 *
 * @param {string|number|null} a
 * @param {string|number|null} b
 * @returns {'a'|'b'|null}
 */
export function betterValue(a, b) {
  const pa = _leadingFloat(a);
  const pb = _leadingFloat(b);
  if (pa == null || pb == null || pa === pb) return null;
  return pa > pb ? 'a' : 'b';
}

// ---------------------------------------------------------------------------
// View state
// ---------------------------------------------------------------------------

let _el = null;
let _pending = false;

const KIND_ORDER = [
  ['concepts', 'concept'],
  ['methods',  'method'],
  ['datasets', 'dataset'],
];

// ---------------------------------------------------------------------------
// Mount / Unmount
// ---------------------------------------------------------------------------

export function mount(el) {
  _el = el;
  _render();
}

export function unmount() {
  _el = null;
  _pending = false;
}

// ---------------------------------------------------------------------------
// Render
// ---------------------------------------------------------------------------

function _hashParams() {
  const hash = window.location.hash || '';
  const qIdx = hash.indexOf('?');
  const params = {};
  if (qIdx >= 0) {
    for (const pair of hash.slice(qIdx + 1).split('&')) {
      const [k, v] = pair.split('=');
      if (k) params[decodeURIComponent(k)] = decodeURIComponent(v || '');
    }
  }
  return params;
}

function _render() {
  if (!_el) return;
  const { papers } = store.getState();
  const paperList = [...papers.values()];

  const optionsHtml = paperList.map(p =>
    `<option value="${escapeHtml(p.paper_id)}" label="${escapeHtml(p.title || p.paper_id)}"></option>`
  ).join('');

  const params = _hashParams();

  _el.innerHTML = `
    <div class="compare-view">
      <div class="compare-header">
        <input id="cmp-a" class="add-input compare-input" type="text" list="cmp-papers-list"
               placeholder="Paper A — id or title..." autocomplete="off">
        <button id="cmp-swap" class="btn btn-secondary" title="Swap">&#8644;</button>
        <input id="cmp-b" class="add-input compare-input" type="text" list="cmp-papers-list"
               placeholder="Paper B — id or title..." autocomplete="off">
        <button id="cmp-btn" class="btn btn-accent">Compare</button>
        <datalist id="cmp-papers-list">${optionsHtml}</datalist>
      </div>
      <div id="cmp-error" class="compare-error" style="display:none"></div>
      <div id="cmp-result" class="compare-result"></div>
    </div>
  `;

  const inputA = _el.querySelector('#cmp-a');
  const inputB = _el.querySelector('#cmp-b');

  // Prefill from #/compare?a=<id>&b=<id>
  if (params.a) inputA.value = params.a;
  if (params.b) inputB.value = params.b;

  _el.querySelector('#cmp-swap').addEventListener('click', () => {
    const tmp = inputA.value;
    inputA.value = inputB.value;
    inputB.value = tmp;
  });

  _el.querySelector('#cmp-btn').addEventListener('click', _runCompare);
  for (const input of [inputA, inputB]) {
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') _runCompare();
    });
  }

  if (paperList.length === 0) {
    _el.querySelector('#cmp-result').innerHTML = `
      <div class="compare-hint muted">Add at least two papers to the library to compare them.</div>
    `;
  }
}

// ---------------------------------------------------------------------------
// Compare
// ---------------------------------------------------------------------------

async function _runCompare() {
  if (!_el || _pending) return;

  const { papers } = store.getState();
  const paperList = [...papers.values()];
  const rawA = _el.querySelector('#cmp-a').value;
  const rawB = _el.querySelector('#cmp-b').value;

  const idA = resolvePaperInput(rawA, paperList);
  const idB = resolvePaperInput(rawB, paperList);

  if (!idA || !idB) {
    const missing = [];
    if (!idA) missing.push('A');
    if (!idB) missing.push('B');
    _setError(`Could not resolve paper ${missing.join(' and ')} — pick from the list or enter an exact id.`);
    return;
  }

  _setError(null);
  _setPending(true);
  try {
    const res = await api.compare(idA, idB);
    // Keep the hash in sync without re-triggering the router
    history.replaceState(null, '',
      `#/compare?a=${encodeURIComponent(idA)}&b=${encodeURIComponent(idB)}`);
    _renderResult(res);
  } catch (err) {
    _setError(err.message);
    showToast(`Compare failed: ${err.message}`, 'error');
  } finally {
    _setPending(false);
  }
}

function _setPending(on) {
  _pending = on;
  if (!_el) return;
  const btn = _el.querySelector('#cmp-btn');
  if (btn) {
    btn.disabled = on;
    btn.textContent = on ? 'Comparing...' : 'Compare';
  }
}

function _setError(msg) {
  if (!_el) return;
  const errEl = _el.querySelector('#cmp-error');
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
// Result rendering
// ---------------------------------------------------------------------------

function _shortTitle(paperRef) {
  const t = (paperRef && (paperRef.title || paperRef.paper_id)) || '';
  return t.length > 28 ? t.slice(0, 28) + '…' : t;
}

function _columnHtml(header, groups) {
  let total = 0;
  const sections = KIND_ORDER.map(([key, kind]) => {
    const items = (groups && groups[key]) || [];
    total += items.length;
    if (items.length === 0) return '';
    const color = KIND_COLORS[kind] || '#8b949e';
    return items.map(item => `
      <span class="compare-chip">
        <span class="compare-dot" style="background:${escapeHtml(color)}"></span>
        ${escapeHtml(String(item))}
      </span>
    `).join('');
  }).join('');

  return `
    <div class="compare-col">
      <div class="compare-col-header">${escapeHtml(header)} <span class="muted">(${total})</span></div>
      <div class="compare-col-body">
        ${total === 0 ? '<span class="muted">none</span>' : sections}
      </div>
    </div>
  `;
}

function _renderResult(res) {
  if (!_el) return;
  const resultEl = _el.querySelector('#cmp-result');
  if (!resultEl) return;

  const shortA = _shortTitle(res.paper_a);
  const shortB = _shortTitle(res.paper_b);

  // (1) Summary card
  const summaryHtml = res.summary
    ? `<div class="compare-summary">${escapeHtml(res.summary)}</div>`
    : `<div class="compare-summary compare-summary-empty muted">no narrative summary</div>`;

  // (2) Three overlap columns
  const columnsHtml = `
    <div class="compare-columns">
      ${_columnHtml(`Only in ${shortA}`, res.only_a)}
      ${_columnHtml('Shared', res.shared)}
      ${_columnHtml(`Only in ${shortB}`, res.only_b)}
    </div>
  `;

  // (3) Results table
  const rows = res.results || [];
  const tableHtml = rows.length === 0
    ? '<div class="muted compare-no-results">No comparable results reported.</div>'
    : `
      <table class="compare-table">
        <thead>
          <tr>
            <th>Metric</th>
            <th>Dataset</th>
            <th>${escapeHtml(shortA)}</th>
            <th>${escapeHtml(shortB)}</th>
          </tr>
        </thead>
        <tbody>
          ${rows.map(r => {
            const better = betterValue(r.value_a, r.value_b);
            const cell = (v, tag) => {
              const text = v == null || v === '' ? '&mdash;' : escapeHtml(String(v));
              return better === tag ? `<strong>${text}</strong>` : text;
            };
            return `
              <tr>
                <td>${escapeHtml(r.metric || '')}</td>
                <td>${escapeHtml(r.dataset || '')}</td>
                <td class="compare-value">${cell(r.value_a, 'a')}</td>
                <td class="compare-value">${cell(r.value_b, 'b')}</td>
              </tr>
            `;
          }).join('')}
        </tbody>
      </table>
    `;

  // (4) Footer
  const footerHtml = `
    <div class="compare-footer">
      <a href="#/library" class="compare-library-link">Open both in library &rarr;</a>
    </div>
  `;

  resultEl.innerHTML = summaryHtml + columnsHtml + tableHtml + footerHtml;
}
