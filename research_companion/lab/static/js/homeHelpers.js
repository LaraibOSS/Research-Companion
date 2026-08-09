/**
 * homeHelpers.js — pure model helper for the Home view's no-draft welcome hero.
 *
 * emptyHeroModel(state) derives the display model for the "Research Companion"
 * hero shown on /home when there is no draft yet. It is dependency-free aside
 * from the pure onboardingStep() import (no top-level DOM access), so it is
 * unit-testable under `node --test`.
 */
import { onboardingStep } from './components/onboarding.js';

/**
 * @param {object} state — store state ({ draftId, papers (Map), settings, ... })
 * @returns {{ heading: string, subline: string, activeStep: string, paperCount: number }}
 */
export function emptyHeroModel(state) {
  const papers = state.papers instanceof Map ? state.papers : new Map();
  const draftId = state.draftId;

  let paperCount = 0;
  for (const [id, p] of papers) {
    if (id !== draftId && !p.is_draft) paperCount++;
  }

  const subline = paperCount > 0
    ? `You've added ${paperCount} paper${paperCount === 1 ? '' : 's'} — add your draft to start analyzing them.`
    : 'Verify what your paper claims. Add your draft and the literature around it — get grounded, cited answers.';

  return {
    heading: 'Research Companion',
    subline,
    activeStep: onboardingStep(state),
    paperCount,
  };
}

/**
 * Pure model for the Home quick-nav card row: a fixed, ordered set of the
 * most important tabs. Each entry carries EITHER `route` (hash string) or
 * `action` (event key handled by home.js), never both. Node-testable.
 * @param {object} state — store state ({ draftId, papers (Map), ... })
 * @returns {Array<{key,label,desc,count,route?,action?}>}
 */
export function homeNavModel(state) {
  const papers = (state && state.papers instanceof Map) ? state.papers : new Map();
  const draftId = state ? state.draftId : null;

  let paperCount = 0;
  for (const [id, p] of papers) {
    if (id !== draftId && p && !p.is_draft) paperCount++;
  }

  return [
    { key: 'library',   label: 'Library',  desc: 'Your ingested papers and their status',        count: paperCount, route: '#/library' },
    { key: 'graph',     label: 'Graph',    desc: 'The concept knowledge graph of your papers',   count: null,       route: '#/graph' },
    { key: 'draft',     label: draftId ? 'Draft' : 'Set a draft', desc: 'How each paper aligns with what you\'re writing', count: null, route: '#/draft' },
    { key: 'ask',       label: 'Ask',      desc: 'Grounded Q&A with citations to your papers',   count: null,       route: '#/ask' },
    { key: 'timeline',  label: 'Timeline', desc: 'Concepts and methods over time',               count: null,       route: '#/timeline' },
    { key: 'citations', label: 'Citations',desc: 'Which cited references are in your library',   count: null,       action: 'open-citations' },
  ];
}
