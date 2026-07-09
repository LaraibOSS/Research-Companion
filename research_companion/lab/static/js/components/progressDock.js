/**
 * components/progressDock.js — Persistent ingest progress dock.
 *
 * Fixed bottom-right, 320px, collapsible. Mounted once from main.js;
 * survives view switches.
 *
 * Pure logic (node-testable):
 *   dockModel(state) -> { visible, collapsed, bar:{done,total}, current,
 *                          items:[{status,ok,label,retryable,paperId}], summary }
 *   items are driven by state.ingestManifest (per-file folder-ingest status:
 *   queued/processing/done/failed/skipped) when it is non-empty; otherwise they
 *   fall back to the flat state.ingestLog (single-add / ingest started outside
 *   this UI). Each item's status chip is rendered via manifestItemView().
 *
 * DOM renderer: mountDock(el, store, api)
 */

import { escapeHtml } from '../format.js';
import { manifestItemView } from './ingestHelpers.js';

// ---------------------------------------------------------------------------
// Pure model (exported for node --test)
// ---------------------------------------------------------------------------

/**
 * Derive the dock view-model from reducer state.
 *
 * @param {object} state  — { jobs: Map, ingestLog?: Array, ingestManifest?: Array, activeJobs?: Map, failures?: object }
 * @returns {{ visible: boolean, collapsed: boolean,
 *             bar: {done:number, total:number},
 *             current: string,
 *             items: Array<{status:string, ok:boolean|null, label:string, retryable:boolean, paperId:string|null}>,
 *             summary: string|null,
 *             background: Array<{kind:string, label:string}> }}
 */
export function dockModel(state) {
  const job = state.jobs && state.jobs.get('ingest');
  const log = state.ingestLog || [];
  const manifest = Array.isArray(state.ingestManifest) ? state.ingestManifest : [];
  const usingManifest = manifest.length > 0;

  // Build background task lines from activeJobs, excluding ingest (avoid double-display)
  const background = [];
  if (state.activeJobs) {
    for (const [, bJob] of state.activeJobs) {
      if (bJob.kind !== 'ingest') {
        background.push({ kind: bJob.kind, label: bJob.label || '' });
      }
    }
  }

  // Never ran and no background jobs
  if (!job) {
    return {
      visible:    background.length > 0,
      collapsed:  false,
      bar:        { done: 0, total: 0 },
      current:    '',
      items:      [],
      summary:    null,
      background,
    };
  }

  const done  = job.done  ?? 0;
  const total = job.total ?? 0;

  // Build items from the per-file manifest when present (folder-ingest scan/review
  // flow); fall back to the flat ingestLog (single-add / ingest started outside this UI).
  const items = usingManifest
    ? manifest.map(row => {
        const status = row.status || 'queued';
        const failure = status === 'failed' && state.failures ? state.failures[row.path] : null;
        const paperId = (failure && failure.paper_id) || null;
        return {
          status,
          ok:        status === 'done' ? true : (status === 'failed' ? false : null),
          label:     row.relPath || row.name || row.path || '',
          retryable: status === 'failed' && !!paperId,
          paperId,
        };
      })
    : log.map(entry => ({
        status:    entry.ok ? 'done' : 'failed',
        ok:        entry.ok,
        label:     entry.label || entry.path || '',
        retryable: entry.ok ? false : !!entry.paperId,
        paperId:   entry.paperId || null,
      }));

  if (job.status === 'done') {
    let summary;
    if (usingManifest) {
      const added   = manifest.filter(r => r.status === 'done').length;
      const skipped = manifest.filter(r => r.status === 'skipped').length;
      const failed  = manifest.filter(r => r.status === 'failed').length;
      summary = `Ingest complete — ${added} added, ${skipped} skipped, ${failed} failed`;
    } else {
      const successCount = items.filter(i => i.ok).length;
      summary = `Ingest complete — ${successCount} paper${successCount !== 1 ? 's' : ''}`;
    }
    return {
      visible:    true,
      collapsed:  true,
      bar:        { done: total || done, total: total || done },
      current:    '',
      items,
      summary,
      background,
    };
  }

  return {
    visible:    total > 0 || background.length > 0,
    collapsed:  false,
    bar:        { done, total },
    current:    job.current || '',
    items,
    summary:    null,
    background,
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

    const bgHtml = model.background.map(bg => `
      <div class="dock-bg-job">
        <span class="activity-spin dock-bg-spin" aria-hidden="true"></span>
        <span class="dock-bg-label">${escapeHtml(bg.label)}</span>
      </div>
    `).join('');

    const itemsHtml = model.items.map(item => {
      const view = manifestItemView(item);
      const labelHtml = escapeHtml(item.label);

      let retryHtml = '';
      if (item.status === 'failed') {
        if (item.retryable) {
          retryHtml = `<button class="btn btn-sm dock-retry-btn" data-paper-id="${escapeHtml(item.paperId)}">[Retry]</button>`;
        } else {
          retryHtml = `<button class="btn btn-sm dock-retry-btn" disabled title="re-run lab ingest for path items">[Retry]</button>`;
        }
      }

      return `
        <div class="dock-item">
          <span class="lib-status-pill ${view.cls}">${escapeHtml(view.chipLabel)}</span>
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
          ${bgHtml ? `<div class="dock-bg-list">${bgHtml}</div>` : ''}
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

  storeRef.subscribe(['jobs', 'papers', 'activity', 'ingestManifest'], () => {
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
