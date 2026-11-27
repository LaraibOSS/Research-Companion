/**
 * pathHelpers.js — the research path on Home: five stages and ONE next step.
 * Pure and DOM-free (node-testable). Never throws; malformed input degrades
 * to "not started" with a plain reason, never to "done".
 *
 * Why a new module rather than extending nextAction.js: selectNextActions()
 * returns up to three uncosted shortcuts with its own priority order (connect
 * a model first, always) and its tests pin that order. The path needs a
 * different answer — one step, its cost stated before the click, and a free
 * step preferred when no model is configured — so it lives beside it.
 *
 * INPUTS (all optional; each is the raw payload of an existing endpoint, or
 * null when it has not loaded or could not be loaded):
 *   papers    Map<paper_id, paper> or array — GET /api/papers rows
 *   draftId   string | null
 *   settings  GET /api/settings (read through providerReady)
 *   lab       GET /api/lab                    — node_count
 *   gaps      GET /api/gaps                   — themes (fresh only), papers[].gaps
 *   brainstorm GET /api/brainstorm/session    — session.rawDirections
 *   agents    GET /api/agents?paper_id=<draft> — agents[].stage, agents[].last.state
 *
 * STAGE RULES ("library papers" = papers that are not the draft):
 *   collect     done when the library holds at least one paper.
 *   understand  done when at least one library paper has status "done" (its
 *               extraction exists — GET /api/papers sets "done" only then) AND
 *               the concept graph has nodes (lab.node_count > 0). Papers that
 *               merely exist, or a graph count that could not be loaded, are
 *               not enough.
 *   angle       done when the cached gap synthesis has at least one theme
 *               (GET /api/gaps returns themes only while they are fresh) OR
 *               Brainstorm holds at least one generated direction. Per-paper
 *               gaps that were never grouped are not enough.
 *   write       done when a draft is set, is in the library, has status
 *               "done", and is not a scaffolded outline (parse_source
 *               "scaffold" is reported "done" without ever being read).
 *   check       done when write is done AND at least one agent outside the
 *               "prepare" stage has a last result of "done" on that draft. The
 *               Reader and Literature scout only prepare; a failed check is
 *               not a completed one.
 *
 * CURRENT STAGE: the first stage that is not done, in order. "Find your
 * angle" is optional once a draft is set (someone who arrives with a draft
 * need not brainstorm), so it is skipped when choosing the current stage then.
 * When every stage that counts is done, no stage is current.
 *
 * NEXT STEP: exactly one, first match wins (see nextStep() below). Every step
 * says what it does and what it costs, with one of three cost words shared
 * with the Agents page: free, network (free, looks things up online), model
 * (uses your model provider). No call counts are given: the Lab does not
 * compute one for these actions, and a guessed number would be a false
 * promise. When no model is configured, a free step is preferred, and the
 * step says what a model would add.
 */

import { providerReady } from './keyPromptHelpers.js';

export const STAGES = [
  { key: 'collect',    title: 'Collect' },
  { key: 'understand', title: 'Understand' },
  { key: 'angle',      title: 'Find your angle' },
  { key: 'write',      title: 'Write' },
  { key: 'check',      title: 'Check' },
];

/** Words shown for each status, so status is never carried by colour alone. */
export const STATUS_TEXT = { done: 'Done', current: 'Now', not_started: 'Not started' };

const COST_TEXT = {
  free: 'Free',
  network: 'Free, online',
  model: 'Uses your model',
};

function _plural(n, one, many) { return `${n} ${n === 1 ? one : many}`; }

function _papersList(papers) {
  if (papers instanceof Map) return [...papers.values()];
  if (Array.isArray(papers)) return papers;
  return [];
}

function _isObj(x) { return !!x && typeof x === 'object' && !Array.isArray(x); }

/** Count what the stage rules read. Exported for tests. */
export function pathFacts(input) {
  const s = _isObj(input) ? input : {};
  const draftId = typeof s.draftId === 'string' && s.draftId ? s.draftId : null;
  const all = _papersList(s.papers).filter(p => _isObj(p) && typeof p.paper_id === 'string');

  const draft = draftId ? (all.find(p => p.paper_id === draftId) || null) : null;
  const library = all.filter(p => p.paper_id !== draftId && !p.is_draft);
  const read = library.filter(p => p.status === 'done' && p.parse_source !== 'scaffold').length;
  const failed = library.filter(p => p.status === 'failed').length;
  const unread = library.length - read - failed;

  const lab = _isObj(s.lab) ? s.lab : null;
  const nodes = lab && Number.isFinite(lab.node_count) ? lab.node_count : null;

  const gaps = _isObj(s.gaps) ? s.gaps : null;
  const themes = gaps ? (Array.isArray(gaps.themes) ? gaps.themes.length : 0) : null;
  let paperGaps = 0;
  if (gaps && Array.isArray(gaps.papers)) {
    for (const p of gaps.papers) {
      if (_isObj(p) && Array.isArray(p.gaps)) paperGaps += p.gaps.length;
    }
  }

  const bs = _isObj(s.brainstorm) ? s.brainstorm : null;
  let directions = null;
  if (bs) {
    const sess = _isObj(bs.session) ? bs.session : null;
    directions = sess && Array.isArray(sess.rawDirections) ? sess.rawDirections.length : 0;
  }

  const ag = _isObj(s.agents) && Array.isArray(s.agents.agents) ? s.agents.agents : null;
  let checksDone = null;
  let checksFailed = null;
  if (ag) {
    const checks = ag.filter(a => _isObj(a) && a.stage && a.stage !== 'prepare');
    checksDone = checks.filter(a => _isObj(a.last) && a.last.state === 'done').length;
    checksFailed = checks.filter(a => _isObj(a.last) && a.last.state === 'failed').length;
  }

  let draftState = 'none';
  if (draftId && !draft) draftState = 'missing';
  else if (draft && draft.parse_source === 'scaffold') draftState = 'outline';
  else if (draft && draft.status === 'done') draftState = 'read';
  else if (draft && draft.status === 'failed') draftState = 'failed';
  else if (draft) draftState = 'unread';

  return {
    draftId, draftState, papers: library.length, read, failed, unread,
    nodes, themes, paperGaps, directions, checksDone, checksFailed,
    modelReady: providerReady(s.settings),
  };
}

function _stageDone(f) {
  return {
    collect: f.papers >= 1,
    understand: f.read >= 1 && f.nodes !== null && f.nodes > 0,
    angle: (f.themes !== null && f.themes > 0) || (f.directions !== null && f.directions > 0),
    write: f.draftState === 'read',
    check: f.draftState === 'read' && f.checksDone !== null && f.checksDone > 0,
  };
}

function _reason(key, f, done) {
  switch (key) {
    case 'collect':
      return f.papers ? `${_plural(f.papers, 'paper', 'papers')} in your library.` : 'No papers in your library yet.';
    case 'understand': {
      if (!f.papers) return 'Nothing to read until papers are added.';
      const failed = f.failed ? ` ${_plural(f.failed, 'paper', 'papers')} could not be read.` : '';
      if (!f.read) return `None of your ${_plural(f.papers, 'paper', 'papers')} has been read yet.${failed}`;
      const ofN = `${f.read} of ${_plural(f.papers, 'paper', 'papers')} read`;
      if (f.nodes === null) return `${ofN}; the concept graph has not been checked yet.`;
      if (!f.nodes) return `${ofN}, but the concept graph is empty.`;
      return `${ofN} and mapped in the concept graph.`;
    }
    case 'angle': {
      if (done) {
        const parts = [];
        if (f.themes) parts.push(_plural(f.themes, 'gap theme', 'gap themes'));
        if (f.directions) parts.push(_plural(f.directions, 'research direction', 'research directions'));
        return `${parts.join(' and ')}.`;
      }
      if (f.themes === null && f.directions === null) return 'Not checked yet.';
      const optional = f.draftId ? ' Optional once you have a draft.' : '';
      if (f.paperGaps) {
        return `${_plural(f.paperGaps, 'open problem', 'open problems')} found in your papers, not yet grouped into themes.${optional}`;
      }
      return `No gap themes or research directions yet.${optional}`;
    }
    case 'write':
      return {
        none: 'No draft set yet.',
        missing: 'The draft this research points to is not in its library.',
        outline: 'Your draft is an outline from a direction; the checks need a written draft.',
        unread: 'Your draft has been added but not read yet.',
        failed: 'Your draft could not be read.',
        read: 'Your draft is set and has been read.',
      }[f.draftState];
    case 'check': {
      if (f.draftState !== 'read') return 'Needs a draft that has been read.';
      if (f.checksDone === null) return 'Results for your draft have not been loaded.';
      const failed = f.checksFailed ? ` ${_plural(f.checksFailed, 'check', 'checks')} failed.` : '';
      if (!f.checksDone) return `No check has completed on this version of your draft.${failed}`;
      return `${_plural(f.checksDone, 'check has', 'checks have')} run on this draft.${failed}`;
    }
    default:
      return '';
  }
}

/** The single next step. Rules are tried top to bottom; the first match wins. */
function nextStep(f, done) {
  const model = f.modelReady;
  const step = (id, title, what, cost, costText, target, button, withModel = '') => ({
    id, title, what, cost, costLabel: COST_TEXT[cost], costText,
    ...target, button, withModel: model ? '' : withModel,
  });
  const connect = (why) => step(
    'connect-model', 'Connect a model so papers can be read',
    `${why ? `${why} ` : ''}Reading a paper means pulling out its concepts, methods and results, and that needs a model. Set one up in Settings; a local model runs on this machine.`,
    'free', 'Free to set up. Reading papers afterwards uses your model provider.',
    { route: '#/settings' }, 'Open Settings');
  const freeChecks = () => step(
    'run-free-checks', 'Run the free checks on your draft',
    'The reference, statistics, overlap and declarations checkers read your draft and report what they find. Choose them on the Agents page.'
      + (f.checksFailed ? ' A check failed last time; the reason is shown there.' : ''),
    'network', 'Free. Runs on this machine; the reference checker looks titles up in public catalogues.',
    { route: '#/agents' }, 'Open Agents',
    'With a model, agents can also judge novelty and how your citations are used.');

  // 1. Collect
  if (!done.collect) {
    return step(
      'add-papers', 'Add your first papers',
      'Upload PDFs, or add papers by DOI, arXiv id or title. They are kept in this research.',
      model ? 'model' : 'free',
      model ? 'Adding is free. Reading each paper then uses your model provider.'
        : 'Free. Without a model, papers are stored but not read.',
      { action: 'open-ingest' }, 'Add papers',
      'With a model connected, each paper is read and mapped into the concept graph.');
  }

  // 2. Understand
  if (!done.understand) {
    if (!model) {
      if (done.write && !done.check) return freeChecks();
      return connect(f.read ? '' : `None of your ${_plural(f.papers, 'paper', 'papers')} has been read yet.`);
    }
    if (!f.read) {
      return step(
        'read-papers', 'Get your papers read',
        `${_plural(f.unread + f.failed, 'paper has', 'papers have')} not been read yet. Library shows each one's progress, and lets you retry or add a missing PDF.`,
        'model', 'Opening Library is free. Reading a paper uses your model provider.',
        { route: '#/library' }, 'Open Library');
    }
    return step(
      'open-graph', 'Look at your knowledge graph',
      'The graph links the concepts and methods of the papers that have been read. If it is empty, rebuild it from Library.',
      'free', 'Free. Runs on this machine.',
      { route: '#/graph' }, 'Open Graph');
  }

  // 3. Find your angle (only before a draft exists)
  if (!done.angle && f.draftState === 'none') {
    if (model) {
      return step(
        'find-gaps', 'Find what your papers leave open',
        'Gaps collects the limitations and future work your papers state, and groups them into themes across your library.',
        'model', 'Opening Gaps is free. Grouping problems into themes uses your model provider, and runs only when you click Refresh gaps.',
        { route: '#/gaps' }, 'Open Gaps');
    }
    return step(
      'explore-graph', 'Explore your knowledge graph',
      'See which concepts and methods your papers share, and which appear in only one of them.',
      'free', 'Free. Runs on this machine.',
      { route: '#/graph' }, 'Open Graph',
      'With a model, Gaps groups what your papers leave open into themes, and Brainstorm proposes research directions.');
  }

  // 4. Write
  if (!done.write) {
    if (f.draftState === 'none' || f.draftState === 'missing') {
      return step(
        'add-draft', 'Add your draft',
        'Upload the paper you are writing; the rest of this research is compared against it. You can also start one from a direction in Brainstorm.',
        model ? 'model' : 'free',
        model ? 'Adding is free. Reading your draft uses your model provider.'
          : 'Free to add. Without a model your draft is stored but not read, so the checks cannot run on it yet.',
        { action: 'open-ingest-draft' }, 'Add your draft',
        'With a model connected, your draft is read and the checks can run on it.');
    }
    if (f.draftState === 'outline') {
      return step(
        'write-draft', 'Write your draft',
        'Your draft is an outline. Write it, then add the finished PDF as your draft so the checks can read it.',
        'free', 'Free.',
        { route: '#/draft' }, 'Open Draft');
    }
    if (f.draftState === 'failed') {
      return step(
        'fix-draft', 'See why your draft could not be read',
        'Library shows what went wrong and lets you add the PDF again.',
        'free', 'Free to open.',
        { route: '#/library' }, 'Open Library');
    }
    // unread
    if (!model) return connect('Your draft has been added but not read.');
    return step(
      'read-draft', 'Get your draft read',
      'Your draft has been added but not read yet. Library shows its progress and lets you retry.',
      'model', 'Opening Library is free. Reading your draft uses your model provider.',
      { route: '#/library' }, 'Open Library');
  }

  // 5. Check
  if (!done.check) return freeChecks();

  return step(
    'review-checks', 'Review what the checks found',
    'Each agent\'s last result on your draft is on the Agents page. Revise the draft, add the new version, and run the checks again.',
    'free', 'Free to open.',
    { route: '#/agents' }, 'Open Agents',
    'With a model, agents can also judge novelty and how your citations are used.');
}

/**
 * @param {object} input — see the module header
 * @returns {{stages: Array<{key,title,status,statusText,reason}>,
 *   current: string|null, next: object, modelReady: boolean}}
 */
export function researchPath(input) {
  const f = pathFacts(input);
  const done = _stageDone(f);
  const skipAngle = f.draftState !== 'none';
  let current = null;
  for (const { key } of STAGES) {
    if (done[key] || (key === 'angle' && skipAngle)) continue;
    current = key;
    break;
  }
  const stages = STAGES.map(({ key, title }) => {
    const status = done[key] ? 'done' : (key === current ? 'current' : 'not_started');
    return { key, title, status, statusText: STATUS_TEXT[status], reason: _reason(key, f, done[key]) };
  });
  return { stages, current, next: nextStep(f, done), modelReady: f.modelReady };
}
