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
