/**
 * components/progressDock.js — Persistent ingest progress dock.
 *
 * Fixed bottom-right, 320px, collapsible. Mounted once from main.js;
 * survives view switches.
 *
 * Pure logic (node-testable):
 *   dockModel(state) -> { visible, collapsed, bar:{done,total}, current,
 *                          items:[{ok,label,retryable,paperId}], summary }
 *
 * DOM renderer: mountDock(el, store, api)
 */

import { escapeHtml } from '../format.js';

// ---------------------------------------------------------------------------
// Pure model (exported for node --test)
// ---------------------------------------------------------------------------

/**
 * Derive the dock view-model from reducer state.
 *
 * @param {object} state  — { jobs: Map, ingestLog?: Array }
 * @returns {{ visible: boolean, collapsed: boolean,
 *             bar: {done:number, total:number},
 *             current: string,
 *             items: Array<{ok:boolean, label:string, retryable:boolean, paperId:string|null}>,
 *             summary: string|null }}
 */
export function dockModel(state) {
  const job = state.jobs && state.jobs.get('ingest');
  const log  = state.ingestLog || [];

  // Never ran
  if (!job) {
    return { visible: false, collapsed: false, bar: { done: 0, total: 0 }, current: '', items: [], summary: null };
  }

  const done  = job.done  ?? 0;
  const total = job.total ?? 0;

  // Build items from ingestLog
  const items = log.map(entry => ({
    ok:        entry.ok,
    label:     entry.label || entry.path || '',
    retryable: entry.ok ? false : !!entry.paperId,
    paperId:   entry.paperId || null,
  }));

  if (job.status === 'done') {
    const successCount = items.filter(i => i.ok).length;
    return {
      visible:   true,
      collapsed: true,
      bar:       { done: total || done, total: total || done },
      current:   '',
      items,
      summary:   `Ingest complete — ${successCount} paper${successCount !== 1 ? 's' : ''}`,
    };
  }

  return {
    visible:   total > 0,
    collapsed: false,
    bar:       { done, total },
    current:   job.current || '',
    items,
    summary:   null,
  };
}

// ---------------------------------------------------------------------------
// DOM renderer
// ---------------------------------------------------------------------------

let _dockEl = null;
let _collapsed = false;
let _dismissed = false;
let _mounted = false;

/**
 * Mount the progress dock once at boot.
 * @param {HTMLElement} el        — #dock container from index.html
 * @param {object}      storeRef  — store module reference
 * @param {object}      apiRef    — api module reference (for retryPaper)
 */
export function mountDock(el, storeRef, apiRef) {
  if (_mounted) return;
  _mounted = true;
  _dockEl = el;

  function render() {
    if (!_dockEl) return;
    const state = storeRef.getState();
    const model = dockModel(state);

    if (!model.visible || _dismissed) {
      _dockEl.innerHTML = '';
      _dockEl.style.display = 'none';
      return;
    }

    _dockEl.style.display = '';

    if (model.collapsed && model.summary) {
      // Pill mode
      _dockEl.innerHTML = `
        <div class="dock-pill" id="dock-pill">
          <span>&#10003; ${escapeHtml(model.summary)}</span>
          <button class="dock-dismiss" title="Dismiss">&#10005;</button>
        </div>
      `;
      _dockEl.querySelector('.dock-dismiss').addEventListener('click', () => {
        _dismissed = true;
        render();
      });
      return;
    }

    const pct = model.bar.total > 0
      ? Math.round((model.bar.done / model.bar.total) * 100)
      : 0;

    const itemsHtml = model.items.map(item => {
      const icon = item.ok ? '&#10003;' : '&#10007;';
      const cls  = item.ok ? 'dock-item-ok' : 'dock-item-fail';
      const labelHtml = escapeHtml(item.label);

      let retryHtml = '';
      if (!item.ok) {
        if (item.retryable) {
          retryHtml = `<button class="btn btn-sm dock-retry-btn" data-paper-id="${escapeHtml(item.paperId)}">[Retry]</button>`;
        } else {
          retryHtml = `<button class="btn btn-sm dock-retry-btn" disabled title="re-run lab ingest for path items">[Retry]</button>`;
        }
      }

      return `
        <div class="dock-item ${cls}">
          <span class="dock-item-icon">${icon}</span>
          <span class="dock-item-label" title="${escapeHtml(item.label)}">${labelHtml}</span>
          ${retryHtml}
        </div>
      `;
    }).join('');

    _dockEl.innerHTML = `
      <div class="dock-panel${_collapsed ? ' dock-collapsed' : ''}">
        <div class="dock-header" id="dock-header">
          <span class="dock-header-title">Ingest progress</span>
          <span class="dock-header-count">${model.bar.done}/${model.bar.total}</span>
          <button class="dock-toggle" title="${_collapsed ? 'Expand' : 'Collapse'}">${_collapsed ? '&#9650;' : '&#9660;'}</button>
        </div>
        <div class="dock-body${_collapsed ? ' dock-body-hidden' : ''}">
          <div class="dock-bar-bg">
            <div class="dock-bar-fg" style="width:${pct}%"></div>
          </div>
          ${model.current ? `<div class="dock-current muted">${escapeHtml(model.current)}</div>` : ''}
          <div class="dock-items-list">${itemsHtml}</div>
        </div>
      </div>
    `;

    _dockEl.querySelector('#dock-header').addEventListener('click', () => {
      _collapsed = !_collapsed;
      render();
    });

    _dockEl.querySelectorAll('.dock-retry-btn:not([disabled])').forEach(btn => {
      btn.addEventListener('click', async (e) => {
        e.stopPropagation();
        const pid = btn.dataset.paperId;
        try {
          await apiRef.retryPaper(pid);
          showToastFallback('Retry queued', 'info');
        } catch (err) {
          showToastFallback(`Retry failed: ${err.message}`, 'error');
        }
      });
    });
  }

  // Track previous job status to detect real transitions
  let _prevJobStatus = null;

  storeRef.subscribe(['jobs', 'papers'], () => {
    const state = storeRef.getState();
    const job = state.jobs && state.jobs.get('ingest');
    const currentStatus = job ? job.status : null;

    if (currentStatus !== _prevJobStatus) {
      // New run starting (transition from done/null to running) -> reset dismissed
      if (currentStatus === 'running' && _prevJobStatus !== 'running') {
        _collapsed = false;
        _dismissed = false;
      }
      // Transition into done -> reset internal collapsed flag (pill mode takes over)
      if (currentStatus === 'done' && _prevJobStatus !== 'done') {
        _collapsed = false;
        _dismissed = false;
      }
      _prevJobStatus = currentStatus;
    }

    render();
  });

  render();
}

function showToastFallback(msg, type) {
  // Use dynamic import to avoid top-level circular reference issues
  import('./toast.js').then(({ showToast }) => showToast(msg, type)).catch(() => {});
}
