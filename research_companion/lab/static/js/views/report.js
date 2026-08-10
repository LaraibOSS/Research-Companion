/**
 * views/report.js — Deep-Research Report tab (Phase 2, slice 2e-1).
 * Route: /report
 *
 * A topic input + "Generate report" button drives POST /api/report/refresh
 * (a guarded 202 background job -- MUTATING, wrapped in ensureActiveResearch
 * like Brainstorm's "Draft this direction"): the server runs
 * generate_questions -> per-question qa.answer -> build_report, reporting
 * progress ("Answering i/N") via the job's `detail`, which this view polls
 * with the shared pollDecision helper (oaLinkHelpers.js, the same one
 * library.js uses for find-pdf jobs). The report_updated SSE event (->
 * the 'report' topic) also triggers a refetch, so a report generated from
 * another tab/session still shows up here. Renders the topic, then each
 * section as a question heading + answer + citation chips that open the
 * cited paper/section in the reader -- structured JSON into escaped-HTML
 * DOM, like every other view (no markdown parsing).
 */

import * as store from '../store.js';
import * as api from '../api.js';
import { escapeHtml } from '../format.js';
import { showToast } from '../components/toast.js';
import { ensureActiveResearch } from '../researchGuard.js';
import { pollDecision } from '../oaLinkHelpers.js';
import { reportSectionModel } from '../reportHelpers.js';

// ---------------------------------------------------------------------------
// Module state
// ---------------------------------------------------------------------------

let _el = null;
let _unsubs = [];
let _report = null;      // last fetched GET /api/report payload
let _generating = false;
let _jobDetail = '';
let _error = null;

const _POLL_MS = 800;

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

export function mount(el) {
  _el = el;
  _generating = false;
  _jobDetail = '';
  _error = null;

  el.innerHTML = `<div class="report-view"><div class="report-loading muted">Loading report…</div></div>`;

  _unsubs.push(store.subscribe(['report'], async () => {
    try {
      _report = await api.getReport();
    } catch (err) {
      console.warn('[report] refetch failed:', err);
    }
    _render();
  }));

  _fetch();
}

export function unmount() {
  for (const u of _unsubs) u();
  _unsubs = [];
  _el = null;
}

// ---------------------------------------------------------------------------
// Data fetching
// ---------------------------------------------------------------------------

async function _fetch() {
  try {
    _report = await api.getReport();
  } catch (err) {
    console.warn('[report] fetch failed:', err);
  }
  _render();
}

// ---------------------------------------------------------------------------
// Generate + poll
// ---------------------------------------------------------------------------

function _currentTopic() {
  const input = _el && _el.querySelector('#report-topic-input');
  return input ? input.value.trim() : '';
}

async function _generate() {
  const topic = _currentTopic();
  if (!topic) {
    showToast('Enter a topic first', 'error');
    return;
  }

  await ensureActiveResearch(async () => {
    _generating = true;
    _error = null;
    _jobDetail = 'Generating report…';
    _render();

    try {
      const { job_id } = await api.refreshReport({ topic });
      await _pollJob(job_id);
    } catch (err) {
      _generating = false;
      _error = err.message || 'Failed to generate report';
      _render();
    }
  });
}

async function _pollJob(jobId) {
  let consecutiveFailures = 0;
  let elapsedPolls = 0;

  // eslint-disable-next-line no-constant-condition
  while (true) {
    elapsedPolls += 1;
    let job = null;
    let err = null;
    try {
      job = await api.getJob(jobId);
    } catch (e) {
      err = e;
    }

    if (!err) {
      consecutiveFailures = 0;
      if (job && job.status !== 'running') {
        _generating = false;
        if (job.status === 'failed') {
          _error = job.detail || 'Report generation failed';
        } else {
          _error = null;
          try {
            _report = await api.getReport();
          } catch (fetchErr) {
            console.warn('[report] post-job refetch failed:', fetchErr);
          }
        }
        _render();
        return;
      }
      _jobDetail = (job && job.detail) || 'Generating report…';
      _render();
    }

    const decision = pollDecision({
      status: job ? job.status : undefined,
      error: err,
      consecutiveFailures,
      elapsedPolls,
    });

    if (decision === 'retry-transient') consecutiveFailures += 1;
    if (decision === 'give-up' || decision === 'stop-404') {
      _generating = false;
      _error = 'Report generation is taking too long — try refreshing.';
      _render();
      return;
    }

    await new Promise(resolve => setTimeout(resolve, _POLL_MS));
  }
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

function _render() {
  if (!_el) return;

  const sections = (_report && Array.isArray(_report.sections)) ? _report.sections : [];
  const topic = (_report && typeof _report.topic === 'string') ? _report.topic : '';
  const models = sections.map(reportSectionModel);

  _el.innerHTML = `
    <div class="report-view">
      <div class="report-header">
        <h2>Report</h2>
        <p class="muted">A cited literature review of your library on a topic. Based on your library — not the open web.</p>
      </div>
      <div class="report-controls">
        <input type="text" id="report-topic-input" class="report-topic-input"
               placeholder="e.g. graph-based retrieval for code search" value="${escapeHtml(topic)}" />
        <button class="btn btn-primary report-generate-btn" ${_generating ? 'disabled' : ''}>
          ${_generating ? 'Generating…' : 'Generate report'}
        </button>
      </div>
      ${_generating ? `<div class="report-progress muted">${escapeHtml(_jobDetail)}</div>` : ''}
      ${_error ? `<div class="report-error">${escapeHtml(_error)}</div>` : ''}
      <div class="report-body">
        ${!_generating && models.length === 0 ? _emptyHtml() : models.map(_sectionHtml).join('')}
      </div>
    </div>`;

  _bindEvents();
}

function _emptyHtml() {
  return `<div class="report-empty muted">Enter a topic and generate a report from your library.</div>`;
}

function _sectionHtml(m) {
  const chips = m.citations.map(c => `
    <button class="chip report-citation-chip" data-paper-id="${escapeHtml(c.paperId)}" data-section-id="${escapeHtml(c.sectionId)}">
      ${c.label}
    </button>`).join('');

  const bodyHtml = m.hasError
    ? `<div class="report-section-error">${m.errorMessage}</div>`
    : `<div class="report-answer">${m.answer}</div>
       <div class="report-citations">${chips}</div>
       ${m.unverifiedQuotes.length > 0
          ? `<div class="report-unverified muted">Unverified quote${m.unverifiedQuotes.length === 1 ? '' : 's'} (not found verbatim in your library): ${m.unverifiedQuotes.join('; ')}</div>`
          : ''}`;

  return `
    <div class="report-section">
      <div class="report-question">${m.question}</div>
      ${bodyHtml}
    </div>`;
}

// ---------------------------------------------------------------------------
// Event binding
// ---------------------------------------------------------------------------

function _bindEvents() {
  if (!_el) return;

  const btn = _el.querySelector('.report-generate-btn');
  if (btn) btn.addEventListener('click', () => { _generate(); });

  const input = _el.querySelector('#report-topic-input');
  if (input) {
    input.addEventListener('keydown', (evt) => {
      if (evt.key === 'Enter') _generate();
    });
  }

  _el.querySelectorAll('.report-citation-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      const paperId = chip.dataset.paperId;
      if (!paperId) return;
      window.__rcPendingPaper = paperId;
      window.dispatchEvent(new CustomEvent('rc:open-paper', {
        detail: { paper_id: paperId },
        bubbles: true,
      }));
      window.location.hash = '#/library';
    });
  });
}
