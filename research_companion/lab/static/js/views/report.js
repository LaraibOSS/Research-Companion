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
import {
  reportSectionModel, reportCoverageModel, reportPlanModel,
  reportEmptyState, reportCostLine, reportPlanStatus,
} from '../reportHelpers.js';
import { claimAuditBadge, claimAuditSummaryLine, CLAIM_AUDIT_DISCLAIMER } from '../claimAuditHelpers.js';
import { tip } from '../glossary.js';

// RCS stance vocab (supports/contradicts/neutral, Report Evidence Scoring
// / RCS, 2e-2) -> a badge color, keyed directly by the rcs stanceSlug
// (mirrors draft.js's own local STANCE_COLORS constant -- colors are not
// centralized in format.js).
const RCS_STANCE_COLORS = {
  supports: '#3fb950',
  contradicts: '#f85149',
  neutral: '#58a6ff',
};

// ---------------------------------------------------------------------------
// Module state
// ---------------------------------------------------------------------------

let _el = null;
let _unsubs = [];
let _report = null;      // last fetched GET /api/report payload
let _generating = false;
let _jobDetail = '';
let _error = null;
let _scoring = false;         // Report Evidence Scoring (RCS, 2e-2)
let _scoreDetail = '';
let _scoreError = null;
let _audit = null;            // last GET /api/claim-audit payload for the report
let _auditing = false;
let _auditError = null;

// Editable Research Plan (Phase 2, slice 2e-4). `_plan` is the RAW
// (unescaped) editable list of question strings -- only ever written into
// a <textarea>.value (never interpolated into HTML), so no escaping is
// needed here; reportPlanModel()'s escaped copy is used only for the
// read-only "Plan: N questions" summary line, never for editing.
let _plan = null;          // string[] | null -- non-null iff _planMode is true
let _planMode = false;     // true -> render the editable plan list
let _planGenerating = false;
let _planError = null;

const _POLL_MS = 800;

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

export function mount(el) {
  _el = el;
  _generating = false;
  _jobDetail = '';
  _error = null;
  _scoring = false;
  _scoreDetail = '';
  _scoreError = null;
  _plan = null;
  _planMode = false;
  _planGenerating = false;
  _planError = null;

  el.innerHTML = `<div class="report-view"><div class="report-loading muted">Loading report…</div></div>`;

  // The claim-audit job publishes JobStarted/JobFinished on 'activity'; pull
  // the stored result once it ends so badges appear without a manual reload.
  _unsubs.push(store.subscribe(['activity'], async () => {
    const { activeJobs } = store.getState();
    const running = activeJobs
      && [...activeJobs.values()].some(j => j && j.kind === 'claim-audit');
    if (running || !_auditing) return;
    _auditing = false;
    try {
      const data = await api.getClaimAudit('report');
      _audit = (data && data.audit) || null;
    } catch {
      _audit = null;
    }
    _render();
  }));

  // The empty state's advice depends on how many papers exist. Boot hydrates
  // papers before the router mounts anything, so the first render is already
  // accurate — but a workspace switch re-snapshots the library underneath a
  // live view, and adding a paper changes the count. Re-render on both so the
  // advice never contradicts what the Library tab shows.
  _unsubs.push(store.subscribe(['papers'], () => {
    if (!_report || !Array.isArray(_report.sections) || _report.sections.length === 0) {
      _render();
    }
  }));

  _unsubs.push(store.subscribe(['report'], async () => {
    try {
      _report = await api.getReport();
    } catch (err) {
      console.warn('[report] refetch failed:', err);
    }
    _syncPlanFromReport();
    _render();
  }));

  _fetch();
}

export function unmount() {
  for (const u of _unsubs) u();
  _unsubs = [];
  // Clear the payloads too. _report and _audit outlived the view, so switching
  // research showed the previous workspace's report and claim audit until the
  // new one finished loading.
  _report = null;
  _audit = null;
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
  // Non-fatal: an absent or failed audit just means no badges.
  try {
    const data = await api.getClaimAudit('report');
    _audit = (data && data.audit) || null;
  } catch {
    _audit = null;
  }
  _syncPlanFromReport();
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
// Editable Research Plan (Phase 2, slice 2e-4)
//
// "Generate plan" (api.reportPlan -- SYNCHRONOUS, one LLM call, like
// api.directions) populates `_plan` (raw editable question strings) and
// switches into edit mode; the plan list itself (add/remove/reorder/edit)
// is entirely CLIENT-SIDE (no per-edit network call); "Run report" posts
// the edited list via the EXISTING api.refreshReport({topic, questions})
// 202 job + _pollJob (reused as-is). A saved plan.status === 'draft' (from
// GET /api/report) opens the view in edit mode on load/refetch; an
// 'answered' plan shows the report with an "Edit plan / re-run" affordance
// that repopulates `_plan` from the report's own plan.questions.
// ---------------------------------------------------------------------------

function _syncPlanFromReport() {
  const rawPlan = _report && _report.plan;
  if (rawPlan && rawPlan.status === 'draft' && Array.isArray(rawPlan.questions)) {
    _plan = rawPlan.questions.slice();
    _planMode = true;
  } else {
    _planMode = false;
  }
}

async function _generatePlan() {
  const topic = _currentTopic();
  if (!topic) {
    showToast('Enter a topic first', 'error');
    return;
  }

  await ensureActiveResearch(async () => {
    _planGenerating = true;
    _planError = null;
    _render();

    try {
      const data = await api.reportPlan({ topic });
      _planGenerating = false;
      if (!data || data.ok !== true || !data.plan) {
        _planError = (data && data.error) || 'Failed to generate plan';
        _render();
        return;
      }
      _plan = Array.isArray(data.plan.questions) ? data.plan.questions.slice() : [];
      _planMode = true;
      if (_report) _report.plan = data.plan;
      _render();
    } catch (err) {
      _planGenerating = false;
      _planError = err.message || 'Failed to generate plan';
      _render();
    }
  });
}

async function _runReport() {
  const topic = _currentTopic();
  if (!topic) {
    showToast('Enter a topic first', 'error');
    return;
  }
  const questions = (_plan || []).map(q => (q || '').trim()).filter(q => q);
  if (questions.length === 0) {
    showToast('Add at least one question first', 'error');
    return;
  }

  await ensureActiveResearch(async () => {
    _generating = true;
    _error = null;
    _jobDetail = 'Generating report…';
    _render();

    try {
      const { job_id } = await api.refreshReport({ topic, questions });
      await _pollJob(job_id);
      if (!_error) {
        _planMode = false;
        _render();
      }
    } catch (err) {
      _generating = false;
      _error = err.message || 'Failed to generate report';
      _render();
    }
  });
}

function _editPlan() {
  const rawPlan = _report && _report.plan;
  _plan = (rawPlan && Array.isArray(rawPlan.questions)) ? rawPlan.questions.slice() : [];
  _planMode = true;
  _planError = null;
  _render();
}

function _planListHtml() {
  const rows = _plan.map((_q, i) => `
    <div class="report-plan-row" data-q-idx="${i}">
      <textarea class="report-plan-q" data-q-idx="${i}" rows="2" aria-label="Investigation question ${i + 1}"></textarea>
      <div class="report-plan-row-actions">
        <button type="button" class="btn-icon report-plan-up" data-q-idx="${i}" title="Move up" ${i === 0 ? 'disabled' : ''}>&#9650;</button>
        <button type="button" class="btn-icon report-plan-down" data-q-idx="${i}" title="Move down" ${i === _plan.length - 1 ? 'disabled' : ''}>&#9660;</button>
        <button type="button" class="btn-icon report-plan-delete" data-q-idx="${i}" title="Remove question">&#10005;</button>
      </div>
    </div>`).join('');

  const canRun = _plan.some(q => q && q.trim());

  return `
    <div class="report-plan-editor">
      <p class="report-plan-hint muted">Review, edit, add, remove, or reorder these investigation questions, then Run report to answer exactly this set.</p>
      <div class="report-plan-list">${rows}</div>
      <div class="report-plan-actions">
        <button type="button" class="btn btn-secondary report-plan-add-btn">+ Add question</button>
        <button type="button" class="btn btn-primary report-run-btn" ${(_generating || !canRun) ? 'disabled' : ''}>
          ${_generating ? 'Running…' : 'Run report'}
        </button>
      </div>
    </div>`;
}

// ---------------------------------------------------------------------------
// Score evidence (Report Evidence Scoring / RCS, 2e-2)
// ---------------------------------------------------------------------------

async function _scoreEvidence() {
  await ensureActiveResearch(async () => {
    _scoring = true;
    _scoreError = null;
    _scoreDetail = 'Scoring evidence…';
    _render();

    try {
      const { job_id } = await api.scoreEvidence();
      await _pollScoreJob(job_id);
    } catch (err) {
      _scoring = false;
      _scoreError = err.message || 'Failed to score evidence';
      _render();
    }
  });
}

async function _pollScoreJob(jobId) {
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
        _scoring = false;
        if (job.status === 'failed') {
          _scoreError = job.detail || 'Evidence scoring failed';
        } else {
          _scoreError = null;
          try {
            _report = await api.getReport();
          } catch (fetchErr) {
            console.warn('[report] post-score refetch failed:', fetchErr);
          }
        }
        _render();
        return;
      }
      _scoreDetail = (job && job.detail) || 'Scoring evidence…';
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
      _scoring = false;
      _scoreError = 'Evidence scoring is taking too long — try refreshing.';
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
  const hasReport = models.length > 0;
  // The honesty caption appears only once at least one citation actually
  // carries an rcs badge — an unscored report renders exactly as 2e-1.
  const hasRcs = models.some(m => (m.citations || []).some(c => c && c.rcs));

  // Coverage / Saturation (2e-3, LLM-FREE, always-on) -- purely additive:
  // a report with no `coverage` field (an older client's report, or a
  // coverage computation that failed and was skipped) renders exactly as
  // 2e-1/2e-2 -- no bar, no summary line, no caption.
  const reportCoverage = reportCoverageModel(_report);
  const hasCoverage = !!reportCoverage;
  const coverageCaption = (reportCoverage && reportCoverage.relevantAvailable === 0)
    ? 'No relevant library material was found for these questions — coverage cannot be computed yet.'
    : 'Coverage is a BM25 heuristic — relative to what our own search judged relevant to each question, not ground truth.';

  // Editable Research Plan (2e-4, purely additive) -- a report with no
  // `plan` field (older than this slice) renders with none of this: no
  // status line, no "Edit plan / re-run" button, exactly as 2e-1/2e-2/2e-3.
  const planModel = reportPlanModel(_report && _report.plan);
  const planStatusLine = planModel
    ? `<p class="report-plan-status muted">${escapeHtml(reportPlanStatus(planModel))}</p>`
    : '';

  // What a run costs, in the unit the user is billed in. Shown before the
  // click, not after: an unexpected bill is the fastest way to lose trust in
  // an opt-in AI feature. Exact once a plan pins the question count.
  const costLine = reportCostLine({
    questionCount: planModel ? planModel.questions.length : null,
  });
  const editPlanBtnHtml = (planModel && !_planMode)
    ? `<button class="btn btn-secondary report-edit-plan-btn" type="button" ${(_generating || _scoring) ? 'disabled' : ''}>Edit plan / re-run</button>`
    : '';

  _el.innerHTML = `
    <div class="report-view">
      <div class="report-header">
        <h2>Report</h2>
        <p class="muted">A cited literature review of your library on a topic. Based on your library — not the open web.</p>
      </div>
      <div class="report-controls">
        <input type="text" id="report-topic-input" class="report-topic-input"
               placeholder="e.g. graph-based retrieval for code search" value="${escapeHtml(topic)}" />
        <button class="btn ${_planMode ? 'btn-secondary' : 'btn-primary'} report-generate-plan-btn" type="button"
                title="${_planMode
                  ? 'Replace the plan below with a freshly generated one'
                  : 'Write the question list first — free to edit before you pay to answer it'}"
                ${(_planGenerating || _generating) ? 'disabled' : ''}>
          ${_planGenerating ? 'Generating plan…' : 'Generate plan'}
        </button>
        <button class="btn btn-secondary report-generate-btn" ${_generating ? 'disabled' : ''}>
          ${_generating ? 'Generating…' : 'Generate report'}
        </button>
        <button class="btn btn-secondary report-score-evidence-btn"
                ${(!hasReport || _scoring || _generating) ? 'disabled' : ''}>
          ${_scoring ? 'Scoring…' : 'Score evidence'}
        </button>
        <button class="btn btn-secondary report-audit-btn" type="button"
                title="Check whether each cited passage actually supports the claim (uses your model)"
                ${(!hasReport || _auditing || _generating) ? 'disabled' : ''}>
          ${_auditing ? 'Checking citations…' : 'Check citations'}
        </button>
        <button class="btn btn-secondary report-export-btn" type="button" ${!hasReport ? 'disabled' : ''}>
          Download (.md)
        </button>
      </div>
      <p class="report-cost-line muted">${escapeHtml(costLine)}</p>
      ${_auditError ? `<div class="report-error">${escapeHtml(_auditError)}</div>` : ''}
      ${_auditSummaryHtml()}
      ${_planError ? `<div class="report-error report-plan-error">${escapeHtml(_planError)}</div>` : ''}
      ${planStatusLine}
      ${editPlanBtnHtml}
      ${_planMode ? _planListHtml() : ''}
      ${_generating ? `<div class="report-progress muted">${escapeHtml(_jobDetail)}</div>` : ''}
      ${_error ? `<div class="report-error">${escapeHtml(_error)}</div>` : ''}
      ${_scoring ? `<div class="report-progress muted">${escapeHtml(_scoreDetail)}</div>` : ''}
      ${_scoreError ? `<div class="report-error">${escapeHtml(_scoreError)}</div>` : ''}
      ${hasRcs ? '<p class="report-rcs-caption muted">Relevance &amp; stance are AI judgments of the cited passage — not independently verified.</p>' : ''}
      ${hasCoverage ? `
        <div class="report-coverage report-coverage--summary"${tip('coverage')} title="${reportCoverage.pct}% (${reportCoverage.cited}/${reportCoverage.relevantAvailable})">
          <span class="report-coverage-label">Overall coverage: ${reportCoverage.pct}% (median ${reportCoverage.medianPct}%) — ${reportCoverage.cited}/${reportCoverage.relevantAvailable} relevant passages cited</span>
          <div class="research-cov-bar">
            <div class="research-cov-bar-fill" style="width:${reportCoverage.pct}%"></div>
          </div>
        </div>
        <p class="report-coverage-caption muted">${coverageCaption}</p>
      ` : ''}
      <div class="report-body">
        ${!_generating && models.length === 0 ? _emptyHtml() : models.map((m, i) => _sectionHtml(m, i)).join('')}
      </div>
    </div>`;

  _bindEvents();
}

function _emptyHtml() {
  // Distinguishes a missing prerequisite (no papers -> Generate cannot help)
  // from a caveat about quality (few papers -> it will work, but read thin).
  const { papers } = store.getState();
  const s = reportEmptyState({ paperCount: papers ? papers.size : 0 });
  return `<div class="report-empty${s.blocked ? ' report-empty--blocked' : ''}">
      <p class="report-empty-headline">${escapeHtml(s.headline)}</p>
      <p class="muted">${escapeHtml(s.detail)}</p>
      <p class="muted report-empty-tip">${escapeHtml(s.tip)}</p>
    </div>`;
}

function _rcsBadgeHtml(rcs) {
  if (!rcs) return '';
  const color = RCS_STANCE_COLORS[rcs.stanceSlug] || '#8b949e';
  return `
    <span class="rcs-badge" style="color:${escapeHtml(color)}" title="${rcs.rationale}">
      <span class="rcs-badge-relevance"${tip('rcs_relevance')}>${rcs.relevancePct}%</span>
      <span class="rcs-badge-stance"${tip('rcs_stance')}>${rcs.stanceIcon}</span>
    </span>`;
}

function _coverageBarHtml(cov) {
  // Coverage / Saturation (2e-3) -- purely additive: no coverage on this
  // section (an older/unscored report) renders nothing, exactly 2e-1/2e-2.
  if (!cov) return '';
  return `
    <div class="report-coverage"${tip('coverage')} title="${cov.pct}% (${cov.cited}/${cov.relevantAvailable})">
      <span class="report-coverage-label">Coverage: ${cov.pct}% (${cov.cited}/${cov.relevantAvailable})</span>
      <div class="research-cov-bar">
        <div class="research-cov-bar-fill" style="width:${cov.pct}%"></div>
      </div>
    </div>`;
}


// Claim-audit badge for one citation. Matched on paper+section within the same
// report section, so a re-ordered report never mislabels a citation; anything
// that does not match simply shows no badge rather than a wrong one.

function _auditSummaryHtml() {
  const line = claimAuditSummaryLine(_audit && _audit.summary);
  if (!line) return '';
  return `<div class="report-audit-summary">
      <span class="report-audit-summary-line">${escapeHtml(line)}</span>
      <span class="muted report-audit-note">${escapeHtml(CLAIM_AUDIT_DISCLAIMER)}</span>
    </div>`;
}

async function _runAudit() {
  if (_auditing) return;
  _auditing = true;
  _auditError = null;
  _render();
  try {
    const res = await api.runClaimAudit('report');
    if (!res || !res.ok) {
      _auditError = (res && res.error) || 'Could not start the citation check.';
      _auditing = false;
      _render();
      return;
    }
    showToast('Checking citations against their sources…', 'info');
    // the job publishes JobStarted/JobFinished; refetch when it ends
  } catch (err) {
    _auditError = err.message || 'Could not start the citation check.';
    _auditing = false;
    _render();
  }
}

function _auditFor(sectionIndex, citation) {
  const sections = (_audit && _audit.sections) || [];
  const sec = sections[sectionIndex];
  if (!sec) return null;
  const hit = (sec.citations || []).find(c =>
    String(c.paper_id || '') === String(citation.paperId || '')
    && String(c.section_id || '') === String(citation.sectionId || ''));
  return hit ? hit.audit : null;
}

function _auditBadgeHtml(sectionIndex, citation) {
  const b = claimAuditBadge(_auditFor(sectionIndex, citation));
  if (!b.show) return '';
  const detail = b.reason ? `${b.title} — ${b.reason}` : b.title;
  return `<span class="report-audit-badge audit-${escapeHtml(b.tone)}"
           title="${escapeHtml(detail)}">${escapeHtml(b.label)}</span>`;
}

function _sectionHtml(m, sectionIndex) {
  const chips = m.citations.map(c => `
    <button class="chip report-citation-chip" data-paper-id="${escapeHtml(c.paperId)}" data-section-id="${escapeHtml(c.sectionId)}">
      ${c.label}${_rcsBadgeHtml(c.rcs)}${_auditBadgeHtml(sectionIndex, c)}
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
      ${_coverageBarHtml(m.coverage)}
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

  const scoreBtn = _el.querySelector('.report-score-evidence-btn');
  if (scoreBtn) scoreBtn.addEventListener('click', () => { _scoreEvidence(); });

  const auditBtn = _el.querySelector('.report-audit-btn');
  if (auditBtn) auditBtn.addEventListener('click', () => { _runAudit(); });

  const exportBtn = _el.querySelector('.report-export-btn');
  if (exportBtn) exportBtn.addEventListener('click', () => { _exportReport(); });

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

  _bindPlanEvents();
}

// ---------------------------------------------------------------------------
// Editable Research Plan (2e-4) event binding -- all list edits are
// CLIENT-SIDE ONLY (no per-edit network call); textarea values are set
// here in JS (never interpolated into the template string), so no
// escaping is needed for the raw question text.
// ---------------------------------------------------------------------------

function _bindPlanEvents() {
  if (!_el) return;

  const genPlanBtn = _el.querySelector('.report-generate-plan-btn');
  if (genPlanBtn) genPlanBtn.addEventListener('click', () => { _generatePlan(); });

  const editPlanBtn = _el.querySelector('.report-edit-plan-btn');
  if (editPlanBtn) editPlanBtn.addEventListener('click', () => { _editPlan(); });

  if (!_planMode || !Array.isArray(_plan)) return;

  // Set each row's textarea value in JS (not via HTML interpolation) --
  // textarea .value never parses HTML, so raw user text is always safe.
  _el.querySelectorAll('.report-plan-q').forEach((ta) => {
    const idx = Number(ta.dataset.qIdx);
    ta.value = _plan[idx] != null ? _plan[idx] : '';
    ta.addEventListener('input', () => {
      _plan[idx] = ta.value;
    });
  });

  _el.querySelectorAll('.report-plan-delete').forEach((delBtn) => {
    delBtn.addEventListener('click', () => {
      const idx = Number(delBtn.dataset.qIdx);
      _plan.splice(idx, 1);
      _render();
    });
  });

  _el.querySelectorAll('.report-plan-up').forEach((upBtn) => {
    upBtn.addEventListener('click', () => {
      const idx = Number(upBtn.dataset.qIdx);
      if (idx <= 0) return;
      [_plan[idx - 1], _plan[idx]] = [_plan[idx], _plan[idx - 1]];
      _render();
    });
  });

  _el.querySelectorAll('.report-plan-down').forEach((downBtn) => {
    downBtn.addEventListener('click', () => {
      const idx = Number(downBtn.dataset.qIdx);
      if (idx >= _plan.length - 1) return;
      [_plan[idx], _plan[idx + 1]] = [_plan[idx + 1], _plan[idx]];
      _render();
    });
  });

  const addBtn = _el.querySelector('.report-plan-add-btn');
  if (addBtn) {
    addBtn.addEventListener('click', () => {
      _plan.push('');
      _render();
      const rows = _el.querySelectorAll('.report-plan-q');
      const last = rows[rows.length - 1];
      if (last) last.focus();
    });
  }

  const runBtn = _el.querySelector('.report-run-btn');
  if (runBtn) runBtn.addEventListener('click', () => { _runReport(); });
}

// ---------------------------------------------------------------------------
// Export (2e-5) -- Download (.md). The markdown is downloaded as a file
// via a Blob + synthetic <a download>, NEVER inserted into the DOM -- no
// XSS surface. No ensureActiveResearch wrapping: GET /api/report/export
// is read-only and unguarded, exactly like Notes' own export.
// ---------------------------------------------------------------------------

async function _exportReport() {
  try {
    const data = await api.exportReport();
    const markdown = (data && typeof data.markdown === 'string') ? data.markdown : '';
    _downloadMarkdown(markdown);
  } catch (err) {
    showToast('Failed to export report', 'error');
    console.error('[report view] export error', err);
  }
}

function _downloadMarkdown(markdown) {
  const blob = new Blob([markdown], { type: 'text/markdown' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'research-report.md';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
