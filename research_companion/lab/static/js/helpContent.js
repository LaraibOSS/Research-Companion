/**
 * helpContent.js — per-page help copy: what a page does, what it is based on,
 * and whether AI is involved.
 *
 * Pure and dependency-free (no DOM, no store) so it is node-testable. Consumed
 * by components/helpPanel.js, which renders the persistent "?" affordance the
 * router attaches to every view.
 *
 * Writing rules for entries:
 *   what     — one short paragraph, plain language, from the user's side of the
 *              screen. What the page is FOR, not how it is built.
 *   basedOn  — where the content comes from (your library, your draft, the open
 *              web, a heuristic). This is the honesty line: a user must be able
 *              to tell what an output was computed from.
 *   aiUsed   — true when anything on the page is model-generated, which adds the
 *              verification disclaimer.
 */

/** Shown wherever AI-generated content appears. */
export const AI_DISCLAIMER =
  'AI-assisted. This is generated from the papers in your library — it can be '
  + 'incomplete or wrong. Always open the cited paper and verify before you rely '
  + 'on or cite anything here.';

/** Shown on pages whose output is computed, not model-generated. */
export const DETERMINISTIC_NOTE =
  'No AI is used here — this is computed directly from your library, so the same '
  + 'papers always give the same result.';

const _HELP = {
  home: {
    title: 'Home',
    what: 'Your starting point. On a brand-new workspace it offers the two ways in — '
      + 'brainstorm from an idea, or bring a draft you already have. Once you have work, '
      + 'it becomes a dashboard: what to do next, open suggestions, and your recent progress.',
    basedOn: 'Your active research: its papers, draft, and history.',
    aiUsed: false,
  },
  brainstorm: {
    title: 'Brainstorm',
    what: 'Start from just a topic. Search the real literature, add the papers you want to '
      + 'your library, then turn them into ranked research directions, a novelty check, and '
      + 'a brief of cited bullet points you can write around.',
    basedOn: 'Search results come from Semantic Scholar (falling back to OpenAlex, plus any '
      + 'connectors you enabled). Directions and the brief are built from the papers you '
      + 'added, your concept graph, and your open gaps — never from papers you do not have.',
    aiUsed: true,
  },
  library: {
    title: 'Library',
    what: 'Every paper in this research and its processing state. Papers you add are '
      + 'downloaded and analyzed in the background, so this page shows what is queued, what '
      + 'finished, and what failed. A failed paper usually means the PDF could not be '
      + 'downloaded — add it manually and it works like any other.',
    basedOn: 'The papers stored in this research on your machine.',
    aiUsed: false,
  },
  graph: {
    title: 'Graph',
    what: 'The concept-level map of your library: the concepts, methods, datasets and claims '
      + 'your papers share. A method used by five papers is one node linked back to all five, '
      + 'so you can see where the field clusters and where it is thin.',
    basedOn: 'Concepts extracted from each paper you added.',
    aiUsed: true,
  },
  draft: {
    title: 'Draft',
    what: 'How the literature lines up against the paper you are writing, section by section: '
      + 'which papers strengthen a section, which challenge it, and which offer an alternative '
      + '— each with quotes checked word-for-word against the source.',
    basedOn: 'Your draft\'s sections and the papers in your library that have been analyzed '
      + 'against it. A brand-new draft shows its outline until you run "Analyze this draft".',
    aiUsed: true,
  },
  timeline: {
    title: 'Timeline',
    what: 'Your library laid out by publication year, so you can see how the field moved: when '
      + 'a concept or method first appears, which years are crowded, and where the recent work '
      + 'sits. Use it to spot what is established versus what is still emerging, and to catch '
      + 'periods your reading has skipped.',
    basedOn: 'Publication years and extracted concepts of your papers. Papers missing a year '
      + 'cannot be placed — fill the year in from the Library to see them here.',
    aiUsed: false,
  },
  gaps: {
    title: 'Gaps',
    what: 'What your papers themselves say is unfinished. Each paper\'s stated limitations and '
      + 'future work are collected and grouped into themes across your whole library, so '
      + 'repeated open problems stand out as candidates for your own contribution.',
    basedOn: 'The limitations and future-work each paper states in its own text — grouped into '
      + 'themes. Nothing here is invented; every theme points back to the papers that raised it.',
    aiUsed: true,
  },
  report: {
    title: 'Report',
    what: 'A structured, cited literature review of your own library. It writes investigation '
      + 'questions for your topic, answers each one from your papers with citations, and lets '
      + 'you edit that question list before the expensive answering pass runs. Generate a plan '
      + 'first: planning is one model call and editing it is free, while answering costs one '
      + 'call per question.',
    basedOn: 'Only the papers in your library — never the open web. Coverage percentages are a '
      + 'keyword-search heuristic, not ground truth.',
    aiUsed: true,
  },
  ask: {
    title: 'Ask',
    what: 'Ask a question in plain language and get an answer assembled from your papers, with '
      + 'a citation to the exact paper and section behind every claim. Click a citation to open '
      + 'the source at that passage.',
    basedOn: 'Your library only. If the papers do not cover it, you get told so rather than a '
      + 'guess.',
    aiUsed: true,
  },
  compare: {
    title: 'Compare',
    what: 'A side-by-side of any two papers — what each claims, the methods and datasets they '
      + 'use, and where they agree or diverge.',
    basedOn: 'The extracted content of the two papers you pick.',
    aiUsed: true,
  },
  citations: {
    title: 'Citations',
    what: 'Your draft\'s bibliography checked against reality: which references resolve to real '
      + 'work, which are already in your library, and which are missing or unverifiable.',
    basedOn: 'Your draft\'s reference list, matched against your library and public catalogues '
      + '(Crossref, OpenAlex, arXiv, and any connectors you enabled).',
    aiUsed: false,
  },
  notes: {
    title: 'Notes',
    what: 'Everything you saved while reading — from an alignment card, an opportunity, the '
      + 'reader, or a brief bullet — in one list you can filter and export as a revision '
      + 'checklist.',
    basedOn: 'Notes you wrote yourself.',
    aiUsed: false,
  },
  researches: {
    title: 'Researches',
    what: 'Every research project you have. Each one is a separate workspace with its own '
      + 'papers, draft, graph and history — switch, rename, archive, or start a new one here.',
    basedOn: 'The projects stored on your machine.',
    aiUsed: false,
  },
};

const _GENERIC = {
  title: 'Research Companion',
  what: 'A local-first research workspace: collect the literature, understand it as a connected '
    + 'graph, and check your own draft against it.',
  basedOn: 'The papers and draft in your active research.',
  aiUsed: true,
};

/**
 * Look up help copy for a view.
 * @param {string} viewId — a route ('/graph'), a bare id ('graph'), or unknown.
 * @returns {{title, what, basedOn, aiUsed, disclaimer}} — never throws;
 *   unknown ids fall back to a generic entry.
 */
export function helpFor(viewId) {
  const key = String(viewId == null ? '' : viewId).replace(/^#?\/+/, '').trim().toLowerCase();
  const entry = _HELP[key] || _GENERIC;
  return {
    ...entry,
    disclaimer: entry.aiUsed ? AI_DISCLAIMER : DETERMINISTIC_NOTE,
  };
}

/** Ids that have a dedicated entry (everything else falls back). */
export function helpViewIds() {
  return Object.keys(_HELP);
}
