/**
 * agentsHelpers.js — pure, DOM-free logic for the Agents page.
 *
 * The server owns what is true (GET /api/agents: the catalogue, each agent's
 * dependencies, cost and needs; POST /api/agents/run refuses anything that
 * cannot run). These helpers only decide how that looks and what the person
 * is told BEFORE they press Run: which agents will run, whether it is paid,
 * and what is missing. The server re-checks everything, so a disagreement can
 * only cost a refused request, never a wrong run.
 */

export const STAGE_HEADINGS = {
  prepare:    'Prepare',
  check:      'Check the paper',
  position:   'Position the work',
  prioritise: 'Decide what to fix first',
  respond:    'Respond to reviewers',
};

const STAGE_ORDER = ['prepare', 'check', 'position', 'prioritise', 'respond'];

const COSTS = {
  free:    { text: 'Free',          tone: 'ok',   hint: 'Runs on this machine. No key, nothing sent.' },
  network: { text: 'Free, online',  tone: 'info', hint: 'Looks titles and identifiers up in public catalogues.' },
  model:   { text: 'Uses your model', tone: 'warn', hint: 'Makes paid calls to your model provider.' },
};

/** Cost badge for a cost word. Unknown words are never shown as free. */
export function costLabel(cost) {
  return COSTS[cost] || { text: 'Cost unknown', tone: 'warn', hint: 'This agent did not state its cost.' };
}

/**
 * Agents grouped by stage, in the catalogue's order.
 * @param {Array<object>} agents — rows from GET /api/agents
 * @returns {Array<{stage:string, heading:string, agents:Array<object>}>}
 */
export function groupByStage(agents) {
  const list = Array.isArray(agents) ? agents : [];
  const groups = [];
  for (const stage of STAGE_ORDER) {
    const inStage = list.filter((a) => a && a.stage === stage);
    if (inStage.length) groups.push({ stage, heading: STAGE_HEADINGS[stage], agents: inStage });
  }
  return groups;
}

/** Every agent the selection needs, including dependencies, by name. */
export function expandSelection(agents, selected) {
  const byName = new Map((agents || []).map((a) => [a.name, a]));
  const out = new Set();
  const stack = [...(selected || [])];
  while (stack.length) {
    const name = stack.pop();
    if (out.has(name) || !byName.has(name)) continue;
    out.add(name);
    for (const dep of byName.get(name).depends_on || []) stack.push(dep);
  }
  return out;
}

const NEED_FIELDS = { 'venue': 'venue', 'problem statement': 'problem_statement' };

/**
 * What pressing Run would do, and what stops it.
 *
 * @param {Array<object>} agents
 * @param {Iterable<string>} selected
 * @param {{paperId?:string, modelConfigured?:boolean, inputs?:object}} opts
 * @returns {{willRun:string[], added:string[], usesModel:boolean,
 *   usesNetwork:boolean, needs:string[], blockers:string[], canRun:boolean,
 *   costLine:string}}
 */
export function selectionSummary(agents, selected, opts = {}) {
  const byName = new Map((agents || []).map((a) => [a.name, a]));
  const chosen = [...new Set(selected || [])].filter((n) => byName.has(n));
  const all = expandSelection(agents, chosen);
  const order = (agents || []).map((a) => a.name);
  const willRun = order.filter((n) => all.has(n));
  const added = willRun.filter((n) => !chosen.includes(n));

  let usesModel = false;
  let usesNetwork = false;
  const needs = [];
  const blockers = [];
  const inputs = opts.inputs || {};

  for (const name of willRun) {
    const a = byName.get(name);
    if (a.cost === 'model') usesModel = true;
    if (a.cost === 'network') usesNetwork = true;
    if (a.runnable_here === false) {
      blockers.push(`${a.title} can only be run from the command line.`);
    }
    for (const need of a.needs || []) {
      if (!needs.includes(need)) needs.push(need);
      const field = NEED_FIELDS[need];
      if (field && !String(inputs[field] || '').trim()) {
        const msg = `${a.title} needs a ${need}.`;
        if (!blockers.includes(msg)) blockers.push(msg);
      }
    }
  }
  if (!chosen.length) blockers.unshift('Choose at least one agent.');
  if (!opts.paperId) blockers.unshift('Choose a paper.');
  if (usesModel && opts.modelConfigured === false) {
    blockers.push('A chosen agent uses a model, and no model is set up. Add one in Settings, or choose free agents.');
  }

  let costLine = 'Free. Runs on this machine.';
  if (usesModel) costLine = 'Makes paid calls to your model provider.';
  else if (usesNetwork) costLine = 'Free. Looks things up in public catalogues.';

  return {
    willRun, added: added.map((n) => byName.get(n).title),
    usesModel, usesNetwork, needs, blockers,
    canRun: blockers.length === 0, costLine,
  };
}

/** How an agent's last result on the chosen paper is shown. */
export function lastResultLabel(last) {
  const state = last && last.state;
  if (state === 'done')   return { text: 'Done', tone: 'ok' };
  if (state === 'failed') return { text: 'Failed', tone: 'fail', detail: (last.error || '').trim() };
  return { text: 'Not run yet', tone: 'muted' };
}

/** Turn a refused run (HTTP 400 detail) into the list of reasons to show. */
export function refusalReasons(err) {
  const detail = err && err.detail;
  if (detail && Array.isArray(detail.problems) && detail.problems.length) {
    return detail.problems.map(String);
  }
  const msg = err && err.message ? String(err.message) : '';
  return [msg || 'The agents could not be started.'];
}
