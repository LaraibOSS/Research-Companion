/**
 * views/agents.js — the Agents page (#/agents).
 *
 * Each agent does one job on a paper and reports back. This page lists them
 * by stage, says plainly what each costs, lets the person tick the ones they
 * want, says before the click what will run and whether it is paid, and shows
 * each agent's last result on the chosen paper.
 *
 * Truth lives on the server (GET /api/agents, POST /api/agents/run). The
 * pure helpers in agentsHelpers.js only decide presentation; a refused run
 * shows every reason the server gave.
 */

import * as api from '../api.js';
import * as store from '../store.js';
import { showToast } from '../components/toast.js';
import { escapeHtml } from '../format.js';
import {
  costLabel,
  groupByStage,
  lastResultLabel,
  refusalReasons,
  selectionSummary,
} from '../agentsHelpers.js';

let _el = null;
let _agents = [];
let _modelConfigured = null;
let _paperId = '';
let _selected = new Set();
let _inputs = { venue: '', problem_statement: '' };
let _running = false;
let _refusal = [];
let _loadError = '';
let _unsub = null;
let _seq = 0;

export function mount(el) {
  _el = el;
  _selected = new Set();
  _refusal = [];
  _running = false;
  _loadError = '';
  _paperId = _defaultPaperId();
  _render();
  _load();
  // The library may still be loading on first visit: re-render the paper
  // picker when it arrives.
  _unsub = store.subscribe(['papers'], () => {
    if (!_paperId) _paperId = _defaultPaperId();
    if (!_running) _render();
  });
}

export function unmount() {
  if (_unsub) { _unsub(); _unsub = null; }
  _el = null;
}

function _papers() {
  const { papers } = store.getState();
  const list = papers instanceof Map ? [...papers.values()] : (Array.isArray(papers) ? papers : []);
  return list.filter((p) => p && p.paper_id);
}

function _defaultPaperId() {
  const { draftId } = store.getState();
  if (draftId) return draftId;
  const first = _papers()[0];
  return first ? first.paper_id : '';
}

async function _load() {
  const seq = ++_seq;
  try {
    const data = await api.getAgents(_paperId || undefined);
    if (seq !== _seq || !_el) return;          // a newer load superseded this one
    _agents = Array.isArray(data.agents) ? data.agents : [];
    _modelConfigured = data.model_configured !== false;
    _loadError = '';
  } catch (err) {
    if (seq !== _seq || !_el) return;
    _loadError = 'The list of agents could not be loaded. Is the Lab server running?';
    console.error('[agents view] load error', err);
  }
  _render();
}

function _render() {
  if (!_el) return;
  const summary = selectionSummary(_agents, _selected, {
    paperId: _paperId, modelConfigured: _modelConfigured, inputs: _inputs,
  });
  _el.innerHTML = `
    <div class="agents-page">
      <header class="agents-header">
        <h2>Agents</h2>
        <p class="agents-intro">Each agent does one job on a paper and reports back.
          Free agents run on this machine. Agents marked
          <strong>Uses your model</strong> make paid calls to your provider.</p>
      </header>
      ${_loadError ? `<div class="agents-error" role="alert">${escapeHtml(_loadError)}</div>` : ''}
      ${_paperPickerHtml()}
      <div class="agents-groups">
        ${groupByStage(_agents).map(_groupHtml).join('')}
      </div>
      ${_inputsHtml(summary)}
      ${_footerHtml(summary)}
    </div>`;
  _bind();
}

function _paperPickerHtml() {
  const papers = _papers();
  if (!papers.length) {
    return `<div class="agents-empty">Add a paper to your library first. Agents work on one paper at a time.</div>`;
  }
  const options = papers.map((p) => {
    const label = p.title || p.paper_id;
    const sel = p.paper_id === _paperId ? ' selected' : '';
    return `<option value="${escapeHtml(p.paper_id)}"${sel}>${escapeHtml(label)}</option>`;
  }).join('');
  return `
    <label class="agents-paper">
      <span>Paper</span>
      <select id="agents-paper-select">${options}</select>
    </label>`;
}

function _groupHtml(group) {
  return `
    <section class="agents-group" aria-labelledby="agents-stage-${escapeHtml(group.stage)}">
      <h3 id="agents-stage-${escapeHtml(group.stage)}">${escapeHtml(group.heading)}</h3>
      <ul class="agents-list">${group.agents.map(_agentHtml).join('')}</ul>
    </section>`;
}

function _agentHtml(a) {
  const cost = costLabel(a.cost);
  const last = lastResultLabel(a.last);
  const disabled = a.runnable_here === false;
  const checked = _selected.has(a.name) ? ' checked' : '';
  const needs = (a.needs || []).length
    ? `<div class="agent-needs">Needs: ${escapeHtml(a.needs.join(', '))}</div>` : '';
  const onlyCli = disabled
    ? `<div class="agent-needs">Run from the command line: research-companion ${escapeHtml((a.reachable_from || [])[0] || 'review')}</div>`
    : '';
  const lastDetail = last.detail
    ? `<div class="agent-last-detail">${escapeHtml(last.detail)}</div>` : '';
  return `
    <li class="agent-card${disabled ? ' agent-card-disabled' : ''}">
      <label class="agent-pick">
        <input type="checkbox" class="agent-check" data-agent="${escapeHtml(a.name)}"${checked}${disabled ? ' disabled' : ''}>
        <span class="agent-title">${escapeHtml(a.title)}</span>
      </label>
      <span class="agent-cost agent-tone-${cost.tone}" title="${escapeHtml(cost.hint)}">${escapeHtml(cost.text)}</span>
      <p class="agent-does">${escapeHtml(a.does)}</p>
      ${needs}${onlyCli}
      ${a.last ? `<div class="agent-last agent-tone-${last.tone}">Last result: ${escapeHtml(last.text)}</div>${lastDetail}` : ''}
    </li>`;
}

function _inputsHtml(summary) {
  const fields = [];
  if (summary.needs.includes('venue')) {
    fields.push(`
      <label class="agents-input">
        <span>Target venue</span>
        <input type="text" id="agents-venue" placeholder="for example neurips" value="${escapeHtml(_inputs.venue)}">
      </label>`);
  }
  if (summary.needs.includes('problem statement')) {
    fields.push(`
      <label class="agents-input">
        <span>Your problem statement</span>
        <textarea id="agents-problem" rows="3" placeholder="One or two sentences on the problem you are working on">${escapeHtml(_inputs.problem_statement)}</textarea>
      </label>`);
  }
  return fields.length ? `<div class="agents-inputs">${fields.join('')}</div>` : '';
}

function _footerHtml(summary) {
  const count = summary.willRun.length;
  const added = summary.added.length
    ? `<div class="agents-added">Also runs, because the chosen agents need them: ${escapeHtml(summary.added.join(', '))}.</div>`
    : '';
  const blockers = (_refusal.length ? _refusal : summary.blockers)
    .filter((b) => b !== 'Choose at least one agent.' || _selected.size > 0 || _refusal.length);
  const blockerHtml = blockers.length
    ? `<ul class="agents-blockers" role="status">${blockers.map((b) => `<li>${escapeHtml(b)}</li>`).join('')}</ul>`
    : '';
  const label = _running ? 'Running…' : (count ? `Run ${count} agent${count === 1 ? '' : 's'}` : 'Run');
  const disabled = _running || !summary.canRun ? ' disabled' : '';
  return `
    <footer class="agents-footer">
      ${added}
      ${count ? `<div class="agents-cost agent-tone-${summary.usesModel ? 'warn' : 'ok'}">${escapeHtml(summary.costLine)}</div>` : ''}
      ${blockerHtml}
      <button class="btn btn-accent" id="agents-run"${disabled}>${escapeHtml(label)}</button>
    </footer>`;
}

function _bind() {
  if (!_el) return;
  const paperSel = _el.querySelector('#agents-paper-select');
  if (paperSel) {
    paperSel.addEventListener('change', () => {
      _paperId = paperSel.value;
      _refusal = [];
      _load();
    });
  }
  _el.querySelectorAll('.agent-check').forEach((box) => {
    box.addEventListener('change', () => {
      const name = box.getAttribute('data-agent');
      if (box.checked) _selected.add(name); else _selected.delete(name);
      _refusal = [];
      _render();
    });
  });
  const venue = _el.querySelector('#agents-venue');
  if (venue) venue.addEventListener('change', () => { _inputs.venue = venue.value; _refusal = []; _render(); });
  const problem = _el.querySelector('#agents-problem');
  if (problem) problem.addEventListener('change', () => { _inputs.problem_statement = problem.value; _refusal = []; _render(); });
  const run = _el.querySelector('#agents-run');
  if (run) run.addEventListener('click', _run);
}

async function _run() {
  if (_running) return;
  _running = true;
  _refusal = [];
  _render();
  let res;
  try {
    res = await api.runAgents(_paperId, [..._selected], _inputs);
  } catch (err) {
    _running = false;
    _refusal = refusalReasons(err);
    _render();
    return;
  }
  showToast(`Started ${res.agents.length} agent${res.agents.length === 1 ? '' : 's'}`, 'info');
  // Poll the job rather than relying on the event stream, so a missed event
  // can never leave the button stuck on "Running…".
  const runSeq = _seq;
  const poll = async () => {
    if (!_el) return;                               // page left: stop
    let status = 'running';
    try {
      status = (await api.getJob(res.job_id)).status;
    } catch { status = 'unknown'; }
    if (status === 'running') { setTimeout(poll, 1500); return; }
    _running = false;
    if (status === 'failed') showToast('The agent run failed. See each agent's result.', 'error');
    if (runSeq === _seq || _el) _load();
  };
  setTimeout(poll, 800);
}
